"""Tests for the config migration v3 that undoes the prompt-poisoning regression.

Migration v3 must:
1. Wipe the poisoned v2 default prompt back to `null` (so the loader's None default applies).
2. Disable `mic_agc_enabled` for users still on the v2 auto-applied default.
3. Leave a user-written custom prompt or explicit AGC `true` alone.
"""
from __future__ import annotations

import json

import pytest

from jarvis.config import _migrate_config


POISONED_PROMPT = (
    "Jarvis. Greek/English voice assistant. "
    "Λέξεις: καιρός, αύριο, Θεσσαλονίκη, Αθήνα, σήμερα, "
    "παίξε, βάλε, μουσική, email."
)


@pytest.fixture()
def tmp_cfg(tmp_path):
    return tmp_path / "config.json"


def _run_migration(tmp_cfg, cfg_dict):
    """Write a config dict to disk, run the migration, and return the result."""
    tmp_cfg.write_text(json.dumps(cfg_dict), encoding="utf-8")
    return _migrate_config(tmp_cfg, dict(cfg_dict))


def test_wipes_poisoned_prompt(tmp_cfg, capsys):
    cfg_in = {
        "_config_version": 2,
        "whisper_initial_prompt": POISONED_PROMPT,
    }
    out = _run_migration(tmp_cfg, cfg_in)
    assert out["whisper_initial_prompt"] is None
    # Migration v4 also runs at the end (idempotent ladder) and bumps version.
    assert out["_config_version"] >= 3
    assert "Reverted whisper_initial_prompt" in capsys.readouterr().out


def test_wipes_poisoned_prompt_close_variant(tmp_cfg):
    cfg_in = {
        "_config_version": 2,
        "whisper_initial_prompt": "Jarvis. Greek/English voice assistant.",
    }
    out = _run_migration(tmp_cfg, cfg_in)
    assert out["whisper_initial_prompt"] is None


def test_preserves_user_custom_prompt(tmp_cfg):
    """A user who wrote their own prompt (anything not in the poisoned set) is untouched."""
    cfg_in = {
        "_config_version": 2,
        "whisper_initial_prompt": "Γεια σου Jarvis.",
    }
    out = _run_migration(tmp_cfg, cfg_in)
    assert out["whisper_initial_prompt"] == "Γεια σου Jarvis."


def test_disables_agc_default_true(tmp_cfg, capsys):
    """mic_agc_enabled=True (auto-applied default) gets flipped off, marker is set."""
    cfg_in = {
        "_config_version": 2,
        "mic_agc_enabled": True,
    }
    out = _run_migration(tmp_cfg, cfg_in)
    assert out["mic_agc_enabled"] is False
    assert out["_agc_v2_default"] is True
    assert "Disabled mic AGC" in capsys.readouterr().out


def test_preserves_explicit_agc_true_after_marker(tmp_cfg):
    """A user who explicitly re-opted-in to AGC after migration v3 keeps it on."""
    cfg_in = {
        "_config_version": 3,
        "mic_agc_enabled": True,
        "_agc_v2_default": True,  # already-migrated state
    }
    # Migration v3 should be a no-op now
    out = _run_migration(tmp_cfg, cfg_in)
    assert out["mic_agc_enabled"] is True


def test_does_not_run_twice(tmp_cfg, capsys):
    """Once _config_version >= 3, the migration doesn't re-fire."""
    cfg_in = {
        "_config_version": 3,
        "whisper_initial_prompt": POISONED_PROMPT,  # would normally be wiped
    }
    out = _run_migration(tmp_cfg, cfg_in)
    # Still poisoned because version says "already migrated past 3"
    assert out["whisper_initial_prompt"] == POISONED_PROMPT
    # No print fired
    assert "Reverted whisper_initial_prompt" not in capsys.readouterr().out


def test_bumps_version_even_without_changes(tmp_cfg):
    """An untouched config (no poisoned prompt, AGC already off) still gets the v3 marker.

    Migration v4 runs after v3 in the same ladder, so the final version may
    be >= 3 — we just need to confirm v3 ran (the AGC marker is the signal).
    """
    cfg_in = {
        "_config_version": 2,
        "whisper_initial_prompt": "Γεια σου Jarvis.",
        "mic_agc_enabled": False,
    }
    out = _run_migration(tmp_cfg, cfg_in)
    assert out["_config_version"] >= 3
    # marker still added because migration block sets it unconditionally for AGC tracking
    assert out["_agc_v2_default"] is True
