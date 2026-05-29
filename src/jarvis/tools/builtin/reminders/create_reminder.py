"""createReminder tool: schedule a spoken + tray reminder from natural language."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from ....debug import debug_log
from ....reminders.firing import next_cron_fire
from ....reminders.parser import parse_when
from ....reminders.store import ReminderStore
from ...base import Tool, ToolContext
from ...types import ToolExecutionResult


class CreateReminderTool(Tool):
    """Create a one-time or recurring reminder. Parsing fails *closed*: if no
    time can be resolved, nothing is stored and the tool reports failure."""

    @property
    def name(self) -> str:
        return "createReminder"

    @property
    def description(self) -> str:
        return (
            "Set a reminder when the user asks to be reminded of something at a time or on a "
            "schedule (e.g. 'remind me in 20 minutes to call mum', 'remind me every Monday at "
            "8am to stretch', 'θύμισέ μου σε 10 λεπτά να πιω νερό')."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The full natural-language reminder including when it should fire (e.g. 'call mum in 20 minutes', 'κάθε Δευτέρα στις 8 to stretch').",
                },
            },
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        context.user_print("⏰ Setting your reminder…")

        text_arg = (args or {}).get("text") if isinstance(args, dict) else None
        text = (text_arg if isinstance(text_arg, str) else "").strip() or (context.redacted_text or "").strip()
        if not text:
            context.user_print("⚠️ I didn't catch what to remind you about.")
            return ToolExecutionResult(success=False, reply_text="No reminder text provided")

        now = datetime.now().astimezone()
        parsed = parse_when(text, context.cfg, now, language=context.language)
        if parsed is None:
            context.user_print("⚠️ I couldn't work out when to remind you.")
            return ToolExecutionResult(success=False, reply_text="Could not parse a time from the reminder")

        if parsed.cron:
            first_fire = next_cron_fire(parsed.cron, now)
            if first_fire is None:
                context.user_print("⚠️ I couldn't schedule that recurring reminder.")
                return ToolExecutionResult(success=False, reply_text="Could not compute the recurrence")
            trigger_at = first_fire
            recurring_rule = parsed.cron
        else:
            trigger_at = parsed.trigger_at
            recurring_rule = None

        source = "stdin" if getattr(context.cfg, "use_stdin", False) else "voice"
        store = ReminderStore(context.cfg.db_path)
        try:
            rid = store.create(
                text=text, trigger_at=trigger_at, recurring_rule=recurring_rule, source=source
            )
        finally:
            store.close()

        when_local = trigger_at.astimezone().strftime("%a %d %b %H:%M")
        suffix = " (recurring)" if recurring_rule else ""
        debug_log(
            f"createReminder: stored {rid} for {trigger_at.isoformat()} recurring={bool(recurring_rule)}",
            "reminders",
        )
        context.user_print(f"⏰ Reminder set for {when_local}{suffix}.")
        return ToolExecutionResult(success=True, reply_text=f"Reminder set for {when_local}{suffix}.")
