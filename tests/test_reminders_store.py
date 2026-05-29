"""Behaviour tests for the reminder store.

Covers CRUD round-trips, the due-selection query (the heart of the firing
loop), and the status transitions the firing state machine relies on. These
assert observable outcomes, not internal SQL.
"""
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.reminders.store import ReminderStore
from jarvis.reminders.models import ReminderStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def store():
    s = ReminderStore(":memory:")
    yield s
    s.close()


@pytest.mark.unit
def test_create_then_get_round_trips_all_fields(store):
    when = _now() + timedelta(minutes=20)
    rid = store.create(text="drink water", trigger_at=when, source="voice")

    got = store.get(rid)
    assert got is not None
    assert got.id == rid
    assert got.text == "drink water"
    assert got.source == "voice"
    assert got.status == ReminderStatus.PENDING
    assert got.recurring_rule is None
    # instant preserved to the second regardless of tz representation
    assert abs((got.trigger_at - when).total_seconds()) < 1


@pytest.mark.unit
def test_due_selects_overdue_pending_excludes_future_and_terminal(store):
    now = _now()
    past = store.create(text="past", trigger_at=now - timedelta(minutes=1))
    future = store.create(text="future", trigger_at=now + timedelta(minutes=10))
    cancelled = store.create(text="cancelled", trigger_at=now - timedelta(minutes=5))
    store.cancel(cancelled)

    due_ids = {r.id for r in store.due(now)}
    assert past in due_ids
    assert future not in due_ids
    assert cancelled not in due_ids


@pytest.mark.unit
def test_due_selects_snoozed_whose_snooze_has_elapsed(store):
    now = _now()
    elapsed = store.create(text="snooze me", trigger_at=now - timedelta(minutes=30))
    store.snooze(elapsed, now - timedelta(seconds=1))

    still_snoozed = store.create(text="later", trigger_at=now - timedelta(minutes=30))
    store.snooze(still_snoozed, now + timedelta(minutes=5))

    due_ids = {r.id for r in store.due(now)}
    assert elapsed in due_ids
    assert still_snoozed not in due_ids


@pytest.mark.unit
def test_mark_completed_and_missed_transitions(store):
    now = _now()
    a = store.create(text="a", trigger_at=now)
    store.mark_completed(a)
    assert store.get(a).status == ReminderStatus.COMPLETED

    b = store.create(text="b", trigger_at=now)
    store.mark_missed(b)
    assert store.get(b).status == ReminderStatus.MISSED


@pytest.mark.unit
def test_reschedule_sets_future_trigger_and_returns_to_pending(store):
    now = _now()
    rid = store.create(
        text="stretch", trigger_at=now - timedelta(minutes=1), recurring_rule="0 8 * * 1"
    )
    nxt = now + timedelta(days=3)
    store.reschedule(rid, nxt)

    got = store.get(rid)
    assert got.status == ReminderStatus.PENDING
    assert got.snooze_until is None
    assert abs((got.trigger_at - nxt).total_seconds()) < 1


@pytest.mark.unit
def test_list_filters_by_status(store):
    now = _now()
    store.create(text="a", trigger_at=now)
    b = store.create(text="b", trigger_at=now)
    store.cancel(b)

    pending_texts = {r.text for r in store.list(statuses=[ReminderStatus.PENDING])}
    assert "a" in pending_texts
    assert "b" not in pending_texts
