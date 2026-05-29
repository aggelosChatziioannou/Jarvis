"""The reminder firing tick: runs once per daemon poll cycle.

Selects due reminders, applies the grace window, delivers (speak + tray toast)
within grace, and transitions status:
  - one-time: delivered -> completed; beyond grace -> missed (silent);
  - recurring: delivered within grace, then re-armed to the next strictly-future
    cron occurrence (occurrences missed while offline are skipped, not replayed);
    if the next fire can't be computed (croniter absent/invalid) it parks as missed.

Idempotent: every fired reminder is immediately moved out of the ``due()``
predicate, so a row never fires twice across consecutive ticks.

Fail-open: a failure on one reminder is logged and the rest still process; the
daemon also wraps the whole tick in its own try/except.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from jarvis.debug import debug_log

from .models import ReminderStatus


def fire_due_reminders(store, cfg, tts, now: datetime, deliver: Optional[Callable] = None) -> None:
    """Process all due reminders. ``deliver(reminder, cfg, tts)`` is injectable."""
    if deliver is None:
        deliver = _default_deliver
    grace = timedelta(seconds=float(getattr(cfg, "reminder_grace_window_sec", 300.0)))
    try:
        due = store.due(now)
    except Exception as exc:
        debug_log(f"reminder due() query failed (non-fatal): {type(exc).__name__}", "reminders")
        return
    if due:
        debug_log(f"reminder tick: {len(due)} due", "reminders")
    for reminder in due:
        try:
            _process(reminder, store, cfg, tts, now, grace, deliver)
        except Exception as exc:
            debug_log(
                f"reminder {reminder.id} processing failed (non-fatal): {type(exc).__name__}",
                "reminders",
            )


def _process(reminder, store, cfg, tts, now, grace, deliver) -> None:
    if reminder.status == ReminderStatus.SNOOZED and reminder.snooze_until:
        fire_time = reminder.snooze_until
    else:
        fire_time = reminder.trigger_at
    within_grace = (now - fire_time) <= grace

    if reminder.recurring_rule:
        if within_grace:
            debug_log(f"reminder {reminder.id}: firing (recurring)", "reminders")
            deliver(reminder, cfg, tts)
        else:
            debug_log(f"reminder {reminder.id}: recurring occurrence missed (beyond grace)", "reminders")
        nxt = next_cron_fire(reminder.recurring_rule, now)
        if nxt is not None:
            store.reschedule(reminder.id, nxt)
            debug_log(f"reminder {reminder.id}: rescheduled -> {nxt.isoformat()}", "reminders")
        else:
            store.mark_missed(reminder.id)
            debug_log(f"reminder {reminder.id}: cannot compute next fire, parked as missed", "reminders")
        return

    if within_grace:
        debug_log(f"reminder {reminder.id}: firing (one-time)", "reminders")
        deliver(reminder, cfg, tts)
        store.mark_completed(reminder.id)
    else:
        store.mark_missed(reminder.id)
        debug_log(f"reminder {reminder.id}: one-time missed (beyond grace)", "reminders")


def next_cron_fire(rule: str, now: datetime) -> Optional[datetime]:
    """Next strictly-future occurrence of a cron rule, or None.

    Returns None if croniter is unavailable or the rule is invalid, so callers
    can fail closed (park as missed / refuse to create) rather than crash.
    """
    try:
        from croniter import croniter
    except ImportError:
        debug_log("croniter unavailable - recurring reminder will not re-arm", "reminders")
        return None
    try:
        if not croniter.is_valid(rule):
            return None
        return croniter(rule, now).get_next(datetime)
    except Exception as exc:
        debug_log(f"croniter next-fire failed (non-fatal): {type(exc).__name__}", "reminders")
        return None


def _default_deliver(reminder, cfg, tts) -> None:
    # Lazy import keeps the firing module free of TTS/desktop concerns until a
    # reminder actually fires in production (tests inject their own deliver).
    from .delivery import speak_and_toast

    speak_and_toast(reminder.text, reminder.id, cfg, tts)
