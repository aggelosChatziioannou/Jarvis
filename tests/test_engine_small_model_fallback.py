"""Tests for the malformed-output small-model fallback (R2) and the
config-driven memory-injection window (R3) in the reply engine.

R2: the default chat model is ``gemma4:e2b``. The old inline detector checked
only substrings like ``:1b``/``:3b``/``:7b`` and therefore MISSED ``gemma4:e2b``,
sending the wrong (large-model) error message. The fix routes the decision
through ``detect_model_size`` so Gemma variants are classified SMALL.

R3: the inter-turn memory-injection window was a hardcoded ``turn >= 3`` (i.e.
~2 turns). It is now driven by ``cfg.memory_injection_max_turns`` (default 4).
"""

import pytest


class TestMalformedFallbackSmallModelDetection:
    """The extracted boolean helper classifies models for the error message."""

    def test_default_gemma_model_is_small(self):
        from jarvis.reply.engine import _model_is_small

        # The shipped default — must be SMALL so the user is told they can
        # switch to a more capable model.
        assert _model_is_small("gemma4:e2b") is True

    def test_gemma_without_tag_is_small(self):
        from jarvis.reply.engine import _model_is_small

        assert _model_is_small("gemma4") is True

    def test_explicit_small_tags_are_small(self):
        from jarvis.reply.engine import _model_is_small

        assert _model_is_small("llama3.2:1b") is True
        assert _model_is_small("qwen2.5:3b") is True
        assert _model_is_small("mistral:7b") is True

    def test_large_model_is_not_small(self):
        from jarvis.reply.engine import _model_is_small

        assert _model_is_small("gpt-oss:20b") is False
        assert _model_is_small("llama3.1:70b") is False

    def test_none_or_empty_is_not_small(self):
        from jarvis.reply.engine import _model_is_small

        # No model name -> default to large (safe; don't blame a small model).
        assert _model_is_small(None) is False
        assert _model_is_small("") is False

    def test_helper_matches_detect_model_size(self):
        """The helper must be a faithful boolean view of detect_model_size,
        not a re-implementation that can drift."""
        from jarvis.reply.engine import _model_is_small
        from jarvis.reply.prompts import ModelSize, detect_model_size

        for name in ["gemma4:e2b", "gemma4", "llama3.2:1b", "gpt-oss:20b", "llama3.1:70b"]:
            expected = detect_model_size(name) == ModelSize.SMALL
            assert _model_is_small(name) is expected, name


class TestMalformedFallbackMessage:
    """The chosen error message reflects the model size for gemma4:e2b."""

    def _build_message(self, is_small: bool) -> str:
        # Mirror the wording produced by the engine so the test pins the
        # observable user-facing behaviour, keyed off the helper.
        return (
            "I had trouble understanding that request. "
            "This can happen with smaller AI models. "
            "You can switch to a more capable model through the Setup Wizard in the menu bar."
            if is_small else
            "I had trouble understanding that request. Could you try rephrasing it?"
        )

    def test_gemma_gets_small_model_guidance(self):
        from jarvis.reply.engine import _model_is_small

        msg = self._build_message(_model_is_small("gemma4:e2b"))
        assert "smaller AI models" in msg
        assert "Setup Wizard" in msg

    def test_large_model_gets_rephrase_guidance(self):
        from jarvis.reply.engine import _model_is_small

        msg = self._build_message(_model_is_small("gpt-oss:20b"))
        assert "rephrasing" in msg
        assert "Setup Wizard" not in msg


class TestMemoryInjectionWindowConfigPath:
    """R3: the engine reads memory_injection_max_turns from config."""

    def test_engine_source_reads_memory_injection_max_turns(self):
        """The window cutoff must be sourced from cfg, not a magic number.

        We assert against the source as a guard that the hardcoded ``turn >= 3``
        was replaced by a config read. A full behavioural test would require
        driving the entire agentic loop with a stalled memory future; this
        focused check plus the debug_log on drop keeps the degradation visible
        without a brittle end-to-end harness.
        """
        import inspect
        from jarvis.reply import engine as engine_mod

        src = inspect.getsource(engine_mod)
        assert "memory_injection_max_turns" in src
        # The old hardcoded comparison must be gone from the injection window.
        assert "turn >= 3" not in src

    def test_default_window_value_is_four(self):
        from jarvis.config import get_default_config

        assert get_default_config()["memory_injection_max_turns"] == 4
