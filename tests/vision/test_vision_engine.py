"""Behaviour tests for VisionEngine orchestration.

Collaborators are injected: a fake capture/client/interactor, a real
MonitorMap + SafetyGuard (so gating and coordinate conversion are exercised
for real), and stubbed OCR. Asserts the locate fallback chain, action gating,
and the two-turn confirm flow via observable results + interactor calls.
"""

from PIL import Image

from jarvis.vision.monitor_map import MonitorMap
from jarvis.vision.safety import Mode, SafetyGuard
from jarvis.vision.vision_engine import VisionEngine


def _monitors():
    # mss convention: index 0 is the virtual bounding box, 1.. are real monitors.
    return MonitorMap(
        monitors_provider=lambda: [
            {"left": 0, "top": 0, "width": 3840, "height": 1080},   # virtual bbox
            {"left": 0, "top": 0, "width": 1920, "height": 1080},   # primary
            {"left": 1920, "top": 0, "width": 1920, "height": 1080},  # secondary
        ],
        set_dpi=False,
    )


class _Cap:
    def capture_monitor(self, which="primary"):
        return Image.new("RGB", (1920, 1080))


class _Client:
    def __init__(self, desc="a window", point=None):
        self._desc = desc
        self._point = point
        self.calls = []

    def describe(self, img):
        self.calls.append("describe")
        return self._desc

    def locate(self, img, target):
        self.calls.append(("locate", target))
        return self._point


class _Interactor:
    def __init__(self):
        self.calls = []

    def click(self, x, y, **k):
        self.calls.append(("click", x, y))

    def type_text(self, text, **k):
        self.calls.append(("type", text))

    def scroll(self, amount, **k):
        self.calls.append(("scroll", amount))


def _engine(mode=Mode.ASSIST, app="notepad.exe", ocr_point=(100, 200), vision_point=None,
            desc="a window", read_text="hello world"):
    monitors = _monitors()
    safety = SafetyGuard(
        monitor_map=monitors, mode=mode,
        auto_whitelist=("notepad.exe", "spotify.exe"),
        auto_blacklist=("chrome.exe",),
        foreground_app_fn=lambda: app, pending_ttl_sec=120.0,
    )
    interactor = _Interactor()
    client = _Client(desc=desc, point=vision_point)
    eng = VisionEngine(
        _Cap(), monitors, client, safety, interactor,
        locate_text_fn=lambda img, target: ocr_point,
        read_text_fn=lambda img: read_text,
    )
    return eng, interactor, client


# --- perception ---------------------------------------------------------

def test_observe_returns_description():
    eng, _, client = _engine(desc="a settings window")
    assert eng.observe() == {"description": "a settings window", "monitor": "primary"}
    assert "describe" in client.calls


def test_read_returns_text():
    eng, _, _ = _engine(read_text="Γειά σου")
    assert eng.read() == {"text": "Γειά σου", "monitor": "primary"}


def test_observe_reports_unavailable_when_model_returns_none():
    # Capture succeeded but the vision model did not respond (timeout / still
    # loading). observe() must NOT hand back an empty description that the LLM
    # then fills with a guess — it must surface an explicit unavailable status.
    eng, _, _ = _engine(desc=None)
    out = eng.observe()
    assert out["monitor"] == "primary"
    assert out.get("status") == "unavailable"
    assert out.get("description") is None
    assert "message" in out          # human-readable reason for the LLM to relay


# --- locate fallback chain ---------------------------------------------

def test_locate_uses_ocr_first_and_converts_to_absolute():
    eng, _, client = _engine(ocr_point=(100, 200))
    out = eng.locate("Submit", "primary")
    assert out["found"] and out["method"] == "ocr"
    assert out["coordinates"] == [100, 200]
    assert ("locate", "Submit") not in client.calls   # VLM not consulted


def test_locate_ocr_on_secondary_adds_offset():
    eng, _, _ = _engine(ocr_point=(50, 60))
    out = eng.locate("X", "secondary")
    assert out["coordinates"] == [1970, 60]   # 1920 + 50


def test_locate_falls_back_to_vision_when_ocr_misses():
    eng, _, client = _engine(ocr_point=None, vision_point=(300, 400))
    out = eng.locate("gear icon", "primary")
    assert out["found"] and out["method"] == "vision"
    assert out["coordinates"] == [300, 400]
    assert ("locate", "gear icon") in client.calls


