"""Tests for migration v5 — rollback of Phase A values that overshot.

v4 set Silero VAD threshold to 0.7 and no_speech_threshold to 0.6 based on
recommendations from research literature. In production on a PD200X dynamic
mic with Greek speech, those values rejected most of every utterance (only
0.3-0.5 s of audio reached Whisper for 1.5-3 s spoken utterances).

v5 walks both back: VAD onset 0.7 → 0.5, no_speech 0.6 → 0.5, and seeds
the offset hysteresis at 0.3 for the new onset. Explicit user choices are
preserved.
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


def test_rolls_back_silero_threshold_07(tmp_cfg, capsys):
    """Users still on v4's 0.7 default get rolled back to 0.5."""
    out = _run(tmp_cfg, {"_config_version": 4, "vad_silero_threshold": 0.7})
    assert out["vad_silero_threshold"] == 0.5
    assert out["vad_silero_neg_threshold"] == 0.3
    captured = capsys.readouterr().out
    assert "Rolled back Silero VAD onset" in captured


def test_preserves_explicit_silero_threshold_05(tmp_cfg):
    """User who already had 0.5 stays at 0.5 — no harm, no extra log noise."""
    out = _run(tmp_cfg, {"_config_version": 4, "vad_silero_threshold": 0.5})
    assert out["vad_silero_threshold"] == 0.5


def test_preserves_explicit_silero_threshold_08(tmp_cfg):
    """User who explicitly chose 0.8 (e.g. for a very noisy office) keeps it."""
    out = _run(tmp_cfg, {"_config_version": 4, "vad_silero_threshold": 0.8})
    assert out["vad_silero_threshold"] == 0.8


def test_rolls_back_no_speech_threshold_06(tmp_cfg, capsys):
    out = _run(tmp_cfg, {"_config_version": 4, "whisper_no_speech_threshold": 0.6})
    assert out["whisper_no_speech_threshold"] == 0.5
    assert "Eased whisper_no_speech_threshold" in capsys.readouterr().out


def test_preserves_explicit_no_speech_threshold(tmp_cfg):
    out = _run(tmp_cfg, {"_config_version": 4, "whisper_no_speech_threshold": 0.7})
    assert out["whisper_no_speech_threshold"] == 0.7


def test_bumps_version_to_5(tmp_cfg):
    out = _run(tmp_cfg, {"_config_version": 4})
    assert out["_config_version"] == 5


def test_does_not_re_run_when_already_v5(tmp_cfg, capsys):
    out = _run(tmp_cfg, {"_config_version": 5, "vad_silero_threshold": 0.7})
    # Still 0.7 because version says "already migrated".
    assert out["vad_silero_threshold"] == 0.7
    assert "Rolled back Silero VAD" not in capsys.readouterr().out
