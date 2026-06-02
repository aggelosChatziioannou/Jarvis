"""HTTP bridge for the console Memory page: graph CRUD + reminders CRUD.

Handlers are called directly (matching the repo's api_server test style) with
the underlying stores pointed at a tmp SQLite file via monkeypatch.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.jarvis import api_server
from src.jarvis.memory.graph import GraphMemoryStore
from src.jarvis.reminders.store import ReminderStore


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    db = str(tmp_path / "graph.db")
    monkeypatch.setattr(api_server, "_resolve_graph_store", lambda: GraphMemoryStore(db))
    return db


@pytest.fixture
def rem_db(tmp_path, monkeypatch):
    db = str(tmp_path / "rem.db")
    monkeypatch.setattr(api_server, "_resolve_reminder_store", lambda: ReminderStore(db))
    return db


# ── Graph ────────────────────────────────────────────────────────────────

def test_graph_node_create_read_update_delete(graph_db):
    created = api_server.graph_create_node(
        api_server.GraphNodeCreate(name="Coffee", description="taste", data="black, no sugar")
    )
    nid = created["id"]
    assert created["name"] == "Coffee"

    got = api_server.graph_get_node(nid)
    assert got["node"]["id"] == nid
    assert got["node"]["data"] == "black, no sugar"
    assert "children" in got and "ancestors" in got

    updated = api_server.graph_update_node(nid, api_server.GraphNodeUpdate(data="oat milk latte"))
    assert updated["data"] == "oat milk latte"

    res = api_server.graph_delete_node(nid)
    assert res == {"ok": True, "id": nid}


def test_graph_delete_protects_structural_nodes(graph_db):
    with pytest.raises(api_server.HTTPException) as ei:
        api_server.graph_delete_node("root")
    assert ei.value.status_code == 400


def test_graph_get_missing_node_is_404(graph_db):
    with pytest.raises(api_server.HTTPException) as ei:
        api_server.graph_get_node("does-not-exist")
    assert ei.value.status_code == 404


def test_graph_nodes_serves_the_real_three_branch_taxonomy(graph_db):
    out = api_server.graph_nodes()
    ids = {n["id"] for n in out["nodes"]}
    assert "root" in ids
    assert {"user", "directives", "world"} <= ids
    # edges connect root to its branches
    assert any(e["source"] == "root" for e in out["edges"])


def test_graph_create_with_missing_parent_is_400(graph_db):
    with pytest.raises(api_server.HTTPException) as ei:
        api_server.graph_create_node(
            api_server.GraphNodeCreate(name="x", parent_id="nope")
        )
    assert ei.value.status_code == 400


# ── Reminders ────────────────────────────────────────────────────────────

def _iso_in(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_reminder_create_list_complete_delete(rem_db):
    created = api_server.reminders_create(
        api_server.ReminderCreate(text="Call mum", trigger_at=_iso_in(2))
    )
    rid = created["id"]
    assert created["text"] == "Call mum"
    assert created["status"] == "pending"

    listed = api_server.reminders_list()
    assert any(r["id"] == rid for r in listed)

    done = api_server.reminders_update(rid, api_server.ReminderUpdate(status="completed"))
    assert done["status"] == "completed"

    res = api_server.reminders_delete(rid)
    assert res == {"ok": True, "id": rid}


def test_reminder_snooze_requires_until(rem_db):
    created = api_server.reminders_create(
        api_server.ReminderCreate(text="Standup", trigger_at=_iso_in(1))
    )
    with pytest.raises(api_server.HTTPException) as ei:
        api_server.reminders_update(created["id"], api_server.ReminderUpdate(status="snoozed"))
    assert ei.value.status_code == 400


def test_reminder_create_rejects_bad_datetime(rem_db):
    with pytest.raises(api_server.HTTPException) as ei:
        api_server.reminders_create(api_server.ReminderCreate(text="x", trigger_at="not-a-date"))
    assert ei.value.status_code == 400


def test_reminder_update_missing_is_404(rem_db):
    with pytest.raises(api_server.HTTPException) as ei:
        api_server.reminders_update("nope", api_server.ReminderUpdate(status="completed"))
    assert ei.value.status_code == 404
