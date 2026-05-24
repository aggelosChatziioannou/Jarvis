"""Tests that pin the no-poison contract for `whisper_initial_prompt`.

When the config has `whisper_initial_prompt: None` (the default after the
v3 migration), the listener MUST NOT pass any `initial_prompt` kwarg to
`WhisperModel.transcribe`. Passing `None` or `""` historically led to
Whisper falling back to a memorised prompt and echoing it as transcription.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _create_mock_config(**kwargs):
    """Minimal listener config — enough for `_finalize_utterance` to reach transcribe."""
    cfg = MagicMock()
    cfg.whisper_model = kwargs.get("whisper_model", "small")
    cfg.whisper_device = kwargs.get("whisper_device", "auto")
    cfg.whisper_compute_type = kwargs.get("whisper_compute_type", "float16")
    cfg.whisper_backend = kwargs.get("whisper_backend", "faster-whisper")
    cfg.whisper_initial_prompt = kwargs.get("whisper_initial_prompt", None)
    cfg.whisper_allowed_languages = kwargs.get(
        "whisper_allowed_languages", ["el", "en"]
    )
    cfg.whisper_default_language = kwargs.get("whisper_default_language", None)
    cfg.whisper_no_speech_threshold = 0.4
    cfg.whisper_compression_ratio_threshold = 2.0
    cfg.sample_rate = 16000
    cfg.vad_enabled = False
    cfg.vad_backend = "webrtc"
    cfg.vad_aggressiveness = 2
    cfg.vad_pre_roll_ms = 400
    cfg.echo_tolerance = 0.3
    cfg.echo_energy_threshold = 2.0
    cfg.hot_window_seconds = 3.0
    cfg.voice_collect_seconds = 2.0
    cfg.voice_max_collect_seconds = 60.0
    cfg.voice_device = None
    cfg.voice_debug = False
    cfg.tune_enabled = False
    cfg.mic_agc_enabled = False
    cfg.mic_agc_target_rms = 0.1
    cfg.mic_agc_max_gain = 10.0
    cfg.whisper_min_audio_duration = 0.05
    cfg.whisper_min_confidence = 0.3
    cfg.whisper_min_word_length = 1
    cfg.voice_min_energy = 0.0045
    cfg.endpoint_silence_ms = 800
    cfg.max_utterance_ms = 12000
    cfg.tts_max_utterance_ms = 3000
    cfg.vad_frame_ms = 20
    cfg.transcript_buffer_duration_sec = 120.0
    cfg.intent_judge_model = "test"
    cfg.intent_judge_timeout_sec = 3.0
    cfg.hot_window_enabled = True
    cfg.echo_tolerance = 0.3
    cfg.echo_energy_threshold = 2.0
    cfg.tts_rate = 200
    cfg.wake_word = "jarvis"
    cfg.wake_aliases = []
    cfg.wake_fuzzy_ratio = 0.78
    cfg.stop_commands = ["stop"]
    cfg.ollama_base_url = "http://127.0.0.1:11434"
    return cfg


def _build_listener(mock_cfg, whisper_device="cuda"):
    """Create a VoiceListener with a mocked Whisper model and audio subsystem."""
    mock_whisper_model = MagicMock()
    # Have transcribe return (segments, info)
    mock_segment = MagicMock()
    mock_segment.text = "ολα καλα"
    mock_info = MagicMock()
    mock_info.language = "el"
    mock_info.language_probability = 0.95
    mock_whisper_model.transcribe.return_value = (iter([mock_segment]), mock_info)

    with patch("jarvis.listening.listener.sys") as mock_sys:
        mock_sys.platform = "linux"
        with patch("jarvis.listening.listener.FASTER_WHISPER_AVAILABLE", True), \
             patch("jarvis.listening.listener.MLX_WHISPER_AVAILABLE", False), \
             patch("jarvis.listening.listener.WhisperModel", return_value=mock_whisper_model), \
             patch("jarvis.listening.listener.sd") as mock_sd, \
             patch("jarvis.listening.listener.create_intent_judge", return_value=None):
            mock_sd.query_devices.return_value = [{"name": "M", "max_input_channels": 1}]
            mock_sd.InputStream.side_effect = Exception("stop here")

            from jarvis.listening.listener import VoiceListener
            listener = VoiceListener(MagicMock(), mock_cfg, MagicMock(), MagicMock())
            listener.model = mock_whisper_model
            listener._whisper_device = whisper_device
            listener._samplerate = 16000
            listener._utterance_frames = [np.zeros(16000, dtype=np.float32)]
            listener.echo_detector._utterance_start_time = time.time() - 1.0
            listener.is_speech_active = True
            return listener, mock_whisper_model


def test_no_prompt_kwarg_when_config_is_none():
    """The whole point of the v3 migration: a null prompt means no prompt."""
    cfg = _create_mock_config(whisper_initial_prompt=None)
    listener, mock_model = _build_listener(cfg)
    listener._finalize_utterance()

    mock_model.transcribe.assert_called_once()
    call_kwargs = mock_model.transcribe.call_args[1]
    assert "initial_prompt" not in call_kwargs, (
        "initial_prompt MUST be omitted when config is None — found "
        f"{call_kwargs.get('initial_prompt')!r} in transcribe kwargs"
    )


def test_no_prompt_kwarg_when_config_is_empty_string():
    """Empty/whitespace-only prompts are normalised to None."""
    cfg = _create_mock_config(whisper_initial_prompt="   ")
    listener, mock_model = _build_listener(cfg)
    listener._finalize_utterance()

    call_kwargs = mock_model.transcribe.call_args[1]
    assert "initial_prompt" not in call_kwargs


def test_prompt_kwarg_passed_when_explicitly_set():
    """A user who deliberately writes a (short, speech-style) prompt gets it forwarded."""
    cfg = _create_mock_config(whisper_initial_prompt="Γεια σου Jarvis.")
    listener, mock_model = _build_listener(cfg)
    listener._finalize_utterance()

    call_kwargs = mock_model.transcribe.call_args[1]
    assert call_kwargs.get("initial_prompt") == "Γεια σου Jarvis."


def test_default_language_used_as_bootstrap_when_lock_empty():
    """First-utterance: lock has no consensus → fall back to whisper_default_language."""
    cfg = _create_mock_config(whisper_default_language="el")
    listener, mock_model = _build_listener(cfg)
    listener._finalize_utterance()

    call_kwargs = mock_model.transcribe.call_args[1]
    assert call_kwargs.get("language") == "el"


def test_language_none_when_no_lock_and_no_default():
    """When both lock and default are empty, language hint is None → auto-detect."""
    cfg = _create_mock_config(whisper_default_language=None)
    listener, mock_model = _build_listener(cfg)
    listener._finalize_utterance()

    call_kwargs = mock_model.transcribe.call_args[1]
    assert call_kwargs.get("language") is None
