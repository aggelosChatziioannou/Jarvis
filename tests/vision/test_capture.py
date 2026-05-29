"""Behaviour tests for vision.capture — multi-monitor screenshot grabbing.

The grabber (mss) is injected so tests run without a display and assert that
the correct screen region is requested for each monitor, and that an in-memory
PIL image is returned (never a file path).
"""

from PIL import Image

from jarvis.vision.capture import ScreenCapture
from jarvis.vision.monitor_map import MonitorMap


def _provider(monitors):
    left = min(m["left"] for m in monitors)
    top = min(m["top"] for m in monitors)
    right = max(m["left"] + m["width"] for m in monitors)
    bottom = max(m["top"] + m["height"] for m in monitors)
    virtual = {"left": left, "top": top, "width": right - left, "height": bottom - top}
    return lambda: [virtual] + list(monitors)


def _two_monitor_map():
    return MonitorMap(
        monitors_provider=_provider([
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 1920, "top": 0, "width": 2560, "height": 1440},
        ]),
        set_dpi=False,
    )


def _recording_grabber():
    """Return (grabber, calls) where grabber yields an image sized to region."""
    calls = []

    def grab(region):
        calls.append(dict(region))
        return Image.new("RGB", (region["width"], region["height"]))

    return grab, calls


def test_capture_primary_uses_primary_geometry():
    grab, calls = _recording_grabber()
    cap = ScreenCapture(monitor_map=_two_monitor_map(), grabber=grab)
    img = cap.capture_primary()
    assert calls[-1] == {"left": 0, "top": 0, "width": 1920, "height": 1080}
    assert isinstance(img, Image.Image)
    assert img.size == (1920, 1080)


def test_capture_secondary_uses_secondary_geometry():
    grab, calls = _recording_grabber()
    cap = ScreenCapture(monitor_map=_two_monitor_map(), grabber=grab)
    img = cap.capture_secondary()
    assert calls[-1] == {"left": 1920, "top": 0, "width": 2560, "height": 1440}
    assert img.size == (2560, 1440)


def test_capture_all_returns_one_image_per_monitor():
    grab, calls = _recording_grabber()
    cap = ScreenCapture(monitor_map=_two_monitor_map(), grabber=grab)
    imgs = cap.capture_all()
    assert len(imgs) == 2
    assert [i.size for i in imgs] == [(1920, 1080), (2560, 1440)]


def test_capture_region_passes_through_exact_box():
    grab, calls = _recording_grabber()
    cap = ScreenCapture(monitor_map=_two_monitor_map(), grabber=grab)
    img = cap.capture_region(100, 200, 300, 400)
    assert calls[-1] == {"left": 100, "top": 200, "width": 300, "height": 400}
    assert img.size == (300, 400)


def test_capture_returns_in_memory_image_not_path():
    # Privacy guarantee: capture yields a PIL Image held in memory, never a
    # filename on disk. (A path would be a str.)
    grab, _ = _recording_grabber()
    cap = ScreenCapture(monitor_map=_two_monitor_map(), grabber=grab)
    result = cap.capture_primary()
    assert isinstance(result, Image.Image)
    assert not isinstance(result, str)
