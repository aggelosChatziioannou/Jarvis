"""Read Wispr Flow's real recording state, locally and fail-open.

Why this exists
---------------
The Wispr bridge drives Wispr Flow with a single *toggle* hotkey
(Ctrl+Win+Space) and used to track Wispr's recording state with one local
boolean. That is open-loop: a single missed or extra tap inverts the mapping
for the rest of the session (Jarvis "starts" what is really a stop, and vice
versa), which surfaces as "Wispr records but Jarvis captured nothing" or
"Jarvis says listening but Wispr never started".

To close the loop we need to OBSERVE whether Wispr is actually recording.
Characterisation (``scripts/characterise_wispr_overlay.py``) found that Wispr's
overlay window is geometry-invariant (its indicator is Electron web content,
invisible to Win32), but that **Wispr opens the microphone only while
recording**, and Windows records this in the per-application mic *consent
store*::

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager
        \\ConsentStore\\microphone\\NonPackaged\\<exe-path-with-#-separators>

Each entry has ``LastUsedTimeStart`` and ``LastUsedTimeStop`` (FILETIMEs).
While an app is actively capturing, ``LastUsedTimeStop == 0``; when it stops,
the stop gets a timestamp. This flips deterministically and in real time with
Wispr's recording state and is purely local (no audio, no content, nothing
leaves the machine).

Contract
--------
``WisprStateProbe.is_recording()`` returns ``True`` / ``False`` when confident,
or ``None`` when it cannot tell (non-Windows, missing ``winreg``, no Wispr
consent entry, or any error). The bridge treats ``None`` as "unknown" and
falls back to its previous behaviour, so this is never worse than before.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from ..debug import debug_log

# A reader returns True when Wispr is capturing the mic, False when it is not,
# or None when the state cannot be determined.
MicUsageReader = Callable[[], Optional[bool]]

# Consent-store sub-key rows: (subkey_name, last_used_start, last_used_stop).
ConsentRow = Tuple[str, int, int]

_WISPR_TOKENS = ("wisprflow", "wispr flow", "wispr")

_CONSENT_BASES = (
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore\microphone\NonPackaged",
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore\microphone",
)


def recording_from_consent_rows(rows: List[ConsentRow]) -> Optional[bool]:
    """Decide whether Wispr is recording from mic-consent rows.

    ``rows`` is ``[(subkey_name, last_used_start, last_used_stop), ...]`` and
    may include non-Wispr apps (they are filtered out). Among the Wispr entries
    we pick the one with the greatest ``last_used_start`` — the currently-active
    Wispr version — and report recording iff its ``last_used_stop == 0``.

    Selecting the max-start entry (rather than "any entry with stop == 0")
    prevents a stale ``stop == 0`` left by a crashed older-version install from
    reading as "recording". Returns ``None`` when no Wispr entry is present.
    """
    wispr = [
        (name, start, stop)
        for (name, start, stop) in rows
        if any(tok in name.lower() for tok in _WISPR_TOKENS)
    ]
    if not wispr:
        return None
    # Active version = greatest LastUsedTimeStart.
    _name, _start, stop = max(wispr, key=lambda r: r[1])
    return stop == 0


def _registry_mic_reader() -> Optional[bool]:
    """Default reader: read Wispr's mic state from the Windows consent store.

    Returns ``None`` on non-Windows, missing ``winreg``, no Wispr entry, or any
    error (fail-open). Never raises.
    """
    try:
        import winreg  # Windows-only stdlib
    except Exception:
        return None

    rows: List[ConsentRow] = []
    found_any = False
    for base in _CONSENT_BASES:
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not any(tok in sub.lower() for tok in _WISPR_TOKENS):
                    continue
                found_any = True
                try:
                    with winreg.OpenKey(root, sub) as k:
                        start = _query_int(winreg, k, "LastUsedTimeStart")
                        stop = _query_int(winreg, k, "LastUsedTimeStop")
                    if start is not None and stop is not None:
                        rows.append((sub, start, stop))
                except OSError:
                    continue
        finally:
            try:
                winreg.CloseKey(root)
            except Exception:
                pass

    if not found_any:
        return None
    return recording_from_consent_rows(rows)


def _query_int(winreg_mod, key, name: str) -> Optional[int]:
    try:
        value, _ = winreg_mod.QueryValueEx(key, name)
        return int(value)
    except (OSError, TypeError, ValueError):
        return None


class WisprStateProbe:
    """Fail-open probe for Wispr Flow's real recording state.

    Wraps an injectable :data:`MicUsageReader` (default: the local registry
    reader). ``is_recording()`` never raises; any failure yields ``None``.
    ``available()`` reports whether the last call produced a definite answer.
    """

    def __init__(self, reader: Optional[MicUsageReader] = None) -> None:
        self._reader: MicUsageReader = reader or _registry_mic_reader
        self._last: Optional[bool] = None

    def is_recording(self) -> Optional[bool]:
        try:
            result = self._reader()
        except Exception as e:  # fail-open: never raise into the caller
            debug_log(f"WisprStateProbe reader raised: {e!r}", "voice")
            self._last = None
            return None
        if result not in (True, False):
            self._last = None
            return None
        self._last = bool(result)
        return self._last

    def available(self) -> bool:
        """True when the last :meth:`is_recording` returned a definite bool."""
        return self._last in (True, False)
