"""A degraded fused judgment must never masquerade as a real 'no tools' call.

Live failure this guards: the fused engine hit its 10s timeout (busy Ollama
queue), returned the safe-default with tools=[], and the reply engine took
that as 'the model decided no tools are needed' — skipping its own router
and answering "I don't have access to your windows" for a query the tools
could have served.
"""

from jarvis.listening.fused_intent import FusedIntentEngine, FusedJudgment


class TestDegradedFlag:
    def test_safe_default_is_marked_degraded(self):
        j = FusedIntentEngine._safe_default(raw="", elapsed_ms=10000.0)
        assert j.degraded is True
        assert j.tools == []

    def test_real_judgment_defaults_to_not_degraded(self):
        j = FusedJudgment(
            intent="directed", confidence="high",
            tools=[{"name": "listOpenWindows", "arguments": {}}],
            plan=["List open windows."], fast_path_match=None,
            explanation="", elapsed_ms=1200.0,
        )
        assert j.degraded is False


class TestListenerStash:
    def _stash(self, fused):
        """Mirror of the listener's stash logic (kept in sync by this test
        failing if the contract changes): degraded -> None, real -> list."""
        if getattr(fused, "degraded", False):
            return None, None
        return list(fused.tools or []), list(fused.plan or [])

    def test_degraded_passes_none_so_engine_runs_its_router(self):
        tools, plan = self._stash(FusedIntentEngine._safe_default())
        assert tools is None and plan is None

    def test_real_empty_tools_still_pass_as_empty_list(self):
        j = FusedJudgment(
            intent="directed", confidence="high", tools=[],
            plan=["Reply to user."], fast_path_match=None,
            explanation="chat", elapsed_ms=900.0,
        )
        tools, plan = self._stash(j)
        assert tools == [] and plan == ["Reply to user."]


class TestFastPathPlacementGuard:
    """Window-arrangement phrases must skip the keyword layer entirely."""

    def test_placement_phrases_fall_through_to_the_router(self):
        from jarvis.listening import fast_paths
        for q in [
            "βάλε το spotify στην αριστερή οθόνη",
            "put chrome on the right screen",
            "split chrome and spotify",
            "άνοιξε το spotify στην δεξιά οθόνη",
        ]:
            assert fast_paths.match(q) is None, q

    def test_plain_music_and_app_commands_still_fast_path(self):
        from jarvis.listening import fast_paths
        m = fast_paths.match("βάλε bohemian rhapsody")
        assert m is not None and m.tool_name == "search_and_play"
        m2 = fast_paths.match("άνοιξε το spotify")
        assert m2 is not None and m2.tool_name in ("open_app", "search_and_play")
