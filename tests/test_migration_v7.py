"""Tests for config migration v7 - forward legacy audio device names.

Phase 1 of the audio-device redesign persists the chosen input/output by
STABLE endpoint id, with the friendly name kept alongside as a fallback. The
old config keys held only a name-ish string:

  * ``tts_output_device`` (output) - an index, name substring, or None.
  * ``wispr_mic_device``  (input)  - an index, name substring, or None.

Migration v7 copies a legacy NON-EMPTY value forward into the new
``audio_output_name`` / ``audio_input_name`` keys, leaving the matching
``*_endpoint_id`` blank. The name fallback in resolve_endpoint_to_sd_index
then resolves the device on next use. It must NOT seed from the OS default
(that is Phase 2) and must leave explicit user values untouched.
"""
from __future__ import annotations

import json

import pytest

from jarvis.config import _migrate_config


@pytest.fixture()
def tmp_cfg(tmp_path):
    return tmp_path / "config.json"


def _run(tmp_cfg, cfg_dict):
    tmp_cfg.write_text(json.dumps(cfg_dict), encoding="utf-8")
    return _migrate_config(tmp_cfg, dict(cfg_dict))


def test_forwards_legacy_output_name(tmp_cfg, capsys):
    """A legacy tts_output_device string lands in audio_output_name; the
    endpoint id is left blank for the name fallback to resolve."""
    out = _run(tmp_cfg, {"_config_version": 6, "tts_output_device": "PD200X"})
    assert out["audio_output_name"] == "PD200X"
    # The migration never seeds an endpoint id; it stays absent/blank so the
    # "" default applies at load time and the name fallback resolves it.
    assert out.get("audio_output_endpoint_id", "") == ""
    assert "audio output" in capsys.readouterr().out.lower()


def test_forwards_legacy_input_name(tmp_cfg):
    """A legacy wispr_mic_device string lands in audio_input_name."""
    out = _run(
        tmp_cfg,
        {"_config_version": 6, "wispr_mic_device": "Microphone (PD200X)"},
    )
    assert out["audio_input_name"] == "Microphone (PD200X)"
    assert out.get("audio_input_endpoint_id", "") == ""


def test_forwards_integer_index_device_as_string(tmp_cfg):
    """A legacy numeric device index (stored as int) is forwarded as a string
    so the new name-based key has a usable value."""
    out = _run(tmp_cfg, {"_config_version": 6, "tts_output_device": 16})
    assert out["audio_output_name"] == "16"


def test_does_not_seed_endpoint_id_from_os_default(tmp_cfg):
    """Migration never fills *_endpoint_id - that is the Phase 2 OS-default
    seed. After v7 the ids stay blank even with legacy names present."""
    out = _run(
        tmp_cfg,
        {
            "_config_version": 6,
            "tts_output_device": "Speakers",
            "wispr_mic_device": "Mic",
        },
    )
    assert out.get("audio_output_endpoint_id", "") == ""
    assert out.get("audio_input_endpoint_id", "") == ""


def test_empty_legacy_values_are_not_forwarded(tmp_cfg):
    """None / empty legacy values do not create new name keys (nothing to
    carry), so a user who never picked a device stays unselected."""
    out = _run(
        tmp_cfg,
        {"_config_version": 6, "tts_output_device": None, "wispr_mic_device": ""},
    )
    assert "audio_output_name" not in out
    assert "audio_input_name" not in out


def test_does_not_overwrite_existing_new_keys(tmp_cfg):
    """If a new-key value is already present (e.g. a re-run or partial write),
    the legacy value does not clobber it."""
    out = _run(
        tmp_cfg,
        {
            "_config_version": 6,
            "tts_output_device": "Legacy Speakers",
            "audio_output_name": "Already Chosen",
        },
    )
    assert out["audio_output_name"] == "Already Chosen"


def test_bumps_version_to_7(tmp_cfg):
    out = _run(tmp_cfg, {"_config_version": 6})
    assert out["_config_version"] == 7


def test_does_not_re_run_when_already_v7(tmp_cfg):
    """A config already at v7 is not re-migrated, so a fresh legacy value
    written afterwards is not retro-forwarded."""
    out = _run(
        tmp_cfg,
        {"_config_version": 7, "tts_output_device": "PD200X"},
    )
    assert "audio_output_name" not in out


def test_end_to_end_legacy_config_loads_with_forwarded_name(tmp_cfg, monkeypatch):
    """A legacy on-disk config (pre-v7, name-based keys) loads through
    load_settings() with the name forwarded and the endpoint id blank - the
    full migrate + default-merge path, not just _migrate_config."""
    from jarvis.config import load_settings

    tmp_cfg.write_text(
        json.dumps(
            {
                "_config_version": 6,
                "tts_output_device": "PD200X",
                "wispr_mic_device": "Microphone (PD200X)",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(tmp_cfg))

    settings = load_settings()
    assert settings.audio_output_name == "PD200X"
    assert settings.audio_input_name == "Microphone (PD200X)"
    # No endpoint id was seeded; the "" default carries through.
    assert settings.audio_output_endpoint_id == ""
    assert settings.audio_input_endpoint_id == ""
