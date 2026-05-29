"""Behaviour tests for vision.safety — the guard that gates every action.

Asserts observable verdicts (execute / confirm / refused) per mode, bounds and
foreground-app gating, sensitive-input refusal, and the single-slot pending
buffer with TTL. The foreground-app probe and monitor geometry are injected.
"""

import pytest

from jarvis.vision.monitor_map import MonitorMap
from jarvis.vision.safety import Mode, SafetyGuard, looks_sensitive


def _monitors():
    return MonitorMap(
        monitors_provider=lambda: [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ],
        set_dpi=False,
    )


def _guard(mode=Mode.ASSIST, app="notepad.exe", **kw):
    kw.setdefault("pending_ttl_sec", 120.0)
    return SafetyGuard(
        monitor_map=_monitors(),
        mode=mode,
        auto_whitelist=("notepad.exe", "spotify.exe"),
        auto_blacklist=("chrome.exe", "1password.exe"),
        foreground_app_fn=lambda: app,
        **kw,
    )


# --- mode gating --------------------------------------------------------

def test_observe_mode_refuses_all_actions():
    d = _guard(mode=Mode.OBSERVE).decide("click", coordinates=(100, 100), monitor="primary")
    assert d.verdict == "refused"
    assert d.reason == "observe_mode"


def test_assist_mode_requires_confirmation_and_stashes_pending():
    g = _guard(mode=Mode.ASSIST)
    d = g.decide("click", coordinates=(100, 100), monitor="primary", target="Submit")
    assert d.verdict == "confirm"
    assert g.has_pending() is True


def test_auto_mode_executes_on_whitelisted_app():
    d = _guard(mode=Mode.AUTO, app="spotify.exe").decide(
        "click", coordinates=(100, 100), monitor="primary", target="Next")
    assert d.verdict == "execute"
    assert d.app == "spotify.exe"


def test_auto_mode_refuses_on_blacklisted_app():
    d = _guard(mode=Mode.AUTO, app="chrome.exe").decide(
        "click", coordinates=(100, 100), monitor="primary", target="Buy")
    assert d.verdict == "refused"
    assert d.reason == "auto_blacklisted"


def test_auto_mode_unknown_app_degrades_to_confirm():
    d = _guard(mode=Mode.AUTO, app="some_unknown.exe").decide(
        "click", coordinates=(100, 100), monitor="primary", target="X")
    assert d.verdict == "confirm"


# --- safety guards ------------------------------------------------------

def test_out_of_bounds_coordinates_refused_even_in_auto():
    d = _guard(mode=Mode.AUTO, app="spotify.exe").decide(
        "click", coordinates=(5000, 100), monitor="primary", target="X")
    assert d.verdict == "refused"
    assert d.reason == "out_of_bounds"


def test_type_sensitive_input_is_refused():
    # A Luhn-valid card number must never be typed, in any mode.
    d = _guard(mode=Mode.ASSIST).decide("type", text="my card is 4242 4242 4242 4242")
    assert d.verdict == "refused"
    assert d.reason == "sensitive_input"


def test_type_ordinary_text_is_allowed_to_confirm():
    d = _guard(mode=Mode.ASSIST).decide("type", text="hello world")
    assert d.verdict == "confirm"


# --- pending buffer -----------------------------------------------------

def test_take_pending_returns_once_then_empty():
    g = _guard(mode=Mode.ASSIST)
    g.decide("click", coordinates=(100, 100), monitor="primary", target="Submit")
    p = g.take_pending()
    assert p is not None and p.action == "click" and p.coordinates == (100, 100)
    assert g.take_pending() is None      # single-slot, consumed


def test_take_pending_none_when_expired():
    g = _guard(mode=Mode.ASSIST, pending_ttl_sec=10.0)
    g.decide("click", coordinates=(100, 100), monitor="primary", target="Submit", now=1000.0)
    # 11s later -> expired
    assert g.take_pending(now=1011.0) is None


def test_newer_pending_overwrites_older():
    g = _guard(mode=Mode.ASSIST)
    g.decide("click", coordinates=(100, 100), monitor="primary", target="First")
    g.decide("click", coordinates=(200, 200), monitor="primary", target="Second")
    p = g.take_pending()
    assert p.target == "Second" and p.coordinates == (200, 200)


def test_clear_pending():
    g = _guard(mode=Mode.ASSIST)
    g.decide("click", coordinates=(100, 100), monitor="primary", target="Submit")
    g.clear_pending()
    assert g.has_pending() is False


# --- sensitive-input detector -------------------------------------------

def test_looks_sensitive_detects_luhn_card():
    assert looks_sensitive("4242 4242 4242 4242") is True
    assert looks_sensitive("4242-4242-4242-4242") is True


def test_looks_sensitive_detects_long_digit_run():
    assert looks_sensitive("account 12345678901234") is True


def test_looks_sensitive_false_for_ordinary_text():
    assert looks_sensitive("hello world") is False
    assert looks_sensitive("call me at 555 1234") is False
    assert looks_sensitive("") is False
