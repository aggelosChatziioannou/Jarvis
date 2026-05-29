"""SQLite-backed reminder store.

Owns its OWN sqlite connection + lock so the daemon's firing tick never
contends on the shared memory ``Database`` lock; WAL keeps the connections
consistent when pointed at the same file. Timestamps are normalised to UTC ISO
on the way in (so lexical ordering == chronological ordering, DST-safe) and
returned as tz-aware datetimes.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from .models import Reminder, ReminderStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
  id             TEXT PRIMARY KEY,
  text           TEXT NOT NULL,
  trigger_at     TEXT NOT NULL,
  recurring_rule TEXT,
  status         TEXT NOT NULL DEFAULT 'pending',
  snooze_until   TEXT,
  created_at     TEXT NOT NULL,
  source         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due    ON reminders(status, trigger_at);
CREATE INDEX IF NOT EXISTS idx_reminders_snooze ON reminders(status, snooze_until);
"""


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialise a datetime to a UTC ISO string (naive treated as local)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _status_value(status) -> str:
    return status.value if isinstance(status, ReminderStatus) else str(status)


class ReminderStore:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── writes ──────────────────────────────────────────────────────────
    def create(
        self,
        text: str,
        trigger_at: datetime,
        recurring_rule: Optional[str] = None,
        source: str = "tool",
    ) -> str:
        rid = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute(
                "INSERT INTO reminders "
                "(id, text, trigger_at, recurring_rule, status, snooze_until, created_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    text,
                    _to_iso(trigger_at),
                    recurring_rule,
                    ReminderStatus.PENDING.value,
                    None,
                    _to_iso(created_at),
                    source,
                ),
            )
            self._conn.commit()
        return rid

    def cancel(self, rid: str) -> bool:
        return self._set_status(rid, ReminderStatus.CANCELLED)

    def mark_completed(self, rid: str) -> bool:
        return self._set_status(rid, ReminderStatus.COMPLETED)

    def mark_missed(self, rid: str) -> bool:
        return self._set_status(rid, ReminderStatus.MISSED)

    def snooze(self, rid: str, snooze_until: datetime) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE reminders SET status = ?, snooze_until = ? WHERE id = ?",
                (ReminderStatus.SNOOZED.value, _to_iso(snooze_until), rid),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def reschedule(self, rid: str, next_trigger_at: datetime) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE reminders SET status = ?, trigger_at = ?, snooze_until = NULL WHERE id = ?",
                (ReminderStatus.PENDING.value, _to_iso(next_trigger_at), rid),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ── reads ───────────────────────────────────────────────────────────
    def get(self, rid: str) -> Optional[Reminder]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (rid,)
            ).fetchone()
        return _row_to_reminder(row) if row else None

    def list(self, statuses: Optional[Iterable] = None) -> List[Reminder]:
        with self._lock:
            if statuses:
                values = [_status_value(s) for s in statuses]
                placeholders = ",".join("?" * len(values))
                rows = self._conn.execute(
                    f"SELECT * FROM reminders WHERE status IN ({placeholders}) "
                    "ORDER BY trigger_at ASC",
                    values,
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM reminders ORDER BY trigger_at ASC"
                ).fetchall()
        return [_row_to_reminder(r) for r in rows]

    def due(self, now: datetime) -> List[Reminder]:
        now_iso = _to_iso(now)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM reminders WHERE "
                "(status = 'pending' AND trigger_at <= ?) OR "
                "(status = 'snoozed' AND snooze_until <= ?) "
                "ORDER BY trigger_at ASC",
                (now_iso, now_iso),
            ).fetchall()
        return [_row_to_reminder(r) for r in rows]

    # ── internals ───────────────────────────────────────────────────────
    def _set_status(self, rid: str, status: ReminderStatus) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE reminders SET status = ? WHERE id = ?", (status.value, rid)
            )
            self._conn.commit()
            return cur.rowcount > 0


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        text=row["text"],
        trigger_at=_from_iso(row["trigger_at"]),
        recurring_rule=row["recurring_rule"],
        status=ReminderStatus(row["status"]),
        snooze_until=_from_iso(row["snooze_until"]),
        created_at=_from_iso(row["created_at"]),
        source=row["source"],
    )
