"""Domain types for the reminder subsystem.

Zero I/O, zero third-party deps so they can be constructed and asserted on
freely in unit tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ReminderStatus(str, Enum):
    """Lifecycle states for a reminder.

    ``pending`` -> fires when due. One-time fires terminate as ``completed``
    (delivered) or ``missed`` (overdue beyond the grace window, silent).
    Recurring reminders return to ``pending`` with the next occurrence.
    ``snoozed`` re-fires once ``snooze_until`` passes. ``cancelled`` is inert.
    """

    PENDING = "pending"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    CANCELLED = "cancelled"
    MISSED = "missed"


@dataclass
class Reminder:
    """A persisted reminder row, with timestamps as tz-aware datetimes."""

    id: str
    text: str
    trigger_at: datetime
    recurring_rule: Optional[str]
    status: ReminderStatus
    snooze_until: Optional[datetime]
    created_at: datetime
    source: str


@dataclass
class ParsedWhen:
    """Result of parsing a natural-language time phrase.

    Exactly one of ``trigger_at`` (one-time) or ``cron`` (recurring) is set on
    success. ``ambiguous`` flags that deterministic parsing failed and the LLM
    fallback should be consulted.
    """

    trigger_at: Optional[datetime] = None
    cron: Optional[str] = None
    ambiguous: bool = False
