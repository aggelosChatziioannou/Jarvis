"""Low-level input actions via pyautogui.

Pure mechanics only — NO safety decisions here (bounds checks, mode gating,
confirmation and sensitive-input refusal all live in ``safety.py``). The
backend is injectable so the call shape is unit-testable without moving the
real mouse. Coordinates passed in are absolute virtual-desktop pixels (already
converted by ``monitor_map``).
"""

from __future__ import annotations

from typing import Optional

from ..debug import debug_log


def _real_pyautogui():
    import pyautogui

    # FAILSAFE on: slamming the cursor into a screen corner aborts the action,
    # a hard manual kill-switch for Assist/Auto. PAUSE 0 so we control timing.
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0
    return pyautogui


class Interactor:
    """Thin wrapper over pyautogui click/type/scroll/move."""

    def __init__(self, backend=None) -> None:
        self._pg = backend

    @property
    def pg(self):
        if self._pg is None:
            self._pg = _real_pyautogui()
        return self._pg

    def move_to(self, x: int, y: int, duration: float = 0.0) -> None:
        debug_log(f"interaction: move_to ({x},{y})", "vision")
        self.pg.moveTo(int(x), int(y), duration=duration)

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        debug_log(f"interaction: click ({x},{y}) {button} x{clicks}", "vision")
        self.pg.click(x=int(x), y=int(y), button=button, clicks=int(clicks))

    def type_text(self, text: str, interval: float = 0.01) -> None:
        debug_log(f"interaction: type {len(text)} chars", "vision")
        self.pg.typewrite(text, interval=interval)

    def scroll(self, amount: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Scroll by ``amount`` wheel clicks (positive = up, negative = down)."""
        debug_log(f"interaction: scroll {amount} at ({x},{y})", "vision")
        if x is not None and y is not None:
            self.pg.scroll(int(amount), x=int(x), y=int(y))
        else:
            self.pg.scroll(int(amount))
