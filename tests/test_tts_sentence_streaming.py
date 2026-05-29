"""Tests for sentence-by-sentence TTS streaming in PiperTTS.

Streaming synthesises and plays the reply one sentence at a time inside a
single ``_speak_once`` call, so time-to-first-audio is the synthesis time of
the FIRST sentence rather than the whole reply. The single ``speak()`` call and
its callback contract must stay identical to callers:

  * ``playback_started_callback`` fires EXACTLY ONCE (first sentence's audio).
  * ``completion_callback`` fires EXACTLY ONCE (after the last sentence).
  * ``track_tts_start`` / echo use the FULL reply text (the listener owns that,
    so we only assert ``_last_spoken_text`` keeps the full text here).

These tests mock ``PiperVoice.synthesize`` and the per-sentence playback so no
real audio device or model is required.
"""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Config flag tests
# ---------------------------------------------------------------------------
class TestStreamingConfigFlag:
    """tts_streaming_enabled must exist end-to-end (field + default + loader)."""

    def test_settings_has_streaming_field(self):
        from src.jarvis.config import Settings
        import inspect

        params = set(inspect.signature(Settings).parameters.keys())
        assert "tts_streaming_enabled" in params

    def test_default_config_streaming_enabled_true(self):
        from src.jarvis.config import get_default_config

        defaults = get_default_config()
        assert defaults["tts_streaming_enabled"] is True

    def test_loader_defaults_to_true_when_absent(self):
        from src.jarvis.config import load_settings
        from unittest.mock import patch as _patch

        with _patch("src.jarvis.config._load_json", return_value={}):
            settings = load_settings()
            assert settings.tts_streaming_enabled is True

    def test_loader_honours_false(self):
        from src.jarvis.config import load_settings
        from unittest.mock import patch as _patch

        config_data = {"tts_streaming_enabled": False, "_config_version": 1}
        with _patch("src.jarvis.config._load_json", return_value=config_data):
            settings = load_settings()
            assert settings.tts_streaming_enabled is False


# ---------------------------------------------------------------------------
# Sentence splitter unit tests
# ---------------------------------------------------------------------------
class TestSplitIntoSentences:
    """EL/EN aware sentence splitter used to drive streaming synthesis."""

    def test_splits_basic_english_sentences(self):
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("Hello there. How are you? I am fine!")
        assert out == ["Hello there.", "How are you?", "I am fine!"]

    def test_single_sentence_returns_single_element(self):
        from src.jarvis.output.tts import _split_into_sentences
        assert _split_into_sentences("Just one sentence here") == [
            "Just one sentence here"
        ]

    def test_does_not_split_decimals(self):
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("The value is 3.5 metres long.")
        assert out == ["The value is 3.5 metres long."]

    def test_does_not_split_ellipsis(self):
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("Well... I suppose so.")
        # The ellipsis must not create an empty/extra fragment.
        assert out == ["Well... I suppose so."]

    def test_does_not_split_common_abbreviations(self):
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("Use a tool, e.g. the web search, first.")
        assert out == ["Use a tool, e.g. the web search, first."]

    def test_splits_greek_question_mark(self):
        # Greek uses ';' (U+003B) as its question mark.
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("Τι κάνεις; Είμαι καλά.")
        assert out == ["Τι κάνεις;", "Είμαι καλά."]

    def test_splits_greek_ano_teleia(self):
        # Greek ano teleia '·' (U+0387) is a sentence-level separator.
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("Καλημέρα· τι κάνεις σήμερα")
        assert out == ["Καλημέρα·", "τι κάνεις σήμερα"]

    def test_splits_on_newlines(self):
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("First line\nSecond line")
        assert out == ["First line", "Second line"]

    def test_strips_blank_fragments(self):
        from src.jarvis.output.tts import _split_into_sentences
        out = _split_into_sentences("One.  \n\n  Two.")
        assert out == ["One.", "Two."]

    def test_empty_text_returns_empty_list(self):
        from src.jarvis.output.tts import _split_into_sentences
        assert _split_into_sentences("") == []
        assert _split_into_sentences("   ") == []


# ---------------------------------------------------------------------------
# Streaming behaviour tests (Piper)
# ---------------------------------------------------------------------------
def _make_chunk(n: int = 1024):
    """A fake piper AudioChunk exposing ``audio_int16_array``."""
    chunk = MagicMock()
    chunk.audio_int16_array = np.zeros(n, dtype=np.int16)
    return chunk


@pytest.fixture
def streaming_piper():
    """A PiperTTS wired so synthesis + playback are fully mocked.

    - ``_ensure_initialized`` short-circuits to True with a fake voice.
    - ``self._voice.synthesize`` yields one chunk per call and records the
      text it was asked to synthesise (so order/count can be asserted).
    - The actual sounddevice playback is replaced by a stub that fires the
      started hook once per sentence and returns promptly.
    """
    from src.jarvis.output.tts import PiperTTS

    tts = PiperTTS(enabled=True, model_path="/fake/model.onnx")
    tts._sample_rate = 22050

    synth_calls = []

    fake_voice = MagicMock()

    def fake_synthesize(text, syn_config=None):
        synth_calls.append(text)
        yield _make_chunk()

    fake_voice.synthesize.side_effect = fake_synthesize
    tts._voice = fake_voice
    tts._initialized = True

    return tts, synth_calls


