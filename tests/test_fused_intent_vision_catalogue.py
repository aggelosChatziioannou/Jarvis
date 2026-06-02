"""Deterministic drift-pin: the fused-intent engine must advertise the vision
tools (real registry names) and carry the screen-awareness routing rule.

Behavioural routing (the small model actually picking seeScreen) is covered by
the live eval in evals/test_fused_vision_routing.py. This test is the fast guard
that the catalogue/prompt don't silently lose the vision tools again.
"""

from types import SimpleNamespace

from jarvis.listening.fused_intent import FusedIntentEngine, build_tool_catalogue

VISION_TOOLS = [
    "seeScreen", "readScreen", "locateOnScreen",
    "clickScreen", "typeOnScreen", "scrollScreen", "confirmScreenAction",
]


def _engine():
    cfg = SimpleNamespace(
        ollama_base_url="http://localhost:11434",
        intent_judge_model="qwen3.5:4b-4k",
        intent_judge_timeout_sec=8.0,
    )
    return FusedIntentEngine(cfg)


def test_catalogue_lists_every_vision_tool():
    catalogue_names = {name for name, _desc in build_tool_catalogue()}
    for name in VISION_TOOLS:
        assert name in catalogue_names, f"fused catalogue missing vision tool {name!r}"


def test_system_prompt_advertises_vision_tools_and_screen_rule():
    prompt = _engine()._system_prompt
    # The tools must be visible to the model...
    for name in ("seeScreen", "readScreen", "clickScreen"):
        assert name in prompt, f"system prompt missing {name!r}"
    # ...and the screen-awareness rule must bias screen queries to them.
    lowered = prompt.lower()
    assert "screen" in lowered
    assert "what do you see" in lowered  # the bare-query disambiguation hint
