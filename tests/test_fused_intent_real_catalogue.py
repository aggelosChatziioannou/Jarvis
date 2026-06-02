"""Drift-pin + regression for the fused-intent tool catalogue.

The fused engine advertises a tool catalogue to the small model and then uses
the names the model returns as the reply engine's allow-list. If those names
don't match real registry tool names, ``generate_tools_json_schema`` silently
drops them (``BUILTIN_TOOLS.get(name)`` -> ``None`` -> ``continue``) and
weather / web / meals / reminders get no tool at all on the live fused path.

These tests lock the catalogue to REAL registry names so this class of bug
can never silently ship again.
"""

from types import SimpleNamespace

from jarvis.listening.fused_intent import FusedIntentEngine


def _engine():
    cfg = SimpleNamespace(
        ollama_base_url="http://localhost:11434",
        intent_judge_model="qwen3.5:4b-4k",
        intent_judge_timeout_sec=8.0,
    )
    return FusedIntentEngine(cfg)


def test_system_prompt_uses_real_names_not_fake_dotted_names():
    """The advertised tool names must be the real registry names."""
    prompt = _engine()._system_prompt
    # Real registry names must be advertised so the model routes to tools that exist.
    assert "getWeather" in prompt, "system prompt should advertise the real getWeather tool"
    assert "webSearch" in prompt, "system prompt should advertise the real webSearch tool"
    # The old fake dotted names must be gone — they resolve to no real tool and
    # are silently dropped from the schema, breaking weather/web/music/email.
    for fake in ("weather.current", "web.search", "spotify.play", "time.now", "gmail.send"):
        assert fake not in prompt, f"system prompt still advertises fake tool {fake!r}"


def test_every_catalogue_name_resolves_to_a_real_tool():
    """Drift-pin: every advertised name must resolve in BUILTIN_TOOLS or MCP."""
    from jarvis.listening.fused_intent import build_tool_catalogue
    from jarvis.tools.registry import BUILTIN_TOOLS, get_cached_mcp_tools

    real = set(BUILTIN_TOOLS) | set(get_cached_mcp_tools())
    names = [name for name, _desc in build_tool_catalogue()]
    assert names, "fused tool catalogue is empty"
    for name in names:
        assert name in real, f"fused catalogue advertises non-existent tool {name!r}"


def test_catalogue_advertises_core_builtins_by_real_name():
    """Core user-facing tools must be present under their real names."""
    from jarvis.listening.fused_intent import build_tool_catalogue

    names = {name for name, _desc in build_tool_catalogue()}
    for expected in ("getWeather", "webSearch", "logMeal", "createReminder"):
        assert expected in names, f"fused catalogue missing real tool {expected!r}"


def test_catalogue_excludes_engine_managed_tools():
    """``stop`` and ``toolSearchTool`` are injected by the engine itself, not routed."""
    from jarvis.listening.fused_intent import build_tool_catalogue

    names = {name for name, _desc in build_tool_catalogue()}
    assert "stop" not in names
    assert "toolSearchTool" not in names
