# Wispr Flow closed-loop start/stop synchronisation — design

**Date:** 2026-05-30
**Branch:** feat/voice-comms-fixes
**Status:** Approved design, ready for implementation planning
**Related code:** `src/jarvis/listening/wispr_bridge.py`, `src/jarvis/listening/listener.py`, `src/jarvis/config.py`, `src/jarvis/listening/listening.spec.md`
**Related memory/diagnosis:** multi-agent root-cause workflow 2026-05-30 (see `wispr-toggle-desync-rootcause`)

## 1. Problem

Jarvis drives Wispr Flow's hands-free dictation by simulating a single **toggle** hotkey (`Ctrl+Win+Space`) and tracks Wispr's recording state with one local boolean `_keys_held`. The coupling is **open-loop**: there is no channel that tells Jarvis whether Wispr is actually recording. Because one toggle does both start and stop, a single missed or extra tap (OS-eaten Win-chord, a Wispr hotkey rebound away from the default, Wispr's own 20-minute auto-stop, or Wispr's documented freeze on rapid start/stop) permanently **inverts** the mapping for the rest of the session. This produces two observed symptoms:

- **Symptom A** — Wispr records but Jarvis never shows listening / never captures the speech.
- **Symptom B** — Jarvis shows `[WAKE]`/listening but Wispr never started recording.

The bridge's internal PRESS/RELEASE accounting and locking were independently verified as **correct**; the defect is entirely at the open-loop boundary plus a clipboard-capture path that can silently drop a real transcript.

## 2. Goals / Non-goals

**Goals**
- Close the loop: read Wispr Flow's real recording state and reconcile the bridge to it before and after every tap.
- Make a missed/extra tap **self-correcting** instead of a permanent inversion.
- Stop the HUD from claiming "listening" when recording was never confirmed.
- Fix the verified capture-path drops (repeat-phrase, missing erase config, too-short timeout).
- Be strictly **fail-open**: when Wispr state cannot be observed, behaviour is no worse than today.
- Keep everything **local** (privacy-first): observe only local window metadata, never any cloud API.

**Non-goals (YAGNI)**
- No WASAPI / microphone-session detection (risk of false positives; heavier COM).
- No change to the bridge's internal locking model (verified correct).
- No changes to the Whisper STT path or unrelated listener logic.
- No acoustic echo cancellation or other unrelated voice work.

## 3. Architecture

Convert the "blind toggle" into a **level-seeking, verified** control:

```
wake/trigger
   -> _ensure_recording(True): tap ONLY if observed state != target
   -> confirm recording started (poll probe, bounded)
        -> confirmed: DICTATING + HUD "listening"
        -> not confirmed: one corrective re-tap; still failing -> on_wispr_unavailable()
   -> VAD silence / timeout
   -> _ensure_recording(False): tap ONLY if still recording
   -> confirm stopped
   -> capture via clipboard-sequence -> dispatch
```

Every reconciliation point consults a single new abstraction, `WisprStateProbe`, whose `is_recording()` returns `True` / `False` / `None` (`None` = "cannot tell" = fall back to current behaviour).

## 4. Components

### 4.1 `WisprStateProbe` — `src/jarvis/listening/wispr_state.py` (new)

Single responsibility: report whether Wispr Flow is currently recording, by reading Windows' per-application **microphone-usage** record (the privacy "in-use" indicator) for Wispr Flow.

**Empirical basis (characterisation, §4.4):** Wispr's overlay window (`Chrome_WidgetWin_1` / title `Status`) is **always present and geometry-invariant** — its recording indicator is drawn inside the Electron web content, so no top-level Win32 window attribute changes between idle and recording. The window approach is therefore **not viable**. However, characterisation found that **Wispr opens the microphone only while recording**, and Windows records this in `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged\<exe-path>`: while an app is actively capturing, its `LastUsedTimeStop == 0`; when it stops, `LastUsedTimeStop` gets a FILETIME. This flips deterministically and in real time with Wispr's recording state, and is the discriminator used.

