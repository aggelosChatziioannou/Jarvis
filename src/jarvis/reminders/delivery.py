"""Reminder delivery: the single seam that touches output.

Speaks via core TTS, emits a tray-toast over stdout IPC (the desktop app turns
the ``__REMINDER__:`` line into a native QSystemTrayIcon toast on its GUI
thread - core never imports Qt), and publishes a HUD event via the existing
``api_server.publish_state`` channel. Mirrors the established ``__DIARY__:`` IPC
pattern in ``daemon.py``. Every step is best-effort: a failure in one channel
never blocks the others or the firing tick.

The IPC payload is JSON-encoded ASCII-safe (``ensure_ascii=True``) so a cp1252
Windows console can't crash printing non-Latin reminder text; the desktop side
decodes it back to Unicode.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from jarvis.debug import debug_log

REMINDER_IPC_PREFIX = "__REMINDER__:"


def speak_and_toast(text: str, reminder_id: str, cfg, tts, publish: Optional[Callable] = None) -> None:
    """Deliver a fired reminder: speak + tray toast + HUD event."""
    if getattr(cfg, "reminder_speak_on_fire", True) and tts is not None and getattr(tts, "enabled", False):
        try:
            tts.speak(f"Reminder: {text}")
        except Exception as exc:
            debug_log(f"reminder TTS failed (non-fatal): {type(exc).__name__}", "reminders")

    _emit_toast(reminder_id, text)
    _publish_hud(reminder_id, text, publish)


def _emit_toast(reminder_id: str, text: str) -> None:
    try:
        payload = {"type": "toast", "id": reminder_id, "title": "Reminder", "body": text}
        print(f"{REMINDER_IPC_PREFIX}{json.dumps(payload)}", flush=True)
    except Exception as exc:
        debug_log(f"reminder toast IPC failed (non-fatal): {type(exc).__name__}", "reminders")


def _publish_hud(reminder_id: str, text: str, publish: Optional[Callable]) -> None:
    if publish is None:
        publish = _default_publish
    try:
        publish(reminderFired={"id": reminder_id, "text": text})
    except Exception as exc:
        debug_log(f"reminder HUD publish failed (non-fatal): {type(exc).__name__}", "reminders")


def _default_publish(**fields) -> None:
    # Lazy import so the Flask HUD server isn't pulled in until a reminder fires.
    from jarvis import api_server

    api_server.publish_state(**fields)
