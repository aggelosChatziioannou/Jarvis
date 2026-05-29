"""Configuration safety net for Jarvis.

Why this exists: PC restarts + Jarvis upstream migrations have, in the past,
wiped the user's heavily customized `config.json` and left only the bare
defaults. Recovering by hand is slow and error-prone — wake aliases, MCP
registrations, API keys, voice clone path, etc. all vanish silently.

This module provides:

1. **Timestamped backups**  — every time the config is written via the
   React UI's PATCH endpoint OR every successful daemon boot, the current
   file is copied to `~/.local/share/jarvis/config_backups/`. The 10 most
   recent backups are kept; older ones are pruned automatically.

2. **Wipe detection + auto-restore** — on daemon startup, `check_and_restore()`
   inspects the live config. If it contains fewer "user" keys than the
   threshold (currently 8 non-`_`-prefixed top-level keys), it scans the
   backups (newest → oldest), finds the most recent one that DOES have
   enough keys, and copies it into place. A loud log line tells the user
   what happened.

3. **Atomic writes** — `safe_write_config()` writes via tempfile + rename
   so a crash mid-write never leaves a half-written file.

The mechanism is conservative — if everything looks normal it does nothing.
Worst case (false-positive restore) the user re-saves from the React UI
and the next backup is created.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List


BACKUP_DIR = Path.home() / ".local" / "share" / "jarvis" / "config_backups"
KEEP_BACKUPS = 10
WIPE_THRESHOLD = 8  # fewer non-underscore user keys → suspect a wipe


def _backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _user_keys(cfg: Dict[str, Any]) -> List[str]:
    """Return keys that aren't internal/metadata prefixed with `_`."""
    return [k for k in cfg.keys() if not k.startswith("_")]


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def snapshot(config_path: Path, *, reason: str = "boot") -> Optional[Path]:
    """Save a timestamped backup of the current config. Returns its path.

    Skips backup if:
      - the config file does not exist
      - the config has too few user keys (we don't want to back up a wiped
        config and bury the good backups)
    Keeps only `KEEP_BACKUPS` most recent backups; prunes older.
    """
    if not config_path.exists():
        return None

    current = _load_json_safe(config_path)
    if current is None:
        return None
    if len(_user_keys(current)) < WIPE_THRESHOLD:
        # Don't backup a wiped config — it would push out the good backups.
        return None

    bd = _backup_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = bd / f"config.{ts}.{reason}.json"

    try:
        shutil.copy2(config_path, dest)
    except Exception:
        return None

    # Prune: keep only the most recent KEEP_BACKUPS
    try:
        all_backups = sorted(
            bd.glob("config.*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in all_backups[KEEP_BACKUPS:]:
            try:
                stale.unlink()
            except Exception:
                pass
    except Exception:
        pass

    return dest


def latest_good_backup() -> Optional[Path]:
    """Return the most recent backup whose contents have ≥ WIPE_THRESHOLD user keys."""
    bd = _backup_dir()
    candidates = sorted(
        bd.glob("config.*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        data = _load_json_safe(path)
        if data is not None and len(_user_keys(data)) >= WIPE_THRESHOLD:
            return path
    return None


def check_and_restore(config_path: Path) -> Optional[Path]:
    """If the live config looks wiped, restore from the latest good backup.

    Returns the backup path that was used to restore, or None if nothing
    was done.
    """
    current = _load_json_safe(config_path)
    if current is None:
        return None
    if len(_user_keys(current)) >= WIPE_THRESHOLD:
        return None  # Config looks healthy.

    backup = latest_good_backup()
    if backup is None:
        return None  # No good backup to fall back to.

    try:
        shutil.copy2(backup, config_path)
        print(
            f"♻️ Config looked wiped ({len(_user_keys(current))} user keys) — "
            f"restored from {backup.name}",
            flush=True,
        )
        return backup
    except Exception as e:
        print(f"⚠️ Auto-restore failed: {e}", flush=True)
        return None


def safe_write_config(config_path: Path, data: Dict[str, Any]) -> bool:
    """Atomic write: tmp file + rename. Always takes a snapshot first.

    Returns True on success.
    """
    try:
        # Always snapshot the EXISTING file before overwriting (only if it
        # has enough keys — `snapshot` handles that internally).
        snapshot(config_path, reason="presave")

        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same dir (ensures rename is atomic on Windows).
        fd, tmp_path = tempfile.mkstemp(
            prefix="config.", suffix=".tmp", dir=str(config_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Atomic-ish rename. Windows requires the destination not exist;
            # we use os.replace which overwrites atomically.
            os.replace(tmp_path, str(config_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return True
    except Exception as e:
        print(f"⚠️ safe_write_config failed: {e}", flush=True)
        return False


def list_backups() -> List[Dict[str, Any]]:
    """For diagnostics / UI: list all backups newest → oldest."""
    bd = _backup_dir()
    result: List[Dict[str, Any]] = []
    for path in sorted(bd.glob("config.*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _load_json_safe(path)
        result.append({
            "name": path.name,
            "path": str(path),
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "user_keys": len(_user_keys(data)) if data else 0,
        })
    return result
