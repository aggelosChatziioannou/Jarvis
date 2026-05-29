"""Multi-monitor screen capture via ``mss``.

Returns in-memory ``PIL.Image`` objects only — screenshots are the highest-risk
data in the app, so they are **never written to disk** (CLAUDE.md: privacy
first). The ``mss`` grabber is injectable so the conversion logic is testable
without a real display.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from ..debug import debug_log
from .monitor_map import MonitorMap, MonitorRef, ensure_dpi_awareness


def _mss_grab(region: dict):
    """Grab a single region with mss and return an RGB PIL Image (in-memory)."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(region)
    # mss returns BGRA bytes; convert to RGB without touching disk.
    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


class ScreenCapture:
    """Captures whole monitors or arbitrary regions as PIL Images."""

    def __init__(
        self,
        monitor_map: Optional[MonitorMap] = None,
        grabber: Optional[Callable[[dict], "object"]] = None,
    ) -> None:
        ensure_dpi_awareness()
        self.monitors = monitor_map if monitor_map is not None else MonitorMap()
        self._grab = grabber or _mss_grab

    def capture_monitor(self, which: MonitorRef = "primary"):
        m = self.monitors.get(which)
        region = {"left": m.left, "top": m.top, "width": m.width, "height": m.height}
        debug_log(f"capture: monitor {which!r} region={region}", "vision")
        return self._grab(region)

    def capture_primary(self):
        return self.capture_monitor("primary")

    def capture_secondary(self):
        return self.capture_monitor("secondary")

    def capture_all(self) -> List["object"]:
        return [self.capture_monitor(m.index) for m in self.monitors.monitors]

    def capture_region(self, left: int, top: int, width: int, height: int):
        region = {
            "left": int(left),
            "top": int(top),
            "width": int(width),
            "height": int(height),
        }
        debug_log(f"capture: region={region}", "vision")
        return self._grab(region)
