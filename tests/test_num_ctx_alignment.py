"""Behaviour: every LLM call riding the shared brain requests the SAME num_ctx.

Ollama fully reloads a model's runner whenever a request's num_ctx differs
from the loaded one — measured at ~8.5s per transition on qwen3.5:9b-4k
(both growing AND shrinking). The live voice path alternated fused(4096) →
chat(8192) → fused(4096), paying up to two reloads per query; the reminder
parser's 1024 blew its own 8s timeout on the reload alone ("I couldn't work
out when to remind you" for a perfectly parseable phrase). One shared,
config-driven context size (`llm_num_ctx`, default 4096 — matching the
deliberately-built -4k model) eliminates the thrash.
"""

from types import SimpleNamespace
from unittest.mock import patch

import jarvis.llm as llm_mod
from jarvis.llm import call_llm_direct, chat_with_messages, shared_num_ctx


class _Resp:
    status_code = 200

    @staticmethod
    def json():
        return {"message": {"content": "OK"}, "response": "OK"}

    @staticmethod
    def raise_for_status():
        return None


def _capture_post(captured):
    def fake_post(url, json=None, timeout=None, stream=False):
        captured.append(json or {})
        return _Resp()
    return fake_post


class TestSharedNumCtx:
    def test_default_is_4096(self):
        with patch.object(llm_mod, "load_settings", side_effect=Exception("no cfg")):
            assert shared_num_ctx() == 4096

    def test_reads_llm_num_ctx_from_settings(self):
        with patch.object(llm_mod, "load_settings",
                          return_value=SimpleNamespace(llm_num_ctx=2048)):
            assert shared_num_ctx() == 2048


class TestAllCallSitesAligned:
    def test_chat_and_direct_calls_request_the_same_num_ctx(self):
        captured = []
        with patch.object(llm_mod, "load_settings",
                          return_value=SimpleNamespace(llm_num_ctx=4096)), \
             patch.object(llm_mod.requests, "post", _capture_post(captured)):
            chat_with_messages("http://127.0.0.1:11434", "m", [{"role": "user", "content": "x"}])
            call_llm_direct("http://127.0.0.1:11434", "m", "sys", "x")
        ctxs = {p["options"]["num_ctx"] for p in captured}
        assert ctxs == {4096}, f"mismatched num_ctx across call sites: {ctxs}"

    def test_fused_engine_uses_the_shared_num_ctx(self):
        from jarvis.listening import fused_intent as fi
        captured = []

        class _FusedResp:
            status_code = 200

            @staticmethod
            def json():
                return {"response": '{"intent":"query","confidence":"high","tools":[],"plan":["Reply to user."],"fast_path_match":null,"explanation":""}'}

        def fake_post(url, json=None, timeout=None):
            captured.append(json or {})
            return _FusedResp()

        with patch.object(fi.requests, "post", fake_post):
            eng = fi.FusedIntentEngine(SimpleNamespace(
                ollama_base_url="http://127.0.0.1:11434",
                intent_judge_model="m",
                intent_judge_timeout_sec=8.0,
            ))
            eng._ollama_call("sys", "user")
        assert captured[0]["options"]["num_ctx"] == shared_num_ctx()

    def test_reminder_parser_does_not_override_num_ctx(self):
        """The parser's old num_ctx=1024 forced a runner reload on every
        reminder parse. It must ride the shared context size now."""
        from jarvis.reminders import parser as P
        seen = {}

        def fake_direct(*args, **kwargs):
            seen.update(kwargs)
            return "NONE"

        from datetime import datetime
        with patch.object(P, "call_llm_direct", side_effect=fake_direct):
            P._llm_fallback("ping", SimpleNamespace(
                tool_router_model="m", ollama_base_url="http://127.0.0.1:11434",
            ), datetime.now().astimezone())
        assert seen.get("num_ctx") in (None, shared_num_ctx())
