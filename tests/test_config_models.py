"""
Tests for model configuration in config.py.

Tests the centralized model definitions that serve as the single source of truth
for supported chat models across the application.
"""

import pytest
from jarvis.config import (
    SUPPORTED_CHAT_MODELS,
    DEFAULT_CHAT_MODEL,
    get_supported_model_ids,
    get_default_config,
)


class TestSupportedChatModels:
    """Tests for SUPPORTED_CHAT_MODELS constant."""

    def test_supported_models_is_dict(self):
        """SUPPORTED_CHAT_MODELS should be a dict."""
        assert isinstance(SUPPORTED_CHAT_MODELS, dict)

    def test_supported_models_not_empty(self):
        """SUPPORTED_CHAT_MODELS should have at least one model."""
        assert len(SUPPORTED_CHAT_MODELS) > 0

    def test_supported_models_have_required_fields(self):
        """Each model should have name, description, size, and ram fields."""
        required_fields = {"name", "description", "size", "vram"}
        for model_id, info in SUPPORTED_CHAT_MODELS.items():
            assert isinstance(info, dict), f"{model_id} info should be a dict"
            for field in required_fields:
                assert field in info, f"{model_id} missing required field: {field}"
                assert isinstance(info[field], str), f"{model_id}.{field} should be a string"

    def test_model_ids_are_valid_format(self):
        """Model IDs should be in valid Ollama format (name:tag or just name)."""
        for model_id in SUPPORTED_CHAT_MODELS:
            assert isinstance(model_id, str)
            assert len(model_id) > 0
            # Should not have spaces
            assert " " not in model_id


class TestDefaultChatModel:
    """Tests for DEFAULT_CHAT_MODEL constant."""

    def test_default_model_is_string(self):
        """DEFAULT_CHAT_MODEL should be a string."""
        assert isinstance(DEFAULT_CHAT_MODEL, str)

    def test_default_model_in_supported_models(self):
        """DEFAULT_CHAT_MODEL must be in SUPPORTED_CHAT_MODELS."""
        assert DEFAULT_CHAT_MODEL in SUPPORTED_CHAT_MODELS

    def test_default_model_not_empty(self):
        """DEFAULT_CHAT_MODEL should not be empty."""
        assert len(DEFAULT_CHAT_MODEL) > 0


class TestGetSupportedModelIds:
    """Tests for get_supported_model_ids() function."""

    def test_returns_set(self):
        """get_supported_model_ids() should return a set."""
        result = get_supported_model_ids()
        assert isinstance(result, set)

    def test_returns_model_ids(self):
        """get_supported_model_ids() should return the model IDs from SUPPORTED_CHAT_MODELS."""
        result = get_supported_model_ids()
        expected = set(SUPPORTED_CHAT_MODELS.keys())
        assert result == expected

    def test_contains_default_model(self):
        """get_supported_model_ids() should include DEFAULT_CHAT_MODEL."""
        result = get_supported_model_ids()
        assert DEFAULT_CHAT_MODEL in result


class TestDefaultConfigUsesModelConstant:
    """Tests to ensure default config uses the model constants."""

    def test_default_config_uses_default_chat_model(self):
        """get_default_config() should use DEFAULT_CHAT_MODEL for ollama_chat_model."""
        config = get_default_config()
        assert config["ollama_chat_model"] == DEFAULT_CHAT_MODEL

    def test_default_config_model_is_supported(self):
        """The default model in config should be a supported model."""
        config = get_default_config()
        model = config["ollama_chat_model"]
        assert model in SUPPORTED_CHAT_MODELS


