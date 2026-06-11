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


class TestFusedKeepsModelResident:
    """The fused call shares the ONE warm brain with chat/reply. It must not
    re-arm an unload timer on every voice query: a `keep_alive: 30m` here
    silently scheduled the 9b for eviction after half an hour of idle, making
    the next query pay a full model reload."""

    def test_ollama_payload_keeps_model_loaded_forever(self, monkeypatch):
        from types import SimpleNamespace
        from jarvis.listening import fused_intent as fi

        captured = {}

        class _FakeResp:
            status_code = 200

            @staticmethod
            def json():
                return {"response": '{"intent":"query","confidence":"high","tools":[],"plan":["Reply to user."],"fast_path_match":null,"explanation":""}'}

        def fake_post(url, json=None, timeout=None):
            captured.update(json or {})
            return _FakeResp()

        monkeypatch.setattr(fi.requests, "post", fake_post)
        eng = fi.FusedIntentEngine(SimpleNamespace(
            ollama_base_url="http://127.0.0.1:11434",
            intent_judge_model="qwen3.5:9b-4k",
            intent_judge_timeout_sec=8.0,
        ))
        eng._ollama_call("sys", "user")
        assert captured.get("keep_alive") == -1, (
            f"fused call must keep the shared model resident (keep_alive=-1), "
            f"got {captured.get('keep_alive')!r}"
        )


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

    def test_reminder_modification_phrases_fall_through_to_the_router(self):
        """Live failure: 'cancel the oven reminder' was hijacked by the
        list-due keyword rule and answered 'No reminders are due right now'
        while the reminder stayed active. Any phrase that MODIFIES reminders
        (cancel/delete/snooze/set) must reach the fused router, which routes
        cancelReminder/createReminder correctly."""
        from jarvis.listening import fast_paths
        for q in [
            "cancel the oven reminder",
            "delete my stretching reminder",
            "snooze that reminder",
            "set a reminder to check the oven",
            "ακύρωσε τις υπενθυμίσεις για σήμερα",
        ]:
            assert fast_paths.match(q) is None, q

    def test_reminder_list_questions_still_fast_path(self):
        from jarvis.listening import fast_paths
        for q in [
            "any reminders due?",
            "what reminders do I have?",
            "show my reminders",
            "υπενθυμίσεις σήμερα",
        ]:
            m = fast_paths.match(q)
            assert m is not None, q
            assert "reminder" in (m.tool_name or ""), (q, m.tool_name)

    def test_plain_music_and_app_commands_still_fast_path(self):
        from jarvis.listening import fast_paths
        m = fast_paths.match("βάλε bohemian rhapsody")
        assert m is not None and m.tool_name == "search_and_play"
        m2 = fast_paths.match("άνοιξε το spotify")
        assert m2 is not None and m2.tool_name in ("open_app", "search_and_play")
