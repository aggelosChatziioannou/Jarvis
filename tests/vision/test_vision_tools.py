"""Behaviour tests for the 7 built-in vision tools.

A fake VisionEngine is installed via the shared singleton hook; tests assert
each tool delegates to the right engine method, returns raw JSON, and honours
the vision_enabled gate.
"""

import json
from types import SimpleNamespace

import pytest

import jarvis.tools.builtin.vision._shared as shared
from jarvis.tools.base import ToolContext
from jarvis.tools.builtin.vision import (
    ClickScreenTool,
    ConfirmScreenActionTool,
    LocateOnScreenTool,
    ReadScreenTool,
    ScrollScreenTool,
    SeeScreenTool,
    TypeOnScreenTool,
)


class _FakeEngine:
    def __init__(self):
        self.calls = []

    def observe(self, monitor="primary"):
        self.calls.append(("observe", monitor))
        return {"description": "a window", "monitor": monitor}

    def read(self, monitor="primary"):
        self.calls.append(("read", monitor))
        return {"text": "hello", "monitor": monitor}

    def locate(self, target, monitor="primary"):
        self.calls.append(("locate", target))
        return {"target": target, "found": True, "coordinates": [10, 20]}

    def click(self, target, monitor="primary"):
        self.calls.append(("click", target))
        return {"action": "click", "result": "needs_confirmation", "requires_confirmation": True}

    def type_text(self, text, monitor="primary"):
        self.calls.append(("type", text))
        return {"action": "type", "result": "needs_confirmation"}

    def scroll(self, direction, amount=3, monitor="primary"):
        self.calls.append(("scroll", direction, amount))
        return {"action": "scroll", "result": "executed", "amount": -amount}

    def confirm(self):
        self.calls.append(("confirm",))
        return {"result": "executed"}


@pytest.fixture
def engine():
    eng = _FakeEngine()
    shared.set_vision_engine(eng)
    yield eng
    shared.set_vision_engine(None)


def _ctx(enabled=True):
    cfg = SimpleNamespace(vision_enabled=enabled)
    return ToolContext(
        db=None, cfg=cfg, system_prompt="", original_prompt="",
        redacted_text="", max_retries=1, user_print=lambda *a, **k: None,
    )


def _payload(result):
    return json.loads(result.reply_text)


def test_see_screen_delegates_and_returns_raw(engine):
    out = SeeScreenTool().run({}, _ctx())
    assert out.success
    assert _payload(out)["description"] == "a window"
    assert engine.calls == [("observe", "primary")]


def test_see_screen_disabled_does_not_touch_engine(engine):
    out = SeeScreenTool().run({}, _ctx(enabled=False))
    assert _payload(out) == {"result": "vision_disabled"}
    assert engine.calls == []


def test_read_screen(engine):
    out = ReadScreenTool().run({"monitor": "secondary"}, _ctx())
    assert _payload(out)["text"] == "hello"
    assert engine.calls == [("read", "secondary")]


def test_locate_on_screen(engine):
    out = LocateOnScreenTool().run({"target": "Submit"}, _ctx())
    assert _payload(out)["coordinates"] == [10, 20]
    assert engine.calls == [("locate", "Submit")]


def test_locate_requires_target(engine):
    out = LocateOnScreenTool().run({}, _ctx())
    assert out.success is False
    assert engine.calls == []


def test_click_screen_passes_through_confirmation(engine):
    out = ClickScreenTool().run({"target": "Submit button"}, _ctx())
    assert _payload(out)["requires_confirmation"] is True
    assert engine.calls == [("click", "Submit button")]


def test_type_on_screen(engine):
    out = TypeOnScreenTool().run({"text": "hello world"}, _ctx())
    assert _payload(out)["action"] == "type"
    assert engine.calls == [("type", "hello world")]


def test_scroll_screen(engine):
    out = ScrollScreenTool().run({"direction": "down", "amount": 5}, _ctx())
    assert _payload(out)["result"] == "executed"
    assert engine.calls == [("scroll", "down", 5)]


def test_confirm_screen_action(engine):
    out = ConfirmScreenActionTool().run({}, _ctx())
    assert _payload(out)["result"] == "executed"
    assert engine.calls == [("confirm",)]


def test_tool_metadata_is_well_formed():
    for tool in (SeeScreenTool(), ReadScreenTool(), LocateOnScreenTool(),
                 ClickScreenTool(), TypeOnScreenTool(), ScrollScreenTool(),
                 ConfirmScreenActionTool()):
        assert isinstance(tool.name, str) and tool.name
        assert isinstance(tool.description, str) and len(tool.description) > 20
        assert tool.inputSchema.get("type") == "object"


def test_perception_tools_forbid_hallucination():
    """see/readScreen descriptions must compel the call and forbid inventing
    screen contents — the field fix for the 9B answering from imagination."""
    for tool in (SeeScreenTool(), ReadScreenTool()):
        desc = tool.description.lower()
        assert "must" in desc, f"{tool.name} description must compel the call"
        assert "only way" in desc, f"{tool.name} must state it is the only way to perceive the screen"
        assert ("not invent" in desc or "must not invent" in desc), \
            f"{tool.name} must forbid inventing screen contents"