class TestWhisperHallucinationFilterDefaults:
    """Pin defaults for the Whisper hallucination-filter thresholds.

    Both the faster-whisper `_filter_noisy_segments` path and the MLX
    `_finalize_utterance` path read these via `getattr(cfg, ..., fallback)`;
    the defaults must stay in sync with the `Settings` dataclass field and
    the values documented in README and `listening.spec.md`.
    """

    def test_no_speech_threshold_default(self):
        config = get_default_config()
        assert "whisper_no_speech_threshold" in config
        # 0.5 — middle ground. 0.6 (Calm-Whisper recommendation) was too
        # aggressive in production: it filtered borderline-quiet Greek
        # phonemes captured by a dynamic mic (rolled back in migration v5).
        # The Calm-Whisper exact-match blocklist catches anything 0.5 leaks.
        assert config["whisper_no_speech_threshold"] == 0.5
        assert 0.0 <= config["whisper_no_speech_threshold"] <= 1.0

    def test_min_confidence_default(self):
        config = get_default_config()
        assert "whisper_min_confidence" in config
        assert config["whisper_min_confidence"] == 0.3
        assert 0.0 <= config["whisper_min_confidence"] <= 1.0

    def test_settings_dataclass_round_trips_no_speech_threshold(self, tmp_path, monkeypatch):
        """A config file with an overridden threshold must parse through
        `load_settings` into the `Settings.whisper_no_speech_threshold` field.
        """
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"whisper_no_speech_threshold": 0.72}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        settings = load_settings()
        assert settings.whisper_no_speech_threshold == pytest.approx(0.72)


class TestChatGenerationBoundsConfig:
    """Defaults for the bounded/tuned main-chat generation keys (R1)."""

    def test_llm_chat_max_tokens_default(self):
        config = get_default_config()
        assert "llm_chat_max_tokens" in config
        assert config["llm_chat_max_tokens"] == 512

    def test_llm_chat_temperature_default(self):
        config = get_default_config()
        assert "llm_chat_temperature" in config
        # -1.0 is the "unset / use model default" sentinel.
        assert config["llm_chat_temperature"] == -1.0

    def test_llm_chat_max_tokens_round_trips(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"llm_chat_max_tokens": 256}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        settings = load_settings()
        assert settings.llm_chat_max_tokens == 256

    def test_llm_chat_temperature_round_trips(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"llm_chat_temperature": 0.7}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        settings = load_settings()
        assert settings.llm_chat_temperature == pytest.approx(0.7)


class TestMemoryInjectionWindowConfig:
    """Default for the memory-injection window (R3)."""

    def test_memory_injection_max_turns_default(self):
        config = get_default_config()
        assert "memory_injection_max_turns" in config
        assert config["memory_injection_max_turns"] == 4

    def test_memory_injection_max_turns_round_trips(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"memory_injection_max_turns": 6}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        settings = load_settings()
        assert settings.memory_injection_max_turns == 6


class TestAudioDeviceSelectionConfig:
    """Defaults + round-trip for the endpoint-id audio selection keys.

    Phase 1 of the audio-device redesign: the user's chosen input/output are
    persisted by STABLE endpoint id (preferred) with the friendly name kept
    alongside as a display label + resolution fallback. All four default to
    the empty string ("not selected"); the OS-default seed happens later
    (Phase 2), never here.
    """

    _KEYS = (
        "audio_output_endpoint_id",
        "audio_output_name",
        "audio_input_endpoint_id",
        "audio_input_name",
    )

    def test_defaults_present_and_empty(self):
        config = get_default_config()
        for key in self._KEYS:
            assert key in config, f"missing default for {key}"
            assert config[key] == "", f"{key} should default to empty string"

    def test_keys_round_trip_through_settings(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(
            _json.dumps(
                {
                    "audio_output_endpoint_id": "{0.0.0.00000000}.{spk}",
                    "audio_output_name": "Headset (Realtek(R) Audio)",
                    "audio_input_endpoint_id": "{0.0.1.00000000}.{mic}",
                    "audio_input_name": "Microphone (PD200X)",
                }
            )
        )
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        settings = load_settings()
        assert settings.audio_output_endpoint_id == "{0.0.0.00000000}.{spk}"
        assert settings.audio_output_name == "Headset (Realtek(R) Audio)"
        assert settings.audio_input_endpoint_id == "{0.0.1.00000000}.{mic}"
        assert settings.audio_input_name == "Microphone (PD200X)"

    def test_unset_keys_resolve_to_empty_string(self, tmp_path, monkeypatch):
        """A config with none of the keys set yields empty strings, never None,
        so downstream resolution can treat '' uniformly as 'not selected'."""
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"tts_enabled": True}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        settings = load_settings()
        for key in self._KEYS:
            assert getattr(settings, key) == ""


