"""Behaviour tests for the periodic-job scheduler (no APScheduler).

Cadence is tracked via persisted job_state last-run timestamps so jobs survive
restarts and don't double-run within their interval. A failing job is non-fatal
and does NOT advance last-run (so it retries next tick).
"""
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.memory.maintenance import run_due_jobs

NOW = datetime(2026, 5, 15, tzinfo=timezone.utc)


@pytest.mark.unit
def test_job_state_round_trip(db):
    assert db.get_job_last_run("x") is None
    db.set_job_last_run("x", "2026-05-01T00:00:00+00:00")
    assert db.get_job_last_run("x") == "2026-05-01T00:00:00+00:00"
    db.set_job_last_run("x", "2026-06-01T00:00:00+00:00")  # upsert replaces
    assert db.get_job_last_run("x") == "2026-06-01T00:00:00+00:00"


@pytest.mark.unit
def test_due_job_runs_and_records_last_run(db):
    ran = []
    jobs = [("j", timedelta(days=1), lambda d, c: ran.append(1))]
    out = run_due_jobs(db, object(), jobs, now=NOW)
    assert out == ["j"]
    assert ran == [1]
    assert db.get_job_last_run("j") is not None


@pytest.mark.unit
def test_job_skipped_within_interval(db):
    db.set_job_last_run("j", (NOW - timedelta(hours=1)).isoformat())
    ran = []
    jobs = [("j", timedelta(days=1), lambda d, c: ran.append(1))]
    out = run_due_jobs(db, object(), jobs, now=NOW)
    assert out == []
    assert ran == []


@pytest.mark.unit
def test_raising_job_is_non_fatal_and_keeps_last_run_unset(db):
    def boom(d, c):
        raise RuntimeError("kaboom")

    out = run_due_jobs(db, object(), [("j", timedelta(days=1), boom)], now=NOW)
    assert out == []  # did not propagate
    assert db.get_job_last_run("j") is None  # not advanced -> retried next tick
