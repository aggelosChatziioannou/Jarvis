"""Behaviour tests for the additive memory-lifecycle schema migration.

The migration must be backward-compatible: new columns appear on fresh and
pre-existing graphs, existing rows get safe defaults, the structural nodes
(root + fixed branches) are stamped permanent/high-importance, and re-opening
an existing graph is idempotent and lossless.
"""
import sqlite3

import pytest

from jarvis.memory.graph import GraphMemoryStore

LIFECYCLE_COLS = {"importance", "ttl_days", "permanent", "version", "last_consolidated"}


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


@pytest.mark.unit
def test_fresh_store_has_lifecycle_columns(tmp_path):
    store = GraphMemoryStore(str(tmp_path / "g.db"))
    try:
        assert LIFECYCLE_COLS <= _cols(store.conn, "memory_nodes")
    finally:
        store.close()


@pytest.mark.unit
def test_structural_nodes_are_permanent_and_high_importance(tmp_path):
    store = GraphMemoryStore(str(tmp_path / "g.db"))
    try:
        rows = store.conn.execute(
            "SELECT id, permanent, importance FROM memory_nodes "
            "WHERE id IN ('root','user','directives','world')"
        ).fetchall()
        assert len(rows) == 4
        for r in rows:
            assert r["permanent"] == 1
            assert r["importance"] == 3
    finally:
        store.close()


@pytest.mark.unit
def test_new_node_gets_safe_defaults(tmp_path):
    store = GraphMemoryStore(str(tmp_path / "g.db"))
    try:
        node = store.create_node(name="X", description="d", data="hello", parent_id="user")
        row = store.conn.execute(
            "SELECT importance, ttl_days, permanent, version FROM memory_nodes WHERE id=?",
            (node.id,),
        ).fetchone()
        assert row["importance"] == 2
        assert row["ttl_days"] is None
        assert row["permanent"] == 0
        assert row["version"] == 1
        # also exposed on the dataclass
        assert node.importance == 2
        assert node.version == 1
        assert node.permanent is False
    finally:
        store.close()


@pytest.mark.unit
def test_reopen_is_idempotent_and_lossless(tmp_path):
    path = str(tmp_path / "g.db")
    store = GraphMemoryStore(path)
    nid = store.create_node(name="X", description="d", data="keep me", parent_id="user").id
    store.close()

    store2 = GraphMemoryStore(path)  # must not raise on the second open
    try:
        got = store2.get_node(nid)
        assert got is not None and got.data == "keep me"
        assert LIFECYCLE_COLS <= _cols(store2.conn, "memory_nodes")
    finally:
        store2.close()


@pytest.mark.unit
def test_old_shape_db_is_upgraded_with_defaults(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE memory_nodes (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '', parent_id TEXT,
            access_count INTEGER NOT NULL DEFAULT 0, last_accessed TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            data_token_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO memory_nodes
            (id,name,description,data,parent_id,access_count,last_accessed,created_at,updated_at,data_token_count)
        VALUES
            ('root','Root','top','',NULL,0,'2026-01-01T00:00:00','2026-01-01T00:00:00','2026-01-01T00:00:00',0),
            ('leaf1','Leaf','a leaf','old data','root',0,'2026-01-01T00:00:00','2026-01-01T00:00:00','2026-01-01T00:00:00',0);
        """
    )
    conn.commit()
    conn.close()

    store = GraphMemoryStore(path)  # migration runs on open
    try:
        assert LIFECYCLE_COLS <= _cols(store.conn, "memory_nodes")
        leaf = store.conn.execute(
            "SELECT importance, permanent, version, data FROM memory_nodes WHERE id='leaf1'"
        ).fetchone()
        assert leaf["importance"] == 2 and leaf["permanent"] == 0 and leaf["version"] == 1
        assert leaf["data"] == "old data"  # pre-existing data preserved
        root = store.conn.execute(
            "SELECT permanent, importance FROM memory_nodes WHERE id='root'"
        ).fetchone()
        assert root["permanent"] == 1 and root["importance"] == 3
    finally:
        store.close()
