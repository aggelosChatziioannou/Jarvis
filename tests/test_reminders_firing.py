"""Behaviour tests for the reminder firing state machine.

Delivery is injected so we assert *which* reminders fire and the resulting
status transitions, without touching TTS or the desktop IPC.
"""
from datetime import datetime, timedelta, timezone

import pytest

import jarvis.reminders.firing as firing_mod
from jarvis.reminders.firing import fire_due_reminders
from jarvis.reminders.models import ReminderStatus
from jarvis.reminders.store import ReminderStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Cfg:
    reminder_grace_window_sec = 300.0


@pytest.fixture
def store():
    s = ReminderStore(":memory:")
    yield s
    s.close()


@pytest.fixture
def fired():
    delivered = []

    def deliver(reminder, cfg, tts):
        delivered.append(reminder.id)

    return delivered, deliver


@pytest.mark.unit
def test_one_time_within_grace_delivers_and_completes(store, fired):
    delivered, deliver = fired
    now = _now()
    rid = store.create(text="x", trigger_at=now - timedelta(seconds=10))

    fire_due_reminders(store, Cfg(), None, now, deliver=deliver)

    assert rid in delivered
    assert store.get(rid).status == ReminderStatus.COMPLETED


@pytest.mark.unit
def test_one_time_beyond_grace_is_missed_and_silent(store, fired):
    delivered, deliver = fired
    now = _now()
    rid = store.create(text="x", trigger_at=now - timedelta(seconds=600))

    fire_due_reminders(store, Cfg(), None, now, deliver=deliver)

    assert rid not in delivered
    assert store.get(rid).status == ReminderStatus.MISSED


@pytest.mark.unit
def test_recurring_within_grace_delivers_and_reschedules_to_future(store, fired):
    delivered, deliver = fired
    now = _now()
    rid = store.create(
        text="stretch", trigger_at=now - timedelta(seconds=5), recurring_rule="* * * * *"
    )

    fire_due_reminders(store, Cfg(), None, now, deliver=deliver)

    assert rid in delivered
    got = store.get(rid)
    assert got.status == ReminderStatus.PENDING
    assert got.trigger_at > now


@pytest.mark.unit
def test_recurring_beyond_grace_is_silent_but_advances(store, fired):
    delivered, deliver = fired
    now = _now()
    rid = store.create(
        text="stretch", trigger_at=now - timedelta(seconds=600), recurring_rule="* * * * *"
    )

    fire_due_reminders(store, Cfg(), None, now, deliver=deliver)

    assert rid not in delivered
    got = store.get(rid)
    assert got.status == ReminderStatus.PENDING
    assert got.trigger_at > now


@pytest.mark.unit
def test_snoozed_elapsed_refires(store, fired):
    delivered, deliver = fired
    now = _now()
    rid = store.create(text="x", trigger_at=now - timedelta(minutes=30))
    store.snooze(rid, now - timedelta(seconds=5))

    fire_due_reminders(store, Cfg(), None, now, deliver=deliver)

    assert rid in delivered
    assert store.get(rid).status == ReminderStatus.COMPLETED


@pytest.mark.unit
def test_no_duplicate_fire_across_two_ticks(store, fired):
    delivered, deliver = fired
    now = _now()
    rid = store.create(text="x", trigger_at=now - timedelta(seconds=10))

    fire_due_reminders(store, Cfg(), None, now, deliver=deliver)
    fire_due_reminders(store, Cfg(), None, now + timedelta(seconds=2), deliver=deliver)

    assert delivered.count(rid) == 1


@pytest.mark.unit
def test_recurring_parks_as_missed_when_next_fire_unavailable(store, fired, monkeypatch):
    delivered, deliver = fired
    monkeypatch.setattr(firing_mod, "next_cron_fire", lambda rule, now: None)
    now = _now()
    rid = store.create(
        text="x", trigger_at=now - timedelta(seconds=5), recurring_rule="0 8 * * 1"
    )

    fire_due_reminders(store, Cfg(), None, now, deliver=deliver)

    assert store.get(rid).status == ReminderStatus.MISSED


@pytest.mark.unit
def test_one_bad_reminder_does_not_block_the_rest(store, fired, monkeypatch):
    delivered, deliver = fired
    now = _now()
    good = store.create(text="good", trigger_at=now - timedelta(seconds=5))
    # a delivery that throws for one id must not stop the others
    calls = {"n": 0}

    def flaky(reminder, cfg, tts):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        delivered.append(reminder.id)

    other = store.create(text="other", trigger_at=now - timedelta(seconds=4))
    fire_due_reminders(store, Cfg(), None, now, deliver=flaky)

    # the second reminder still fired despite the first raising
    assert other in delivered
