"""snoozeReminder tool: delay the soonest active reminder by a short duration."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ....debug import debug_log
from ....reminders.models import ReminderStatus
from ....reminders.store import ReminderStore
from ...base import Tool, ToolContext
from ...types import ToolExecutionResult

# number + unit, EN + EL (digits are language-agnostic; unit words cover both)
_DURATION_RE = re.compile(
    r"(\d+)\s*(hours?|hrs?|h|ώρες|ώρα|ωρες|ωρα|minutes?|mins?|m|λεπτά|λεπτό|λεπτ)",
    re.UNICODE,
)


class SnoozeReminderTool(Tool):
    @property
    def name(self) -> str:
        return "snoozeReminder"

    @property
    def description(self) -> str:
        return "Snooze a reminder for a short duration when the user says e.g. 'snooze for 5 minutes' / 'σνούζ για 5 λεπτά'."

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "How long to snooze, e.g. '5 minutes', '10 λεπτά', '1 hour'.",
                },
            },
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        text = ((args or {}).get("text") if isinstance(args, dict) else None) or context.redacted_text or ""
        minutes = _parse_minutes(text)
        if minutes is None:
            minutes = int(getattr(context.cfg, "reminder_default_snooze_min", 5))
        snooze_until = datetime.now().astimezone() + timedelta(minutes=minutes)

        store = ReminderStore(context.cfg.db_path)
        try:
            active = store.list(statuses=[ReminderStatus.PENDING, ReminderStatus.SNOOZED])
            if not active:
                return ToolExecutionResult(success=False, reply_text="You have no active reminders to snooze.")
            target = active[0]  # soonest by trigger_at
            store.snooze(target.id, snooze_until)
            debug_log(f"snoozeReminder: snoozed {target.id} for {minutes}min", "reminders")
        finally:
            store.close()

        context.user_print(f"😴 Snoozed for {minutes} minute(s).")
        return ToolExecutionResult(success=True, reply_text=f"Snoozed '{target.text}' for {minutes} minute(s).")


def _parse_minutes(text: str) -> Optional[int]:
    match = _DURATION_RE.search((text or "").lower())
    if not match:
        return None
    count = int(match.group(1))
    unit = match.group(2)
    if unit.startswith(("h", "ώ", "ω")):
        return count * 60
    return count
