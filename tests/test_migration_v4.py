"""Tests for config migration v4 — ASR reliability upgrade.

Migration v4 transitions users from the v2/v3 default whisper params to the
Phase A research-backed defaults. It must:
1. Bump `whisper_compute_type` "float16" → "int8_float16" (only if at v2 default).
2. Bump `whisper_beam_size` 5 / unset → 1.
3. Bump `whisper_no_speech_threshold` 0.4 → 0.6 (only if at v3 default).
4. Tighten `whisper_compression_ratio_threshold` 2.0 → 1.35.
5. Bump `vad_silero_threshold` 0.5 → 0.7 + seed hysteresis fields.
6. Leave explicit user overrides untouched.
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


def test_bumps_compute_type_from_float16(tmp_cfg, capsys):
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_compute_type": "float16"})
    assert out["whisper_compute_type"] == "int8_float16"
    assert "Upgraded Whisper compute type" in capsys.readouterr().out


def test_preserves_explicit_compute_type(tmp_cfg):
    """A user who chose float32 (e.g. for max accuracy) keeps it."""
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_compute_type": "float32"})
    assert out["whisper_compute_type"] == "float32"


def test_sets_beam_size_when_unset(tmp_cfg, capsys):
    out = _run(tmp_cfg, {"_config_version": 3})
    assert out["whisper_beam_size"] == 1
    assert "beam_size to 1" in capsys.readouterr().out


def test_bumps_beam_size_5_to_1(tmp_cfg):
    """The historic hard-coded value 5 gets migrated to greedy."""
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_beam_size": 5})
    assert out["whisper_beam_size"] == 1


def test_preserves_explicit_beam_size_3(tmp_cfg):
    """A user who chose a custom value (3) keeps it."""
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_beam_size": 3})
    assert out["whisper_beam_size"] == 3


def test_raises_no_speech_threshold_from_v3_default(tmp_cfg, capsys):
    """v4 bumps 0.4 → 0.6, but v5 in the same ladder rolls back to 0.5.

    The final value matters more than the intermediate; we only assert that
    v4's bump fired (the log message). The actual settled value is 0.5 — see
    test_migration_v5.py.
    """
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_no_speech_threshold": 0.4})
    # v4 + v5 combined effect.
    assert out["whisper_no_speech_threshold"] == 0.5
    captured = capsys.readouterr().out
    # v4's bump log:
    assert "no_speech_threshold: 0.4 → 0.6" in captured
    # v5's rollback log:
    assert "Eased whisper_no_speech_threshold: 0.6 → 0.5" in captured


def test_preserves_explicit_no_speech_threshold(tmp_cfg):
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_no_speech_threshold": 0.35})
    assert out["whisper_no_speech_threshold"] == 0.35


def test_tightens_compression_ratio_threshold(tmp_cfg, capsys):
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_compression_ratio_threshold": 2.0})
    assert out["whisper_compression_ratio_threshold"] == 1.35
    assert "compression_ratio_threshold" in capsys.readouterr().out


def test_preserves_explicit_compression_ratio(tmp_cfg):
    out = _run(tmp_cfg, {"_config_version": 3, "whisper_compression_ratio_threshold": 2.4})
    assert out["whisper_compression_ratio_threshold"] == 2.4


def test_upgrades_vad_silero_with_hysteresis_seed(tmp_cfg, capsys):
    """v4 bumps Silero threshold 0.5 → 0.7 + seeds hysteresis fields.

    v5 (same ladder) then rolls back the threshold to 0.5 because 0.7 was
    too aggressive for dynamic mics. The hysteresis seed fields stay (they
    were always sensible defaults; only the onset value was bad).
    """
    out = _run(tmp_cfg, {"_config_version": 3, "vad_silero_threshold": 0.5})
    # v4 + v5 combined effect: starts at 0.5, v4 bumps to 0.7, v5 rolls back to 0.5.
    assert out["vad_silero_threshold"] == 0.5
    # v5 also retunes the offset to 0.3 (smaller hysteresis spread).
    assert out["vad_silero_neg_threshold"] == 0.3
    # Hysteresis seed fields stay regardless (v4 sets them, v5 doesn't touch them).
    assert out["vad_silero_min_speech_ms"] == 300
    assert out["vad_silero_min_silence_ms"] == 400
    assert out["vad_silero_speech_pad_ms"] == 400
    captured = capsys.readouterr().out
    assert "Upgraded Silero VAD" in captured  # v4 fired
    assert "Rolled back Silero VAD onset" in captured  # v5 fired


def test_preserves_explicit_vad_threshold(tmp_cfg):
    out = _run(tmp_cfg, {"_config_version": 3, "vad_silero_threshold": 0.85})
    assert out["vad_silero_threshold"] == 0.85


def test_bumps_config_version_to_4(tmp_cfg):
    """v4 runs, then v5 also runs in the same ladder. Final version is 5."""
    out = _run(tmp_cfg, {"_config_version": 3})
    assert out["_config_version"] >= 4


def test_does_not_re_run_when_already_v4(tmp_cfg, capsys):
    """Migration is idempotent: a v4 config stays put."""
    out = _run(tmp_cfg, {
        "_config_version": 4,
        "whisper_compute_type": "float16",  # would normally be bumped
    })
    # Still float16 because version says "already migrated".
    assert out["whisper_compute_type"] == "float16"
    assert "Upgraded Whisper compute type" not in capsys.readouterr().out


def test_v3_to_v4_picks_up_v3_state_for_user_who_skipped_intermediate_runs(tmp_cfg):
    """User who jumps straight from v2 to v4 still gets v3's prompt fix AND v4 changes."""
    out = _run(tmp_cfg, {
        "_config_version": 2,
        "whisper_initial_prompt": (
            "Jarvis. Greek/English voice assistant. "
            "Λέξεις: καιρός, αύριο, Θεσσαλονίκη, Αθήνα, σήμερα, "
            "παίξε, βάλε, μουσική, email."
        ),
        "whisper_compute_type": "float16",
        "mic_agc_enabled": True,
    })
    # v3 effects
    assert out["whisper_initial_prompt"] is None
    assert out["mic_agc_enabled"] is False
    # v4 effects
    assert out["whisper_compute_type"] == "int8_float16"
    assert out["whisper_beam_size"] == 1
    # v5 also ran in the same ladder, so final version is 5.
    assert out["_config_version"] >= 4
