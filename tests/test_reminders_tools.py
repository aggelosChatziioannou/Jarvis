"""Behaviour tests for the four reminder tools.

Each tool exposes a single optional ``text`` property (planner fast-path),
opens its own ReminderStore at cfg.db_path, and returns raw data. Tests use a
temp-file db so create-then-read spans tool calls, and deterministic time
phrases so the LLM fallback is never hit.
"""
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.tools.base import ToolContext
from jarvis.tools.builtin.reminders.create_reminder import CreateReminderTool
from jarvis.tools.builtin.reminders.list_reminders import ListRemindersTool
from jarvis.tools.builtin.reminders.cancel_reminder import CancelReminderTool
from jarvis.tools.builtin.reminders.snooze_reminder import SnoozeReminderTool
from jarvis.reminders.store import ReminderStore
from jarvis.reminders.models import ReminderStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def cfg(mock_config, tmp_path):
    mock_config.db_path = str(tmp_path / "reminders.db")
    return mock_config


def _ctx(cfg, redacted="", language=None):
    prints = []
    ctx = ToolContext(
        db=None,
        cfg=cfg,
        system_prompt="",
        original_prompt="",
        redacted_text=redacted,
        max_retries=0,
        user_print=lambda m: prints.append(m),
        language=language,
    )
    return ctx, prints


def _rows(cfg):
    store = ReminderStore(cfg.db_path)
    try:
        return store.list()
    finally:
        store.close()


# ── createReminder ──────────────────────────────────────────────────────
@pytest.mark.unit
def test_create_one_time_persists_pending_reminder(cfg):
    ctx, _ = _ctx(cfg)
    res = CreateReminderTool().run({"text": "in 20 minutes"}, ctx)
    assert res.success
    rows = _rows(cfg)
    assert len(rows) == 1
    assert rows[0].status == ReminderStatus.PENDING
    assert rows[0].recurring_rule is None
    assert rows[0].trigger_at > _now()


@pytest.mark.unit
def test_create_recurring_computes_first_future_fire(cfg):
    ctx, _ = _ctx(cfg)
    res = CreateReminderTool().run({"text": "every Monday at 8am"}, ctx)
    assert res.success
    rows = _rows(cfg)
    assert rows[0].recurring_rule == "0 8 * * 1"
    assert rows[0].status == ReminderStatus.PENDING
    assert rows[0].trigger_at > _now()


@pytest.mark.unit
def test_create_uses_redacted_text_when_no_arg(cfg):
    ctx, _ = _ctx(cfg, redacted="in 5 minutes")
    res = CreateReminderTool().run(None, ctx)
    assert res.success
    assert len(_rows(cfg)) == 1


@pytest.mark.unit
def test_create_retries_with_full_utterance_when_arg_lacks_a_time(cfg, monkeypatch):
    """Live failure: the fused router stripped the time phrase — args carried
    'check the oven' for 'remind me in 3 hours to check the oven' — and the
    tool failed closed even though the user's utterance had a perfectly
    parseable time. The tool must retry parsing with the full utterance."""
    def fake_parse(text, cfg_, now, language=None):
        if "3 hours" in text:
            from jarvis.reminders.models import ParsedWhen
            return ParsedWhen(trigger_at=now + timedelta(hours=3))
        return None
    monkeypatch.setattr(
        "jarvis.tools.builtin.reminders.create_reminder.parse_when", fake_parse,
    )
    ctx, _ = _ctx(cfg, redacted="remind me in 3 hours to check the oven")
    res = CreateReminderTool().run({"text": "check the oven"}, ctx)
    assert res.success
    rows = _rows(cfg)
    assert len(rows) == 1
    assert rows[0].trigger_at > _now()


@pytest.mark.unit
def test_create_fails_closed_when_time_unparseable(cfg, monkeypatch):
    monkeypatch.setattr(
        "jarvis.tools.builtin.reminders.create_reminder.parse_when",
        lambda *a, **k: None,
    )
    ctx, _ = _ctx(cfg, redacted="some text with no time")
    res = CreateReminderTool().run({"text": "blah"}, ctx)
    assert res.success is False
    assert _rows(cfg) == []


# ── listReminders ───────────────────────────────────────────────────────
@pytest.mark.unit
def test_list_returns_active_reminders(cfg):
    store = ReminderStore(cfg.db_path)
    store.create(text="drink water", trigger_at=_now() + timedelta(minutes=5))
    store.close()
    ctx, _ = _ctx(cfg)
    res = ListRemindersTool().run({}, ctx)
    assert res.success
    assert "drink water" in res.reply_text


@pytest.mark.unit
def test_list_when_empty_says_so(cfg):
    ctx, _ = _ctx(cfg)
    res = ListRemindersTool().run({}, ctx)
    assert res.success
    assert "no" in res.reply_text.lower()


# ── cancelReminder ──────────────────────────────────────────────────────
@pytest.mark.unit
def test_cancel_by_text_substring(cfg):
    store = ReminderStore(cfg.db_path)
    rid = store.create(text="call the dentist", trigger_at=_now() + timedelta(hours=1))
    store.close()
    ctx, _ = _ctx(cfg)
    res = CancelReminderTool().run({"text": "dentist"}, ctx)
    assert res.success
    store = ReminderStore(cfg.db_path)
    assert store.get(rid).status == ReminderStatus.CANCELLED
    store.close()


@pytest.mark.unit
def test_cancel_ambiguous_does_not_cancel(cfg):
    store = ReminderStore(cfg.db_path)
    store.create(text="call mum", trigger_at=_now() + timedelta(hours=1))
    store.create(text="call dad", trigger_at=_now() + timedelta(hours=2))
    store.close()
    ctx, _ = _ctx(cfg)
    res = CancelReminderTool().run({"text": "call"}, ctx)
    assert res.success is False
    assert all(r.status == ReminderStatus.PENDING for r in _rows(cfg))


# ── snoozeReminder ──────────────────────────────────────────────────────
@pytest.mark.unit
def test_snooze_sets_snoozed_with_future_snooze_until(cfg):
    store = ReminderStore(cfg.db_path)
    rid = store.create(text="standup", trigger_at=_now() + timedelta(minutes=1))
    store.close()
    ctx, _ = _ctx(cfg)
    res = SnoozeReminderTool().run({"text": "5 minutes"}, ctx)
    assert res.success
    store = ReminderStore(cfg.db_path)
    got = store.get(rid)
    store.close()
    assert got.status == ReminderStatus.SNOOZED
    assert got.snooze_until > _now()


# ── schema contract (all four) ──────────────────────────────────────────
@pytest.mark.unit
@pytest.mark.parametrize("tool", [CreateReminderTool(), ListRemindersTool(), CancelReminderTool(), SnoozeReminderTool()])
def test_single_text_property_schema_for_fast_path(tool):
    schema = tool.inputSchema
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"text"}
    assert schema["properties"]["text"]["type"] == "string"
    assert isinstance(tool.name, str) and tool.name


# ── snooze duration parsing (EN + EL, abbreviations, no-match default) ────
from jarvis.tools.builtin.reminders.snooze_reminder import _parse_minutes


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        ("5 minutes", 5),
        ("30 min", 30),
        ("2 hours", 120),
        ("1 hour", 60),
        ("3 h", 180),
        ("10 λεπτά", 10),
        ("1 ώρα", 60),
        ("soon", None),
        ("", None),
    ],
)
def test_snooze_parse_minutes(text, expected):
    assert _parse_minutes(text) == expected
