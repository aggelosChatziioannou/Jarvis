"""Behaviour tests for the console VRAM controls (vision toggle + full flush).

User decisions (2026-06-13): two Live-Logs toggles — (1) vision model off to
save VRAM, with Jarvis TELLING the user to re-enable it when a screen request
arrives; (2) full VRAM flush for gaming — wake still works but answers with an
informative canned line only; CPU features (reminders, dictation) keep working.
Flush is runtime-only (a daemon restart restores normal operation); the vision
toggle persists in config.
"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jarvis import model_admin, runtime_flags
from jarvis.listening.listener import VoiceListener

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_flags():
    runtime_flags.set_brain_paused(False)
    yield
    runtime_flags.set_brain_paused(False)


# ── runtime flags ────────────────────────────────────────────────────────────

class TestRuntimeFlags:
    def test_defaults_to_not_paused(self):
        assert runtime_flags.is_brain_paused() is False

    def test_set_and_clear(self):
        runtime_flags.set_brain_paused(True)
        assert runtime_flags.is_brain_paused() is True
        runtime_flags.set_brain_paused(False)
        assert runtime_flags.is_brain_paused() is False


# ── model admin ──────────────────────────────────────────────────────────────

class TestModelAdmin:
    def test_unload_payload_generative(self):
        assert model_admin.unload_payload("qwen3.5:9b-4k") == {
            "model": "qwen3.5:9b-4k", "prompt": "", "keep_alive": 0,
        }

    def test_unload_payload_embedding(self):
        p = model_admin.unload_payload("nomic-embed-text")
        assert p["keep_alive"] == 0 and "input" in p and "prompt" not in p

    def test_list_loaded_parses_ps(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"models": [
            {"name": "qwen3.5:9b-4k", "size_vram": 9_000_000_000},
            {"name": "nomic-embed-text", "size_vram": 600_000_000},
        ]}
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: None
        with patch.object(model_admin.requests, "get", return_value=resp):
            models = model_admin.list_loaded_models("http://x")
        assert [m["name"] for m in models] == ["qwen3.5:9b-4k", "nomic-embed-text"]
        assert models[0]["size_vram"] == 9_000_000_000

    def test_unload_model_routes_embed_to_embed_endpoint(self):
        calls = []

        def fake_post(url, json=None, timeout=None):
            calls.append(url)
            r = MagicMock(status_code=200)
            r.__enter__ = lambda s: s
            r.__exit__ = lambda s, *a: None
            r.raise_for_status = lambda: None
            return r

        with patch.object(model_admin.requests, "post", side_effect=fake_post):
            assert model_admin.unload_model("http://x", "nomic-embed-text")
            assert model_admin.unload_model("http://x", "qwen2.5vl:3b")
        assert calls[0].endswith("/api/embed")
        assert calls[1].endswith("/api/generate")


# ── listener low-VRAM gate ───────────────────────────────────────────────────

def _gated_listener():
    listener = VoiceListener.__new__(VoiceListener)
    listener.cfg = SimpleNamespace(
        lowvram_notice_text="Low-VRAM mode is active.", voice_debug=False,
    )
    listener.tts = MagicMock()
    listener.state_manager = MagicMock()
    listener._stop_thinking_tune = MagicMock()
    listener._run_intent_cascade = MagicMock()
    listener._dispatch_query = MagicMock()
    return listener


class TestLowVramGate:
    def test_paused_speaks_notice_and_never_reaches_the_cascade(self):
        runtime_flags.set_brain_paused(True)
        listener = _gated_listener()
        listener._process_transcript("hey jarvis what time is it", source="wispr")
        listener.tts.speak.assert_called_once()
        spoken = listener.tts.speak.call_args[0][0]
        assert "Low-VRAM" in spoken
        listener._run_intent_cascade.assert_not_called()
        listener._dispatch_query.assert_not_called()

    def test_paused_empty_text_is_silently_ignored(self):
        runtime_flags.set_brain_paused(True)
        listener = _gated_listener()
        listener._process_transcript("", source="whisper")
        listener.tts.speak.assert_not_called()
        listener._dispatch_query.assert_not_called()

    def test_not_paused_does_not_intercept(self):
        listener = _gated_listener()
        # Will proceed into normal processing and fail on missing attrs —
        # the gate must NOT have spoken the notice before that.
        try:
            listener._process_transcript("hello there", source="wispr")
        except Exception:
            pass
        for call in listener.tts.speak.call_args_list:
            assert "Low-VRAM" not in (call.args[0] if call.args else "")


# ── vision tools tell the user how to recover ───────────────────────────────

class TestWarmupRespectsPause:
    def test_warm_up_makes_no_http_call_while_paused(self):
        """Live race: boot warm-up threads reloaded the model right after the
        console flush unloaded it. Warm-ups must be no-ops while paused."""
        from jarvis.listening import intent_judge

        runtime_flags.set_brain_paused(True)
        with patch.object(intent_judge, "requests") as req:
            assert intent_judge.warm_up_ollama_model("http://x", "m", timeout=5.0) is False
        req.post.assert_not_called()


class TestVisionDisabledDetail:
    def test_disabled_reply_instructs_enabling_the_toggle(self):
        from jarvis.tools.builtin.vision.see_screen import SeeScreenTool

        ctx = SimpleNamespace(cfg=SimpleNamespace(vision_enabled=False),
                              user_print=lambda *_: None)
        with patch("jarvis.tools.builtin.vision._shared.load_settings",
                   return_value=SimpleNamespace(vision_enabled=False)):
            result = SeeScreenTool().run({}, ctx)
        assert result.success
        assert "vision_disabled" in result.reply_text
        # The raw data must carry the recovery instruction for the LLM to relay.
        assert "enable" in result.reply_text.lower()
        assert "console" in result.reply_text.lower()

    def test_vision_enabled_reads_fresh_settings_not_boot_snapshot(self):
        """The console toggle must take effect on the NEXT tool call without a
        daemon restart — the engine passes the BOOT config snapshot, so the
        gate has to consult live settings."""
        from jarvis.tools.builtin.vision import _shared

        boot_cfg = SimpleNamespace(vision_enabled=True)  # stale snapshot
        with patch.object(_shared, "load_settings",
                          return_value=SimpleNamespace(vision_enabled=False)):
            assert _shared.vision_enabled(boot_cfg) is False