**Public interface**
```python
MicUsageReader = Callable[[], bool | None]  # True=Wispr capturing, False=not, None=unknown

class WisprStateProbe:
    def __init__(self, reader: MicUsageReader | None = None) -> None: ...
    def is_recording(self) -> bool | None:
        """True/False when confident; None when it cannot tell (fail-open)."""
    def available(self) -> bool:
        """True when the reader returned a definite True/False on the last call."""
```

- **`MicUsageReader`** is a thin injectable seam. The default implementation reads the registry consent store with `winreg` (stdlib, no new dependency): it enumerates `...\microphone\NonPackaged` (and the packaged store as a fallback) for sub-keys whose name contains `WisprFlow`/`Wispr Flow`, picks the entry with the **greatest `LastUsedTimeStart`** (the currently-active Wispr version, ignoring stale older-version installs), and reports recording iff that entry's `LastUsedTimeStop == 0`. Tests inject a fake reader — **no real registry in CI**.
- **Why max-start:** there are many stale per-version sub-keys (old installs), all with a non-zero stop. Selecting the max-`LastUsedTimeStart` entry tracks the active version and prevents a stale `stop == 0` (e.g. from a past crash) on an inactive version from reading as "recording".
- **Fail-open everywhere:** non-Windows, missing `winreg`, no Wispr consent entry, or any exception -> `None`. Never raises.
- **No process/PID resolution needed:** the registry read is keyed by exe path, not a live PID, so the probe does not enumerate processes or windows.
- **Privacy:** reads only local registry mic-usage timestamps for Wispr. Nothing is sent anywhere; no audio, no content, purely a local boolean "is Wispr capturing the mic".

### 4.2 Bridge integration — `src/jarvis/listening/wispr_bridge.py`