class TestWakeGainConfig:
    """wispr_wake_gain: software gain on the wake-detection audio only.

    Defaults to 1.0 (no change) so existing setups are unaffected; a higher
    value amplifies a weak/distant 'Hey Jarvis' into openWakeWord's range.
    """

    def test_default_is_unity(self):
        config = get_default_config()
        assert config.get("wispr_wake_gain") == 1.0

    def test_round_trips_through_settings(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"wispr_wake_gain": 3.5}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        assert load_settings().wispr_wake_gain == 3.5

    def test_invalid_value_falls_back_to_unity(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"wispr_wake_gain": "loud"}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        assert load_settings().wispr_wake_gain == 1.0


class TestWakeRmsFloorConfig:
    """wispr_wake_rms_floor: ungained int16 RMS below which a wake frame is
    treated as silence and the TRIGGER is skipped (the model is still fed).

    Defaults to 0.0 (off): the recall-tuned far-field model rejects silence on
    its own, and a non-zero floor must stay below far-field RMS (~100-200 for
    the PD200X at 2-3 m) or it drops distant wakes. Must be config-tunable so a
    user can opt back into a guard without a code change.
    """

    def test_default_is_off(self):
        config = get_default_config()
        assert config.get("wispr_wake_rms_floor") == 0.0

    def test_round_trips_through_settings(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"wispr_wake_rms_floor": 50.0}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        assert load_settings().wispr_wake_rms_floor == 50.0

    def test_invalid_value_falls_back_to_off(self, tmp_path, monkeypatch):
        import json as _json
        from jarvis.config import load_settings

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({"wispr_wake_rms_floor": "loud"}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

        assert load_settings().wispr_wake_rms_floor == 0.0


class TestModelConsistency:
    """Tests for overall model configuration consistency."""

    def test_all_models_have_consistent_info_structure(self):
        """All models should have the same info structure."""
        if len(SUPPORTED_CHAT_MODELS) < 2:
            pytest.skip("Need at least 2 models to test consistency")

        first_model = next(iter(SUPPORTED_CHAT_MODELS.values()))
        first_keys = set(first_model.keys())

        for model_id, info in SUPPORTED_CHAT_MODELS.items():
            assert set(info.keys()) == first_keys, f"{model_id} has different fields"

    def test_model_names_are_descriptive(self):
        """Model names should be descriptive (not just the ID)."""
        for model_id, info in SUPPORTED_CHAT_MODELS.items():
            name = info["name"]
            # Name should be longer than the ID (more descriptive)
            assert len(name) > len(model_id), f"{model_id} name should be descriptive"

    def test_vram_requirements_are_specified(self):
        """VRAM requirements should follow expected format (e.g., '8GB+')."""
        for model_id, info in SUPPORTED_CHAT_MODELS.items():
            vram = info["vram"]
            assert "GB" in vram, f"{model_id} VRAM should specify GB"

    def test_non_default_models_require_more_vram_than_default(self):
        """Non-default models need more VRAM because the intent judge (gemma4:e2b) runs alongside them.

        The default model (gemma4:e2b) shares the intent judge, so its VRAM is the baseline.
        Other models must load both themselves AND the intent judge, so their VRAM must be higher.
        """
        import re

        def _extract_vram_gb(vram_str: str) -> int:
            match = re.search(r"(\d+)", vram_str)
            assert match, f"Could not parse VRAM value from: {vram_str}"
            return int(match.group(1))

        default_vram = _extract_vram_gb(SUPPORTED_CHAT_MODELS[DEFAULT_CHAT_MODEL]["vram"])

        for model_id, info in SUPPORTED_CHAT_MODELS.items():
            if model_id == DEFAULT_CHAT_MODEL:
                continue
            model_vram = _extract_vram_gb(info["vram"])
            assert model_vram > default_vram, (
                f"{model_id} VRAM ({info['vram']}) should be higher than default model VRAM "
                f"({SUPPORTED_CHAT_MODELS[DEFAULT_CHAT_MODEL]['vram']}) because the intent judge "
                f"(gemma4:e2b) always runs alongside the chat model"
            )
