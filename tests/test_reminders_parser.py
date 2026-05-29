"""Behaviour tests for natural-language time parsing (parse_when).

Asserts the routing contract:
- deterministic paths (relative/absolute via dateparser, recurrence via the
  cron builder) do NOT consult the LLM;
- genuinely ambiguous phrases fall back to the LLM;
- the parser fails *closed* (returns None) rather than inventing a time.

Grounded in the observed dateparser behaviour: EL/EN relative + EN absolute
parse deterministically; EL absolute / long-tail phrasings need the fallback.
"""
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.reminders import parser as parser_mod
from jarvis.reminders.parser import parse_when

BASE = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)  # a Friday


@pytest.fixture(autouse=True)
def _forbid_real_llm(monkeypatch):
    """By default any LLM call is a failure; fallback tests opt back in."""

    def _boom(*args, **kwargs):
        raise AssertionError("LLM fallback should not have been called here")

    monkeypatch.setattr(parser_mod, "call_llm_direct", _boom)


@pytest.mark.unit
def test_english_relative_uses_dateparser_no_llm(mock_config):
    pw = parse_when("in 20 minutes", mock_config, BASE, language="en")
    assert pw is not None and pw.cron is None
    assert abs((pw.trigger_at - (BASE + timedelta(minutes=20))).total_seconds()) < 1


@pytest.mark.unit
def test_greek_relative_uses_dateparser_no_llm(mock_config):
    pw = parse_when("σε 20 λεπτά", mock_config, BASE, language="el")
    assert pw is not None and pw.cron is None
    assert abs((pw.trigger_at - (BASE + timedelta(minutes=20))).total_seconds()) < 1


@pytest.mark.unit
def test_english_absolute_tomorrow_is_future(mock_config):
    pw = parse_when("tomorrow at 3pm", mock_config, BASE, language="en")
    assert pw is not None and pw.trigger_at is not None
    assert pw.trigger_at > BASE


@pytest.mark.unit
def test_english_recurrence_to_cron_no_llm(mock_config):
    pw = parse_when("every Monday at 8am", mock_config, BASE, language="en")
    assert pw is not None
    assert pw.cron == "0 8 * * 1"
    assert pw.trigger_at is None


@pytest.mark.unit
def test_greek_recurrence_to_cron_no_llm(mock_config):
    pw = parse_when("κάθε Δευτέρα στις 8", mock_config, BASE, language="el")
    assert pw is not None
    assert pw.cron == "0 8 * * 1"


@pytest.mark.unit
def test_daily_recurrence_to_cron(mock_config):
    pw = parse_when("every day at 9", mock_config, BASE, language="en")
    assert pw is not None
    assert pw.cron == "0 9 * * *"


@pytest.mark.unit
def test_greek_daily_recurrence_to_cron(mock_config):
    pw = parse_when("κάθε μέρα στις 9", mock_config, BASE, language="el")
    assert pw is not None
    assert pw.cron == "0 9 * * *"


@pytest.mark.unit
def test_ambiguous_phrase_falls_back_to_llm_iso(mock_config, monkeypatch):
    monkeypatch.setattr(parser_mod, "call_llm_direct", lambda *a, **k: "2026-05-30T09:30:00")
    pw = parse_when("αύριο στις 3", mock_config, BASE, language="el")
    assert pw is not None and pw.trigger_at is not None
    assert pw.trigger_at.year == 2026 and pw.trigger_at.month == 5 and pw.trigger_at.day == 30


@pytest.mark.unit
def test_llm_fallback_can_return_cron(mock_config, monkeypatch):
    monkeypatch.setattr(parser_mod, "call_llm_direct", lambda *a, **k: "0 7 * * *")
    pw = parse_when("nudge me each morning early", mock_config, BASE, language="en")
    assert pw is not None and pw.cron == "0 7 * * *"


@pytest.mark.unit
def test_llm_fallback_none_returns_none(mock_config, monkeypatch):
    monkeypatch.setattr(parser_mod, "call_llm_direct", lambda *a, **k: "NONE")
    pw = parse_when("hello there how are you", mock_config, BASE, language="en")
    assert pw is None


@pytest.mark.unit
def test_empty_text_returns_none(mock_config):
    assert parse_when("", mock_config, BASE, language="en") is None
    assert parse_when("   ", mock_config, BASE, language="en") is None
