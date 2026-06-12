"""Plan shape invariants the direct-exec loop depends on.

Two live failures:
1. "I was unable to fully finish your request because my execution loop ran
   out of turns early on. However, I successfully opened Spotify…" — the
   fused-plan translator appended EVERY fused prose step after the tool
   steps; `tool_steps_of` (all-but-last) then counted the intermediate prose
   as unexecuted *tool steps*, and the synthesis model — staring at a plan it
   could never finish — narrated confusion instead of confirming.
2. "ψάξε στο internet τα τελευταία νέα" never searched: the legacy planner
   emitted a SINGLE-step plan (`webSearch query='…'`) and the direct-exec
   force gate requires len(plan) > 1, so nothing forced the call and the
   chat model answered without searching.
"""

from jarvis.reply.engine import _translate_fused_to_planner_shape, ensure_synthesis_step
from jarvis.reply.planner import tool_steps_of


class TestTranslatorShape:
    def test_tool_steps_plus_single_synthesis_only(self):
        plan = _translate_fused_to_planner_shape(
            [{"name": "apps__open_app", "arguments": {"name": "spotify"}},
             {"name": "manageWindow", "arguments": {"action": "move", "position": "right-half"}}],
            ["Open Spotify.", "Move it to the right half.",
             "Confirm the window position.", "Tell the user it's done."],
        )
        # 2 tool steps + exactly ONE synthesis step — no phantom prose steps.
        assert len(plan) == 3
        assert plan[0].startswith("apps__open_app")
        assert plan[1].startswith("manageWindow")
        assert plan[2] == "Tell the user it's done."
        assert tool_steps_of(plan) == plan[:2]

    def test_no_tools_passthrough_unchanged(self):
        plan = _translate_fused_to_planner_shape([], ["Reply to user."])
        assert plan == ["Reply to user."]

    def test_empty_fused_plan_gets_generic_synthesis(self):
        plan = _translate_fused_to_planner_shape(
            [{"name": "getWeather", "arguments": {}}], [],
        )
        assert plan == ["getWeather", "Reply to the user."]


class TestEnsureSynthesisStep:
    def _schema(self):
        return [{"type": "function", "function": {
            "name": "webSearch", "description": "Search.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        }}]

    def test_single_tool_headed_step_gains_synthesis(self):
        plan = ensure_synthesis_step(["webSearch query='latest gold news'"], self._schema())
        assert plan == ["webSearch query='latest gold news'", "Reply to the user."]
        assert tool_steps_of(plan) == ["webSearch query='latest gold news'"]

    def test_tool_headed_last_step_gains_synthesis(self):
        plan = ensure_synthesis_step(
            ["listOpenWindows", "webSearch query='x'"], self._schema())
        assert plan[-1] == "Reply to the user."
        assert len(plan) == 3

    def test_prose_last_step_untouched(self):
        plan = ensure_synthesis_step(
            ["webSearch query='x'", "Reply to the user."], self._schema())
        assert plan == ["webSearch query='x'", "Reply to the user."]

    def test_empty_plan_untouched(self):
        assert ensure_synthesis_step([], self._schema()) == []
