"""Monitor geometry, DPI awareness, and relative→absolute coordinate mapping.

This is the single most correctness-critical module in the vision engine on
Windows. A vision model returns coordinates *relative to the image it was
shown* (0,0 = top-left of the captured monitor). ``pyautogui`` needs *absolute*
virtual-desktop coordinates. The conversion is a simple offset add — **but only
if** capture (``mss``, physical pixels) and the click backend (``pyautogui``)
share one coordinate space. Under Windows display scaling (125%/150%) a
DPI-unaware process is fed *virtualised* (logical) pixels by Windows, so the two
diverge and every click lands wrong.

The fix has two parts, both owned here:
  1. ``ensure_dpi_awareness()`` makes the process per-monitor-DPI-aware so both
     ``mss`` and ``pyautogui`` see physical pixels.
  2. ``MonitorMap.to_absolute()`` adds the monitor's physical offset.

Geometry is injectable (``monitors_provider``) so the maths is unit-testable
without a real display.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from typing import Callable, List, Optional, Tuple, Union

from ..debug import debug_log

MonitorRef = Union[int, str]

# Module-level latch so repeated MonitorMap construction doesn't hammer the
# Win32 call; awareness is a process-wide setting.
_dpi_awareness_set: Optional[bool] = None


def ensure_dpi_awareness() -> bool:
    """Make this process per-monitor DPI aware (Windows). No-op elsewhere.

    Idempotent and exception-safe. Returns True when awareness is (or was
    already) set, False if it could not be established. Must run before any
    capture or click so physical/logical pixel spaces agree.
    """
    global _dpi_awareness_set
    if _dpi_awareness_set is not None:
        return _dpi_awareness_set

    if sys.platform != "win32":
        _dpi_awareness_set = False
        return False

    import ctypes

    # Preferred: per-monitor-v2 via the modern context API (Win10 1703+).
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        ctx = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctx):
            debug_log("monitor_map: DPI awareness = per-monitor-v2 (context)", "vision")
            _dpi_awareness_set = True
            return True
    except Exception:
        pass

    # Fallback: shcore per-monitor (Win8.1+). Raises if already set -> success.
    try:
        PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
        debug_log("monitor_map: DPI awareness = per-monitor (shcore)", "vision")
        _dpi_awareness_set = True
        return True
    except OSError:
        # E_ACCESSDENIED: awareness already set for the process (e.g. manifest).
        debug_log("monitor_map: DPI awareness already set", "vision")
        _dpi_awareness_set = True
        return True
    except Exception:
        pass

    # Last resort: system-DPI aware (Vista+). Better than nothing on scaled displays.
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        debug_log("monitor_map: DPI awareness = system (legacy)", "vision")
        _dpi_awareness_set = True
        return True
    except Exception:
        debug_log("monitor_map: could not set DPI awareness", "error")
        _dpi_awareness_set = False
        return False


@dataclass(frozen=True)
class Monitor:
    """A single physical monitor in virtual-desktop (physical-pixel) space."""

    index: int          # 1-based logical index (matches mss.monitors[index])
    left: int
    top: int
    width: int
    height: int
    is_primary: bool
    scale: float = 1.0  # DPI scale (dpi/96); best-effort, for diagnostics only

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> Tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


def _default_mss_monitors() -> list:
    """Live monitor geometry from mss. Index 0 is the virtual bounding box."""
    import mss  # imported lazily so unit tests never need a display

    with mss.mss() as sct:
        # Copy to plain dicts so the sct context can close.
        return [dict(m) for m in sct.monitors]


class MonitorMap:
    """Maps logical monitor references and converts relative→absolute coords."""

    def __init__(
        self,
        monitors_provider: Optional[Callable[[], list]] = None,
        set_dpi: bool = True,
    ) -> None:
        if set_dpi:
            ensure_dpi_awareness()
        self._provider = monitors_provider or _default_mss_monitors
        self._monitors: List[Monitor] = []
        self.virtual: dict = {}
        self.refresh()

    def refresh(self) -> None:
        """Re-read monitor geometry (call after a display hot-plug)."""
        raw = list(self._provider())
        if not raw:
            self._monitors = []
            self.virtual = {}
            return
        # mss convention: [0] is the union of all monitors; [1:] are real ones.
        self.virtual = dict(raw[0]) if len(raw) >= 1 else {}
        individual = raw[1:] if len(raw) > 1 else raw

        mons: List[Monitor] = []
        for i, m in enumerate(individual, start=1):
            is_primary = (int(m["left"]) == 0 and int(m["top"]) == 0)
            mons.append(
                Monitor(
                    index=i,
                    left=int(m["left"]),
                    top=int(m["top"]),
                    width=int(m["width"]),
                    height=int(m["height"]),
                    is_primary=is_primary,
                    scale=float(m.get("scale", 1.0)),
                )
            )
        # Guarantee exactly one primary even on odd layouts (none at origin).
        if mons and not any(m.is_primary for m in mons):
            mons[0] = replace(mons[0], is_primary=True)
        self._monitors = mons
        debug_log(
            f"monitor_map: {len(mons)} monitor(s) "
            + ", ".join(f"#{m.index}({m.left},{m.top},{m.width}x{m.height})" for m in mons),
            "vision",
        )

    @property
    def monitors(self) -> List[Monitor]:
        return list(self._monitors)

    @property
    def primary(self) -> Monitor:
        for m in self._monitors:
            if m.is_primary:
                return m
        if self._monitors:
            return self._monitors[0]
        raise ValueError("no monitors detected")

    @property
    def _secondary(self) -> Monitor:
        for m in self._monitors:
            if not m.is_primary:
                return m
        raise IndexError("no secondary monitor present")

    def get(self, which: MonitorRef) -> Monitor:
        """Resolve a monitor by 1-based index or by name ('primary'/'secondary')."""
        if isinstance(which, bool):  # guard: bool is an int subclass
            raise ValueError(f"invalid monitor reference: {which!r}")
        if isinstance(which, int):
            for m in self._monitors:
                if m.index == which:
                    return m
            raise IndexError(f"no monitor with index {which}")
        key = str(which).strip().lower()
        if key in ("primary", "main", "1"):
            return self.primary
        if key in ("secondary", "second", "2"):
            return self._secondary
        if key in ("both", "all"):
            # Callers that mean "both" should iterate .monitors; for a single
            # reference we return primary as the safe default.
            return self.primary
        raise KeyError(f"unknown monitor reference: {which!r}")

    def to_absolute(self, rel_x: int, rel_y: int, which: MonitorRef = "primary") -> Tuple[int, int]:
        """Convert a model-relative coordinate to an absolute desktop coordinate."""
        m = self.get(which)
        return (m.left + int(rel_x), m.top + int(rel_y))

    def in_bounds(self, x: int, y: int, which: Optional[MonitorRef] = None) -> bool:
        """True if (x, y) lies within a given monitor, or any monitor if which is None."""
        if which is None:
            return any(m.contains(x, y) for m in self._monitors)
        return self.get(which).contains(x, y)
