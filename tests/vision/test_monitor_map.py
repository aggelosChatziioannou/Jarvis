"""Behaviour tests for vision.monitor_map — the coordinate/DPI layer.

These assert observable outcomes (where an absolute click lands given a
model-relative coordinate on a given monitor), not internal state. The
monitor geometry is injected so the tests are deterministic and run without
a real display.
"""

import pytest

from jarvis.vision.monitor_map import MonitorMap, Monitor, ensure_dpi_awareness


def _provider(monitors):
    """Build an mss-style provider: index 0 is the virtual bounding box,
    1..n are the individual monitors (matching mss.mss().monitors)."""
    left = min(m["left"] for m in monitors)
    top = min(m["top"] for m in monitors)
    right = max(m["left"] + m["width"] for m in monitors)
    bottom = max(m["top"] + m["height"] for m in monitors)
    virtual = {"left": left, "top": top, "width": right - left, "height": bottom - top}
    return lambda: [virtual] + list(monitors)


def _map(monitors):
    return MonitorMap(monitors_provider=_provider(monitors), set_dpi=False)


# --- Geometry parsing ---------------------------------------------------

def test_individual_monitors_exclude_virtual_bbox():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ])
    assert len(mm.monitors) == 2
    # The virtual bbox (mss index 0) is never exposed as a real monitor.
    assert all(isinstance(m, Monitor) for m in mm.monitors)
    assert mm.monitors[0].index == 1 and mm.monitors[1].index == 2


def test_primary_is_the_monitor_at_origin():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ])
    assert mm.primary.index == 1
    assert mm.primary.is_primary is True
    assert mm.get("secondary").index == 2


def test_primary_fallback_when_no_monitor_at_origin():
    # Rare: a setup where no monitor sits exactly at (0,0). First one wins.
    mm = _map([
        {"left": 100, "top": 50, "width": 1920, "height": 1080},
    ])
    assert mm.primary.index == 1
    assert mm.primary.is_primary is True


# --- Relative -> absolute conversion (the core correctness) -------------

def test_absolute_on_primary_is_identity_offset():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ])
    assert mm.to_absolute(50, 60, "primary") == (50, 60)


def test_absolute_on_secondary_adds_offset():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ])
    # A point 100px from the left of the secondary monitor's own image must
    # map to x=2020 on the virtual desktop.
    assert mm.to_absolute(100, 200, "secondary") == (2020, 200)
    assert mm.to_absolute(100, 200, 2) == (2020, 200)


def test_absolute_handles_monitor_left_of_primary_negative_offset():
    # Secondary physically to the LEFT of primary -> negative left offset.
    # This is the classic case DPI-unaware/naïve code gets wrong.
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -1920, "top": 0, "width": 1920, "height": 1080},
    ])
    assert mm.to_absolute(100, 200, "secondary") == (-1820, 200)


def test_absolute_handles_monitor_above_primary_negative_top():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 0, "top": -1080, "width": 1920, "height": 1080},
    ])
    assert mm.to_absolute(10, 10, 2) == (10, -1070)


# --- Bounds validation (safety guard) -----------------------------------

def test_in_bounds_true_within_a_monitor():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ])
    assert mm.in_bounds(2020, 200) is True          # inside secondary
    assert mm.in_bounds(2020, 200, "secondary") is True


def test_in_bounds_false_outside_all_monitors():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
    ])
    assert mm.in_bounds(5000, 200) is False
    assert mm.in_bounds(-5, 200) is False


def test_in_bounds_respects_specific_monitor():
    mm = _map([
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ])
    # (10,10) is inside primary but NOT inside the secondary monitor.
    assert mm.in_bounds(10, 10, "secondary") is False
    assert mm.in_bounds(10, 10, "primary") is True


# --- Monitor helpers ----------------------------------------------------

def test_monitor_center_and_edges():
    m = Monitor(index=1, left=1920, top=0, width=1920, height=1080, is_primary=False)
    assert m.right == 3840
    assert m.bottom == 1080
    assert m.center == (1920 + 960, 540)
    assert m.contains(2000, 100) is True
    assert m.contains(100, 100) is False


def test_get_unknown_monitor_raises():
    mm = _map([{"left": 0, "top": 0, "width": 1920, "height": 1080}])
    with pytest.raises((KeyError, IndexError, ValueError)):
        mm.get("secondary")   # only one monitor present


# --- DPI awareness smoke -------------------------------------------------

def test_ensure_dpi_awareness_is_safe_and_returns_bool():
    # Must never raise regardless of platform; idempotent.
    result = ensure_dpi_awareness()
    assert isinstance(result, bool)
    assert ensure_dpi_awareness() == result