- **Inject the probe.** New constructor parameter `state_probe: WisprStateProbe | None = None`; defaults to a real probe when `None` and `wispr_closed_loop_enabled` is true, else a no-op probe whose `is_recording()` always returns `None`. Tests pass a `FakeProbe`.
- **`_ensure_recording(target: bool) -> bool`** replaces the blind `_do_press_keys`/`_do_release_keys` toggle decision:
  1. Read `observed = probe.is_recording()`.
  2. If `observed is None`: fall back to the current `_keys_held`-gated behaviour (today's logic) plus the §4.3 guards.
  3. If `observed == target`: reconcile `_keys_held = target`, send **no** tap (the toggle is already where we want it; this is the inversion-healing step).
  4. If `observed != target`: tap once, then **confirm** by polling `is_recording()` up to `wispr_confirm_timeout_sec` (default 1.2, poll ~50 ms). On success set `_keys_held = target`. On failure send **one** corrective re-tap and re-confirm. Still failing -> return `False` (caller surfaces unavailability).
- **`_start_dictation`** keeps an early provisional UI but only promotes to confirmed "listening" once a start is confirmed; when `_ensure_recording(True)` returns `False`, fire the new optional callback **`on_wispr_unavailable()`** so the listener can show "Wispr did not start" instead of a false "listening". When the probe is unavailable (`None`), preserve today's behaviour (show listening immediately).
- **`start()` startup reconciliation:** initialise `_keys_held` from `probe.is_recording()` when confident; if Wispr is found **recording** at boot, force it OFF to a known IDLE before going live. The startup force-OFF is exempt from the §4.2 minimum inter-tap gap (there is no prior tap to gate against), so it is unaffected by `wispr_min_tap_gap_sec`.
- **`on_dictation_end(captured=False)` path / `_post_dictation_worker`:** when a turn produced no transcript, query the probe; if Wispr is still recording, `_ensure_recording(False)` to force a known IDLE. This turns the most diagnostic moment into a recovery point.
- **Cheap guards (always on, independent of the probe):**
  - **Configurable hotkey:** new `wispr_hands_free_combo` (default `["ctrl", "cmd", "space"]`) drives `_tap_hands_free_toggle_locked` instead of the hardcoded chord, so a user whose Wispr binding differs can match it. Unknown key names fall back to the default with a logged warning.
  - **Minimum inter-tap gap:** `_key_worker` enforces `wispr_min_tap_gap_sec` (default 0.5) between consecutive toggle taps, to avoid Wispr's documented rapid-start/stop freeze.

### 4.3 Heuristic fallback (when the probe returns `None`)

When the probe cannot observe Wispr, the bridge keeps today's `_keys_held` logic but adds two conservative, opt-in-safe guards already listed: configurable combo and the minimum inter-tap gap. No blind corrective toggling is performed in this mode (a blind corrective tap with no readback could itself invert state), so fail-open mode is never worse than today.

### 4.4 Signal characterisation (implementation step 1) — DONE

`scripts/characterise_wispr_overlay.py` (`-X utf8`) snapshots Wispr Flow's top-level windows **and** its mic-consent registry entries across three phases (idle -> recording -> idle), driving Wispr with a single `Ctrl+Win+Space` `pynput` tap.

**Result (2026-05-30, this machine):**
- **Window attributes are state-invariant** — the `Status` overlay stays `visible`, `440x320`, at `(1060,1070)` in all three phases. Top-level window enumeration cannot distinguish recording. (Overlay approach rejected.)
- **Mic-usage registry flips deterministically** — the active version (`...WisprFlow\app-1.5.559\Wispr Flow.exe`) reads `LastUsedTimeStop == 0` (IN_USE) only during recording, and a FILETIME stop otherwise. The tap was confirmed to toggle Wispr (so the hands-free binding is `Ctrl+Win+Space` and `pynput` injection is honoured on this machine). This is the discriminator.

**Latency note:** the registry flips within the ~1.6 s post-tap snapshot window; `wispr_confirm_timeout_sec` defaults to `1.2` to comfortably cover the start/stop-to-registry latency.

**Fallback unchanged:** if on some machine no Wispr mic-consent entry exists, the reader returns `None` and the bridge degrades to the §4.3 guards; the capture-path fixes still ship.

### 4.5 Capture-path fixes — `wispr_bridge.py` + `config.py`

- **Clipboard-sequence capture:** use Win32 `GetClipboardSequenceNumber()` to detect that the clipboard changed even when the new transcript text is byte-identical to the baseline (the verified repeat-phrase drop). Baseline = sequence number at `_start_dictation`; dispatch when the sequence advances **and** the current clipboard value is non-empty. On non-Windows or any failure, fall back to the current exact-text diff. A new test asserts an identical re-utterance is still dispatched.
- **Declare the two silently-undeclared Wispr fields** in `config.py` (dataclass field + defaults + builder + constructor, mirroring `wispr_suppress_autotype`):
  - `wispr_erase_max_chars` — read at `wispr_bridge.py:1212` via `getattr(..., 300)` but never declared.
  - `wispr_barge_in_interrupt` — read at `wispr_bridge.py:1376` via `getattr(..., True)` but never declared. Same defect class; fixed here because we are already touching the same four config sites. No behaviour change (default preserves today's `True`).
- **Smarter timeout / diagnosable no-capture:** after `clipboard_wait_sec` elapses, do one final grace check (`wispr_clipboard_grace_sec`, default 2.0) before declaring `captured=False`; propagate a **reason** so the listener notice can distinguish "pyperclip missing" from "identical phrase" from "cloud too slow". **Delivery mechanism:** extend the existing callback to `on_dictation_end(captured: bool, reason: str | None = None)` with a backward-compatible default (`reason=None`); update the listener handler `_on_wispr_dictation_end(self, captured: bool = True, reason: str | None = None)` accordingly. `reason` is one of `"off"` (clipboard polling disabled), `"timeout"` (no clipboard change within the wait+grace), `"unchanged"` (clipboard present but never advanced), or `None` (captured). The optional-keyword shape keeps any other caller/test of the callback working unchanged.

### 4.6 Config fields (config.py)

| Field | Default | Purpose |
|-------|---------|---------|
| `wispr_closed_loop_enabled` | `true` | Master switch for the probe + reconciliation. `false` -> §4.3 fail-open behaviour only. |
| `wispr_hands_free_combo` | `["ctrl","cmd","space"]` | Simulated hands-free toggle chord, to match the user's Wispr binding. |
| `wispr_min_tap_gap_sec` | `0.5` | Minimum gap between consecutive toggle taps. |
| `wispr_confirm_timeout_sec` | `1.2` | How long to poll the probe to confirm a tap took effect (covers registry latency). |
| `wispr_erase_max_chars` | `300` | Existing-but-undeclared cap on auto-type erase. |
| `wispr_barge_in_interrupt` | `true` | Existing-but-undeclared barge-in toggle (declared here for consistency; default preserves current behaviour). |
| `wispr_clipboard_grace_sec` | `2.0` | Extra grace after the clipboard wait before declaring no-capture. |

All are config-driven and tunable; tests assert against the config-derived references, not hardcoded literals.

`wispr_closed_loop_enabled` defaults to `true` and this is **safe before characterisation**: an un-characterised or unreliable overlay signal makes `WisprStateProbe.is_recording()` return `None`, which the bridge treats as "unknown" and degrades to the §4.3 fail-open behaviour (today's logic plus the two cheap guards). The master switch therefore never makes things worse even on a machine where §4.4 has not yet run; it exists so the probe path can be disabled wholesale if ever needed.

## 5. Error handling

- Every probe call is wrapped; any failure yields `None` (treated as "unknown", current behaviour). The probe never raises into the audio/key threads.
- The confirm loop is bounded by `wispr_confirm_timeout_sec` and runs on the key-worker thread, never on the PortAudio callback.
- Non-Windows: the probe is permanently `None`; the capture-path clipboard-sequence falls back to exact-text diff. The feature degrades to today's behaviour with the two cheap guards.

## 6. Testing strategy (TDD — tests first)

- **`wispr_state.py` (unit, fake reader):** `is_recording()` returns `True` when the reader reports Wispr capturing, `False` when not, `None` when the reader returns `None` or raises; `available()` reflects the last definite reading. A separate parser-level test feeds crafted registry rows (active-version `stop==0` -> recording; stale `stop==0` on a smaller-start entry ignored) to the max-start selection logic.
- **Bridge (behaviour, `FakeProbe`):**
  - Desync heal: probe reports recording while `_keys_held` is `False` on a start request -> bridge sends **no** start tap and reconciles to recording (no inversion).
  - Missed PRESS: probe never reports recording after a start tap -> bridge re-taps once, then fires `on_wispr_unavailable` -> exactly the observable signature, no false "listening".
  - `captured=False` with probe still recording -> bridge forces OFF.
  - Min inter-tap gap enforced by `_key_worker`.
  - Configurable combo: a non-default `wispr_hands_free_combo` is the chord actually tapped.
  - Startup reconciliation: Wispr recording at `start()` -> forced OFF.
  - Fail-open: probe `None` -> today's behaviour (one START tap, one STOP tap) unchanged (regression guard).
- **Capture-path (behaviour):** identical re-utterance (same clipboard text, advanced sequence) is dispatched; `wispr_erase_max_chars` is read from config; no-capture reason is propagated.
- **Config:** new fields present with documented defaults; `test_config_models` extended.
- **Integration (opt-in, skipped in CI):** a marker-gated test that exercises the real Win32 probe against a running Wispr Flow, plus the characterisation script.

Run: `.venv\Scripts\python.exe -m pytest tests/ -m unit`. The ~11 pre-existing base-commit failures (hot_window/enrichment/mcp_client/updater/VRAM) are unrelated and must not be attributed to this work.

## 7. Spec-file maintenance

Per the project spec-registry rule, add a **Wispr bridge** section to `src/jarvis/listening/listening.spec.md` documenting: the tap-and-toggle hands-free coupling, the `Ctrl+Win+Space` prerequisite and its configurability, the closed-loop `WisprStateProbe` contract (`True`/`False`/`None`, fail-open), `_ensure_recording` level-seeking, startup reconciliation, the cheap guards, and the clipboard-sequence capture. Update `docs/llm_contexts.md` only if an LLM context changes (it does not here).

## 8. Rollout / risk

- The master switch `wispr_closed_loop_enabled` allows instant rollback to fail-open behaviour without code changes.
- The riskiest dependency (the undocumented overlay signal) is isolated behind the probe and gated by the characterisation acceptance criterion; a negative result degrades safely to the cheap guards plus capture-path fixes.
- Changes are committed incrementally (probe, bridge integration, capture-path, config, spec) so each step is independently testable and revertible.
