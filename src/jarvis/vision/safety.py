"""Safety layer for screen interaction: modes, bounds, app gating, pending actions.

Every click/type/scroll passes through ``SafetyGuard.decide`` which returns one
of three verdicts the tool layer acts on:

  - ``execute``  — run now (AUTO mode on a whitelisted, non-blacklisted app)
  - ``confirm``  — stash a pending action and ask the user (ASSIST, or AUTO on
                   an unknown app); the LLM judges the spoken confirmation
  - ``refused``  — never run (OBSERVE mode, out-of-bounds, sensitive input, or
                   AUTO on a blacklisted app)

Hardcoded guards (no voice command can bypass them): screen-bounds validation,
sensitive-input refusal (Luhn-valid card / long account numbers), and the AUTO
blacklist. The foreground-app probe is injectable for testing.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Optional, Tuple

from ..debug import debug_log
from .monitor_map import MonitorMap, MonitorRef


class Mode(str, Enum):
    OBSERVE = "observe"   # describe/read/locate only; never acts
    ASSIST = "assist"     # proposes; executes only after voice confirmation
    AUTO = "auto"         # executes immediately on whitelisted apps


# Sensitive-input detection is digit/format based (Luhn card numbers, long
# account-number runs), NOT language keyword matching — so it stays correct for
# any language (CLAUDE.md: no hardcoded language patterns). Voice dictation of
# passwords is out of scope; the AUTO blacklist covers banking/password apps.
_DIGIT_GROUPS = re.compile(r"\d(?:[\d \-]{10,})\d")
_LONG_DIGIT_RUN = re.compile(r"\d{12,}")


def _luhn_ok(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def looks_sensitive(text: Optional[str]) -> bool:
    """True if the text contains a credit-card-like (Luhn-valid) or long
    account-number sequence that must never be typed automatically."""
    if not text:
        return False
    for m in _DIGIT_GROUPS.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 12 <= len(digits) <= 19 and _luhn_ok(digits):
            return True
    if _LONG_DIGIT_RUN.search(text):
        return True
    return False


def get_foreground_process_name() -> Optional[str]:
    """Process name of the foreground window (e.g. 'chrome.exe'). Windows only;
    returns None elsewhere or on any failure (fail-closed for AUTO)."""
    if sys.platform != "win32":
        return None
    try:
        import psutil
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name()
    except Exception as exc:  # pragma: no cover - platform/runtime dependent
        debug_log(f"safety: foreground app detect failed — {exc}", "vision")
        return None


@dataclass
class PendingAction:
    action: str                              # "click" | "type" | "scroll"
    target: Optional[str] = None
    text: Optional[str] = None
    coordinates: Optional[Tuple[int, int]] = None   # absolute desktop pixels
    monitor: object = None
    app: Optional[str] = None
    direction: Optional[str] = None
    amount: Optional[int] = None
    created_at: float = 0.0


@dataclass
class Decision:
    verdict: str                              # "execute" | "confirm" | "refused"
    reason: Optional[str] = None
    app: Optional[str] = None
    pending: Optional[PendingAction] = None


class SafetyGuard:
    """Gates screen-interaction actions and holds the single-slot pending action."""

    def __init__(
        self,
        monitor_map: MonitorMap,
        mode: Mode = Mode.ASSIST,
        auto_whitelist: Iterable[str] = (),
        auto_blacklist: Iterable[str] = (),
        pending_ttl_sec: float = 120.0,
        foreground_app_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self.monitors = monitor_map
        self.mode = mode
        self.auto_whitelist = {a.lower() for a in auto_whitelist}
        self.auto_blacklist = {a.lower() for a in auto_blacklist}
        self.pending_ttl = pending_ttl_sec
        self._foreground_app_fn = foreground_app_fn or get_foreground_process_name
        self._pending: Optional[PendingAction] = None

    # --- probes ---------------------------------------------------------

    def foreground_app(self) -> Optional[str]:
        try:
            return self._foreground_app_fn()
        except Exception:
            return None

    def validate_coordinates(self, x: int, y: int, monitor: Optional[MonitorRef] = None) -> bool:
        try:
            return self.monitors.in_bounds(x, y, monitor)
        except Exception:
            return False

    def _auto_allowed(self, app: Optional[str]) -> bool:
        if not app:
            return False
        return app.lower() in self.auto_whitelist

    def _auto_blacklisted(self, app: Optional[str]) -> bool:
        return bool(app) and app.lower() in self.auto_blacklist

    # --- the gate -------------------------------------------------------

    def decide(
        self,
        action: str,
        *,
        coordinates: Optional[Tuple[int, int]] = None,
        text: Optional[str] = None,
        monitor: Optional[MonitorRef] = None,
        target: Optional[str] = None,
        direction: Optional[str] = None,
        amount: Optional[int] = None,
        now: Optional[float] = None,
    ) -> Decision:
        now = time.time() if now is None else now

        # 1) Sensitive input is refused in every mode.
        if action == "type" and looks_sensitive(text):
            debug_log("safety: refused — sensitive input", "vision")
            return Decision(verdict="refused", reason="sensitive_input")

        # 2) Coordinate actions must land on a real monitor.
        if coordinates is not None and not self.validate_coordinates(
            coordinates[0], coordinates[1], monitor
        ):
            debug_log(f"safety: refused — out of bounds {coordinates}", "vision")
            return Decision(verdict="refused", reason="out_of_bounds")

        # 3) OBSERVE never acts.
        if self.mode == Mode.OBSERVE:
            return Decision(verdict="refused", reason="observe_mode")

        app = self.foreground_app()

        # 4) AUTO on a blacklisted app is hard-refused.
        if self.mode == Mode.AUTO and self._auto_blacklisted(app):
            debug_log(f"safety: refused — AUTO blacklisted app {app!r}", "vision")
            return Decision(verdict="refused", reason="auto_blacklisted", app=app)

        # 5) AUTO on a whitelisted app executes immediately.
        if self.mode == Mode.AUTO and self._auto_allowed(app):
            return Decision(verdict="execute", app=app)

        # 6) Everything else (ASSIST, or AUTO on an unknown app) -> confirm.
        pending = PendingAction(
            action=action,
            target=target,
            text=text,
            coordinates=coordinates,
            monitor=monitor,
            app=app,
            direction=direction,
            amount=amount,
            created_at=now,
        )
        self._pending = pending
        debug_log(f"safety: confirm required for {action} (app={app!r})", "vision")
        return Decision(verdict="confirm", app=app, pending=pending)

    # --- pending buffer -------------------------------------------------

    def has_pending(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return self._pending is not None and (now - self._pending.created_at) <= self.pending_ttl

    def take_pending(self, now: Optional[float] = None) -> Optional[PendingAction]:
        """Pop the pending action, or None if absent/expired. Single-slot:
        always clears the slot so a stale action can never fire later."""
        now = time.time() if now is None else now
        p = self._pending
        self._pending = None
        if p is None:
            return None
        if now - p.created_at > self.pending_ttl:
            debug_log("safety: pending action expired", "vision")
            return None
        return p

    def clear_pending(self) -> None:
        self._pending = None
