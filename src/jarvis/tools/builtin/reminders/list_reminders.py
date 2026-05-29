"""listReminders tool: return the user's active reminders as raw text."""
from __future__ import annotations

from typing import Any, Dict, Optional

from ....reminders.models import ReminderStatus
from ....reminders.store import ReminderStore
from ...base import Tool, ToolContext
from ...types import ToolExecutionResult


class ListRemindersTool(Tool):
    @property
    def name(self) -> str:
        return "listReminders"

    @property
    def description(self) -> str:
        return "List the user's active (pending or snoozed) reminders when they ask what reminders they have set."

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Optional free-text filter hint (currently advisory; all active reminders are returned).",
                },
            },
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        context.user_print("📋 Fetching your reminders…")
        store = ReminderStore(context.cfg.db_path)
        try:
            rows = store.list(statuses=[ReminderStatus.PENDING, ReminderStatus.SNOOZED])
        finally:
            store.close()

        if not rows:
            return ToolExecutionResult(success=True, reply_text="No active reminders.")

        lines = []
        for reminder in rows:
            when = (reminder.snooze_until or reminder.trigger_at).astimezone().strftime("%a %d %b %H:%M")
            tag = "recurring" if reminder.recurring_rule else reminder.status.value
            lines.append(f"#{reminder.id[:8]} — {reminder.text} @ {when} [{tag}]")
        return ToolExecutionResult(success=True, reply_text="\n".join(lines))
