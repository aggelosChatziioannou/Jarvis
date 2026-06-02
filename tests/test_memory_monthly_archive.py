"""Behaviour tests for monthly diary consolidation + episodic archive.

The previous calendar month's diary rows are folded into the graph (reusing the
existing extraction) and recorded in episodic_archive; the raw rows are then
removed (hard-delete default) or kept (flag mode). Current month is untouched
and re-running is a no-op. The graph fold is stubbed so no LLM is needed.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import jarvis.memory.graph_ops as graph_ops
from jarvis.memory.conversation import consolidate_previous_month
from jarvis.memory.graph import GraphMemoryStore

MAY_15 = datetime(2026, 5, 15, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = GraphMemoryStore(str(tmp_path / "g.db"))
    yield s
    s.close()


def _fake_fold(**kwargs):
    return SimpleNamespace(stored=["the user likes X"], skipped=0)


def _fake_fold_tuples(**kwargs):
    # The REAL update_graph_from_dialogue returns list[tuple[fact, node_name]].
    return SimpleNamespace(
        stored=[
            ("the user lives in Thessaloniki", "User"),
            ("the user likes hiking", "User/interests"),
        ],
        skipped=0,
    )


def _fake_fold_empty(**kwargs):
    return SimpleNamespace(stored=[], skipped=0)


@pytest.mark.unit
def test_consolidate_archives_folded_fact_text_not_truncated_raw(store, db, monkeypatch):
    """The archive must hold the FOLDED FACT TEXT, not a truncated raw diary.

    Regression: folding returns list[tuple], but the code did "\\n".join(stored)
    over tuples → TypeError → caught → folded="" → the raw diary was truncated
    to 2000 chars and archived while the source was deleted = permanent loss.
    """
    monkeypatch.setattr(graph_ops, "update_graph_from_dialogue", _fake_fold_tuples)
    big = "x" * 2500  # > 2000 so the old truncation fallback would be visible
    db.upsert_conversation_summary("2026-04-03", big)

    month = consolidate_previous_month(db, store, "http://x", "m", now=MAY_15)
    assert month == "2026-04"
    arch = db.conn.execute(
        "SELECT * FROM episodic_archive WHERE month_year='2026-04'"
    ).fetchone()
    summary = arch["consolidated_summary"]
    assert "the user lives in Thessaloniki" in summary
    assert "the user likes hiking" in summary
    assert "xxxx" not in summary  # not the raw diary blob


@pytest.mark.unit
def test_consolidate_fallback_preserves_full_narrative(store, db, monkeypatch):
    """If folding yields nothing, archive the FULL narrative (no 2000-char cut)
    before deleting the raw rows, so no detail is ever silently lost."""
    monkeypatch.setattr(graph_ops, "update_graph_from_dialogue", _fake_fold_empty)
    big = "A" * 3000
    db.upsert_conversation_summary("2026-04-03", big)

    consolidate_previous_month(db, store, "http://x", "m", now=MAY_15)
    arch = db.conn.execute(
        "SELECT * FROM episodic_archive WHERE month_year='2026-04'"
    ).fetchone()
    assert len(arch["consolidated_summary"]) >= 3000


@pytest.mark.unit
def test_consolidate_archives_prev_month_and_removes_raw(store, db, monkeypatch):
    monkeypatch.setattr(graph_ops, "update_graph_from_dialogue", _fake_fold)
    db.upsert_conversation_summary("2026-04-03", "April chat")
    db.upsert_conversation_summary("2026-04-20", "More April")
    db.upsert_conversation_summary("2026-05-10", "May chat")

    month = consolidate_previous_month(db, store, "http://x", "m", now=MAY_15)

    assert month == "2026-04"
    arch = db.conn.execute(
        "SELECT * FROM episodic_archive WHERE month_year = '2026-04'"
    ).fetchone()
    assert arch is not None
    assert arch["original_count"] == 2
    n_apr = db.conn.execute(
        "SELECT COUNT(*) c FROM conversation_summaries WHERE substr(date_utc,1,7)='2026-04'"
    ).fetchone()["c"]
    n_may = db.conn.execute(
        "SELECT COUNT(*) c FROM conversation_summaries WHERE substr(date_utc,1,7)='2026-05'"
    ).fetchone()["c"]
    assert n_apr == 0  # prev-month raw rows removed
    assert n_may == 1  # current month untouched


@pytest.mark.unit
def test_consolidate_no_prev_rows_returns_none(store, db, monkeypatch):
    monkeypatch.setattr(graph_ops, "update_graph_from_dialogue", _fake_fold)
    db.upsert_conversation_summary("2026-05-10", "May chat")
    assert consolidate_previous_month(db, store, "http://x", "m", now=MAY_15) is None


@pytest.mark.unit
def test_consolidate_is_idempotent(store, db, monkeypatch):
    monkeypatch.setattr(graph_ops, "update_graph_from_dialogue", _fake_fold)
    db.upsert_conversation_summary("2026-04-03", "April chat")

    assert consolidate_previous_month(db, store, "http://x", "m", now=MAY_15) == "2026-04"
    # second run: April rows already archived+removed -> no-op, no duplicate archive
    assert consolidate_previous_month(db, store, "http://x", "m", now=MAY_15) is None
    cnt = db.conn.execute(
        "SELECT COUNT(*) c FROM episodic_archive WHERE month_year='2026-04'"
    ).fetchone()["c"]
    assert cnt == 1


@pytest.mark.unit
def test_flag_mode_keeps_raw_rows(store, db, monkeypatch):
    monkeypatch.setattr(graph_ops, "update_graph_from_dialogue", _fake_fold)
    db.upsert_conversation_summary("2026-04-03", "April chat")

    month = consolidate_previous_month(db, store, "http://x", "m", now=MAY_15, delete_raw=False)
    assert month == "2026-04"
    n_apr = db.conn.execute(
        "SELECT COUNT(*) c FROM conversation_summaries WHERE substr(date_utc,1,7)='2026-04'"
    ).fetchone()["c"]
    assert n_apr == 1  # kept in flag mode
    assert db.conn.execute("SELECT COUNT(*) c FROM episodic_archive").fetchone()["c"] == 1
