"""Behaviour tests for TTL purge + weekly low-importance prune.

Both are leaf-only and exempt structural/permanent/normal-importance nodes, so
identity scaffolding is never removed. Scenarios are set up by writing the
lifecycle columns directly (there is no public setter, by design).
"""
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.memory.graph import GraphMemoryStore


def _iso(dt):
    return dt.isoformat()


@pytest.fixture
def store(tmp_path):
    s = GraphMemoryStore(str(tmp_path / "g.db"))
    yield s
    s.close()


def _set(store, node_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    store.conn.execute(
        f"UPDATE memory_nodes SET {cols} WHERE id = ?", (*fields.values(), node_id)
    )
    store.conn.commit()


# ── TTL purge ───────────────────────────────────────────────────────────
@pytest.mark.unit
def test_ttl_purges_expired_low_importance_leaf(store):
    old = _iso(datetime.now(timezone.utc) - timedelta(days=3))
    n = store.create_node(name="L", description="d", data="x", parent_id="user")
    _set(store, n.id, importance=1, ttl_days=1, updated_at=old)

    removed = store.purge_expired_nodes()
    assert removed >= 1
    assert store.get_node(n.id) is None


@pytest.mark.unit
def test_ttl_keeps_normal_importance_even_if_elapsed(store):
    old = _iso(datetime.now(timezone.utc) - timedelta(days=10))
    n = store.create_node(name="L", description="d", data="x", parent_id="user")
    _set(store, n.id, importance=2, ttl_days=1, updated_at=old)

    store.purge_expired_nodes()
    assert store.get_node(n.id) is not None


@pytest.mark.unit
def test_ttl_keeps_node_without_a_ttl(store):
    old = _iso(datetime.now(timezone.utc) - timedelta(days=10))
    n = store.create_node(name="L", description="d", data="x", parent_id="user")
    _set(store, n.id, importance=1, updated_at=old)  # ttl_days stays NULL

    store.purge_expired_nodes()
    assert store.get_node(n.id) is not None


@pytest.mark.unit
def test_ttl_exempts_parents_only_leaves_expire(store):
    old = _iso(datetime.now(timezone.utc) - timedelta(days=10))
    parent = store.create_node(name="P", description="d", data="x", parent_id="user")
    store.create_node(name="C", description="d", data="y", parent_id=parent.id)
    _set(store, parent.id, importance=1, ttl_days=1, updated_at=old)

    store.purge_expired_nodes()
    assert store.get_node(parent.id) is not None  # has a child -> not a leaf -> exempt


@pytest.mark.unit
def test_ttl_never_removes_structural_nodes(store):
    old = _iso(datetime.now(timezone.utc) - timedelta(days=999))
    _set(store, "user", ttl_days=1, updated_at=old)  # permanent=1, importance=3 stay

    store.purge_expired_nodes()
    assert store.get_node("user") is not None


# ── weekly low-importance prune ──────────────────────────────────────────
@pytest.mark.unit
def test_weekly_prune_removes_aged_ephemeral_leaf(store):
    old = _iso(datetime.now(timezone.utc) - timedelta(days=40))
    n = store.create_node(name="L", description="d", data="x", parent_id="world")
    _set(store, n.id, importance=0, updated_at=old)

    removed = store.prune_low_importance(min_age_days=30)
    assert removed >= 1
    assert store.get_node(n.id) is None


@pytest.mark.unit
def test_weekly_prune_keeps_fresh_ephemeral(store):
    n = store.create_node(name="L", description="d", data="x", parent_id="world")
    _set(store, n.id, importance=0)  # updated_at is now (fresh)

    store.prune_low_importance(min_age_days=30)
    assert store.get_node(n.id) is not None


@pytest.mark.unit
def test_weekly_prune_keeps_importance_one_and_above(store):
    old = _iso(datetime.now(timezone.utc) - timedelta(days=40))
    n = store.create_node(name="L", description="d", data="x", parent_id="world")
    _set(store, n.id, importance=1, updated_at=old)

    store.prune_low_importance(min_age_days=30)
    assert store.get_node(n.id) is not None