def test_locate_not_found_when_both_miss():
    eng, _, _ = _engine(ocr_point=None, vision_point=None)
    out = eng.locate("nothing", "primary")
    assert out == {"target": "nothing", "found": False, "monitor": "primary"}


# --- click gating -------------------------------------------------------

def test_click_assist_needs_confirmation_and_does_not_act():
    eng, interactor, _ = _engine(mode=Mode.ASSIST, ocr_point=(100, 200))
    out = eng.click("Submit")
    assert out["result"] == "needs_confirmation" and out["requires_confirmation"] is True
    assert interactor.calls == []
    assert eng.safety.has_pending() is True


def test_click_auto_whitelisted_executes():
    eng, interactor, _ = _engine(mode=Mode.AUTO, app="spotify.exe", ocr_point=(100, 200))
    out = eng.click("Next")
    assert out["result"] == "executed"
    assert interactor.calls == [("click", 100, 200)]


def test_click_auto_blacklisted_refused():
    eng, interactor, _ = _engine(mode=Mode.AUTO, app="chrome.exe", ocr_point=(100, 200))
    out = eng.click("Buy")
    assert out["result"] == "refused" and out["reason"] == "auto_blacklisted"
    assert interactor.calls == []


def test_click_target_not_found():
    eng, interactor, _ = _engine(ocr_point=None, vision_point=None)
    out = eng.click("ghost")
    assert out["result"] == "not_found"
    assert interactor.calls == []


# --- confirm flow -------------------------------------------------------

def test_confirm_executes_pending_click_after_revalidation():
    eng, interactor, _ = _engine(mode=Mode.ASSIST, ocr_point=(100, 200))
    eng.click("Submit")                 # Turn 1: proposes
    out = eng.confirm()                 # Turn 2: user assents
    assert out["result"] == "executed" and out["action"] == "click"
    assert interactor.calls == [("click", 100, 200)]


def test_confirm_with_no_pending_is_graceful():
    eng, interactor, _ = _engine()
    assert eng.confirm() == {"result": "no_pending_action"}
    assert interactor.calls == []


def test_confirm_aborts_if_target_vanished():
    eng, interactor, _ = _engine(mode=Mode.ASSIST, ocr_point=(100, 200))
    eng.click("Submit")
    # Screen changed: target no longer locatable on re-validation.
    eng._locate_text = lambda img, target: None
    eng.client._point = None
    out = eng.confirm()
    assert out["result"] == "target_vanished"
    assert interactor.calls == []


# --- type / scroll ------------------------------------------------------

def test_type_sensitive_refused():
    eng, interactor, _ = _engine(mode=Mode.ASSIST)
    out = eng.type_text("my card 4242 4242 4242 4242")
    assert out["result"] == "refused" and out["reason"] == "sensitive_input"
    assert interactor.calls == []


def test_type_confirm_executes():
    eng, interactor, _ = _engine(mode=Mode.ASSIST)
    eng.type_text("hello world")
    out = eng.confirm()
    assert out["result"] == "executed"
    assert interactor.calls == [("type", "hello world")]


def test_scroll_auto_executes_with_signed_amount():
    eng, interactor, _ = _engine(mode=Mode.AUTO, app="spotify.exe")
    out = eng.scroll("down", amount=3)
    assert out["result"] == "executed" and out["amount"] == -3
    assert interactor.calls == [("scroll", -3)]


# --- build wiring -------------------------------------------------------

def test_build_wires_timeout_and_downscale_from_config():
    from types import SimpleNamespace
    cfg = SimpleNamespace(
        ollama_base_url="http://x:11434",
        vision_model="qwen2.5vl:3b",
        vision_keep_alive="5m",
        vision_timeout_sec=20.0,
        vision_max_width=1280,
        vision_default_mode="assist",
        vision_auto_whitelist=(),
        vision_auto_blacklist=(),
        vision_pending_ttl_sec=120.0,
    )
    eng = VisionEngine.build(cfg)
    assert eng.client.timeout_sec == 20.0
    assert eng.client.max_image_dim == 1280
