"""cancelReminder tool: cancel an active reminder by id or text match."""
from __future__ import annotations

from typing import Any, Dict, Optional

from ....debug import debug_log
from ....reminders.models import ReminderStatus
from ....reminders.store import ReminderStore
from ...base import Tool, ToolContext
from ...types import ToolExecutionResult


class CancelReminderTool(Tool):
    @property
    def name(self) -> str:
        return "cancelReminder"

    @property
    def description(self) -> str:
        return "Cancel an active reminder when the user asks to cancel, remove, or delete a reminder."

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Which reminder to cancel: its id, or words matching its text (e.g. 'dentist').",
                },
            },
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        query = ((args or {}).get("text") if isinstance(args, dict) else None) or context.redacted_text or ""
        query = query.strip()

        store = ReminderStore(context.cfg.db_path)
        try:
            active = store.list(statuses=[ReminderStatus.PENDING, ReminderStatus.SNOOZED])
            if not active:
                return ToolExecutionResult(success=False, reply_text="You have no active reminders to cancel.")

            target = None
            for reminder in active:
                if query and (query == reminder.id or query == reminder.id[:8]):
                    target = reminder
                    break
            if target is None and query:
                matches = [r for r in active if query.lower() in r.text.lower()]
                if len(matches) == 1:
                    target = matches[0]
                elif len(matches) > 1:
                    listing = "; ".join(r.text for r in matches)
                    context.user_print("🤔 More than one reminder matches.")
                    return ToolExecutionResult(
                        success=False,
                        reply_text=f"Multiple reminders match '{query}': {listing}. Please be more specific.",
                    )

            if target is None:
                return ToolExecutionResult(success=False, reply_text=f"No active reminder matches '{query}'.")

            store.cancel(target.id)
            debug_log(f"cancelReminder: cancelled {target.id}", "reminders")
        finally:
            store.close()

        context.user_print("🗑️ Reminder cancelled.")
        return ToolExecutionResult(success=True, reply_text=f"Cancelled reminder: {target.text}")