def _force_streaming(enabled: bool):
    """Patch the module's streaming-enabled reader to a fixed value."""
    return patch("src.jarvis.output.tts._get_streaming_enabled", return_value=enabled)


def _stub_playback(record_started):
    """Patch the per-sentence playback so it engages + finishes instantly.

    Returns a patch context for ``PiperTTS._play_int16_array`` (the helper that
    opens the OutputStream and blocks). The stub fires ``on_started`` (when
    given) and returns ``(played_ok=True, interrupted=False)``.
    """

    def fake_play(self, audio, play_started_hook=None):
        if play_started_hook is not None:
            record_started.append(True)
            play_started_hook()
        return (True, False)

    return patch(
        "src.jarvis.output.tts.PiperTTS._play_int16_array",
        autospec=True,
        side_effect=fake_play,
    )


class TestPiperStreamingBehaviour:
    def test_multi_sentence_synthesises_once_per_sentence_in_order(
        self, streaming_piper
    ):
        tts, synth_calls = streaming_piper
        started = []

        with _force_streaming(True), _stub_playback(started), patch.object(
            tts, "_publish_tts_state"
        ):
            tts._speak_once("First sentence. Second sentence. Third one.")

        assert synth_calls == [
            "First sentence.",
            "Second sentence.",
            "Third one.",
        ]

    def test_started_fires_once_completion_fires_once(self, streaming_piper):
        tts, _synth_calls = streaming_piper
        started_cb = MagicMock()
        completion_cb = MagicMock()
        tts._playback_started_callback = started_cb
        tts._completion_callback = completion_cb
        started = []

        with _force_streaming(True), _stub_playback(started), patch.object(
            tts, "_publish_tts_state"
        ):
            tts._speak_once("Alpha sentence. Beta sentence. Gamma sentence.")

        # The wake-listener mute hook must fire exactly once for the whole reply.
        assert started_cb.call_count == 1
        # And completion exactly once after the last sentence.
        assert completion_cb.call_count == 1

    def test_playback_ended_fires_once_on_natural_completion(self, streaming_piper):
        tts, _synth_calls = streaming_piper
        ended_cb = MagicMock()
        tts._playback_ended_callback = ended_cb
        started = []

        with _force_streaming(True), _stub_playback(started), patch.object(
            tts, "_publish_tts_state"
        ):
            tts._speak_once("One sentence here. Two sentences here.")

        assert ended_cb.call_count == 1

    def test_interrupt_after_first_sentence_skips_remaining(self, streaming_piper):
        tts, synth_calls = streaming_piper
        started_cb = MagicMock()
        completion_cb = MagicMock()
        tts._playback_started_callback = started_cb
        tts._completion_callback = completion_cb

        # Playback stub that interrupts on the FIRST sentence: fires started,
        # sets the interrupt flag, and reports it was interrupted.
        def fake_play(self_, audio, play_started_hook=None):
            if play_started_hook is not None:
                play_started_hook()
            tts._should_interrupt.set()
            return (True, True)

        with _force_streaming(True), patch(
            "src.jarvis.output.tts.PiperTTS._play_int16_array",
            autospec=True,
            side_effect=fake_play,
        ), patch.object(tts, "_publish_tts_state"):
            tts._speak_once("First sentence. Second sentence. Third sentence.")

        # Only the first sentence was synthesised; remaining were skipped.
        assert synth_calls == ["First sentence."]
        # Started still fired exactly once.
        assert started_cb.call_count == 1
        # On interrupt, completion must NOT fire (mirrors whole-text path which
        # gates completion on `not interrupted`).
        assert completion_cb.call_count == 0

    def test_full_text_preserved_for_echo(self, streaming_piper):
        tts, _synth_calls = streaming_piper
        started = []
        full = "First sentence. Second sentence."

        with _force_streaming(True), _stub_playback(started), patch.object(
            tts, "_publish_tts_state"
        ):
            tts._speak_once(full)

        # Echo detection keys off the FULL reply, never per-sentence fragments.
        assert tts.get_last_spoken_text() == full


class TestPiperWholeTextPathUnchanged:
    def test_single_sentence_synthesises_once(self, streaming_piper):
        tts, synth_calls = streaming_piper
        started = []

        with _force_streaming(True), _stub_playback(started), patch.object(
            tts, "_publish_tts_state"
        ):
            tts._speak_once("Only one sentence with no terminator")

        assert synth_calls == ["Only one sentence with no terminator"]

    def test_streaming_disabled_synthesises_once_for_whole_text(
        self, streaming_piper
    ):
        tts, synth_calls = streaming_piper
        started = []

        # Multi-sentence text, but streaming disabled → one synth call with the
        # full text (byte-for-byte whole-text path).
        with _force_streaming(False), _stub_playback(started), patch.object(
            tts, "_publish_tts_state"
        ):
            tts._speak_once("First sentence. Second sentence. Third sentence.")

        assert synth_calls == ["First sentence. Second sentence. Third sentence."]

    def test_started_and_completion_once_in_whole_text_path(self, streaming_piper):
        tts, _synth_calls = streaming_piper
        started_cb = MagicMock()
        completion_cb = MagicMock()
        tts._playback_started_callback = started_cb
        tts._completion_callback = completion_cb
        started = []

        with _force_streaming(False), _stub_playback(started), patch.object(
            tts, "_publish_tts_state"
        ):
            tts._speak_once("First sentence. Second sentence.")

        assert started_cb.call_count == 1
        assert completion_cb.call_count == 1
