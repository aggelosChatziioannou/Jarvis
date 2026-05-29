"""Shared helpers for the vision tools.

Holds the process-wide singleton VisionEngine so the pending-action buffer
survives across turns (Turn 1 ``clickScreen`` proposes -> Turn 2
``confirmScreenAction`` executes). Settings (mode / whitelist) are re-synced
from config on each access so the settings UI takes effect without losing a
pending action.
"""

from __future__ import annotations

import json
from typing import Optional

from ....debug import debug_log

_ENGINE = None  # singleton VisionEngine


def set_vision_engine(engine) -> None:
    """Override the singleton (used by tests)."""
    global _ENGINE
    _ENGINE = engine


def _sync_config(engine, cfg) -> None:
    from ....vision.safety import Mode

    try:
        engine.safety.mode = Mode(str(getattr(cfg, "vision_default_mode", "assist")).lower())
        engine.safety.auto_whitelist = {a.lower() for a in (getattr(cfg, "vision_auto_whitelist", ()) or ())}
        engine.safety.auto_blacklist = {a.lower() for a in (getattr(cfg, "vision_auto_blacklist", ()) or ())}
    except Exception as exc:  # pragma: no cover - defensive
        debug_log(f"vision tools: config sync failed — {exc}", "vision")


def get_vision_engine(cfg):
    global _ENGINE
    if _ENGINE is None:
        from ....vision.vision_engine import VisionEngine

        _ENGINE = VisionEngine.build(cfg)
        debug_log("vision tools: engine built", "vision")
    else:
        _sync_config(_ENGINE, cfg)
    return _ENGINE


def vision_enabled(cfg) -> bool:
    return bool(getattr(cfg, "vision_enabled", False))


def raw(result: dict) -> str:
    """Compact JSON for a tool's raw-data reply_text."""
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
