"""Behaviour tests for memory change-history (versioning) captured at merge.

A superseding merge must (a) leave the merge's own output identical to before
the audit was added, (b) bump the node version, and (c) write exactly one
memory_history row via the optional sink. A no-op rewrite writes nothing, and a
missing sink never blocks the merge (fail-open).
"""
import jarvis.memory.graph_ops as graph_ops
from jarvis.memory.graph import GraphMemoryStore
from jarvis.memory.graph_ops import merge_node_data


def _make_store(tmp_path, sink=None):
    store = GraphMemoryStore(str(tmp_path / "g.db"))
    store.history_sink = sink
    return store


def test_supersession_records_history_and_bumps_version(tmp_path, db, monkeypatch):
    monkeypatch.setattr(
        graph_ops, "call_llm_direct", lambda **kw: '{"facts": ["The user dislikes coffee."]}'
    )
    store = _make_store(tmp_path, sink=db.append_memory_history)
    try:
        node = store.create_node(
            name="Pref", description="prefs", data="The user likes coffee.", parent_id="user"
        )
        result = merge_node_data(store, node.id, ["The user dislikes coffee."], "http://x", "m")

        assert result.success
        got = store.get_node(node.id)
        # merge's visible output is unchanged by the audit hook
        assert got.data == "The user dislikes coffee."
        assert got.version == 2

        rows = db.conn.execute(
            "SELECT * FROM memory_history WHERE node_id = ?", (node.id,)
        ).fetchall()
        assert len(rows) == 1
        assert "likes" in rows[0]["old_text"]
        assert "dislikes" in rows[0]["new_text"]
        assert rows[0]["change_reason"] == "merge_supersede"
        assert rows[0]["version"] == 2
    finally:
        store.close()


def test_noop_rewrite_records_no_history(tmp_path, db, monkeypatch):
    monkeypatch.setattr(
        graph_ops, "call_llm_direct", lambda **kw: '{"facts": ["The user likes coffee."]}'
    )
    store = _make_store(tmp_path, sink=db.append_memory_history)
    try:
        node = store.create_node(
            name="Pref", description="prefs", data="The user likes coffee.", parent_id="user"
        )
        merge_node_data(store, node.id, [], "http://x", "m")  # consolidate-only, returns same set

        assert store.get_node(node.id).version == 1
        rows = db.conn.execute("SELECT * FROM memory_history").fetchall()
        assert rows == []
    finally:
        store.close()


def test_merge_with_absent_sink_still_writes_data_and_bumps_version(tmp_path, monkeypatch):
    monkeypatch.setattr(
        graph_ops, "call_llm_direct", lambda **kw: '{"facts": ["The user dislikes coffee."]}'
    )
    store = _make_store(tmp_path, sink=None)
    try:
        node = store.create_node(
            name="Pref", description="prefs", data="The user likes coffee.", parent_id="user"
        )
        result = merge_node_data(store, node.id, ["The user dislikes coffee."], "http://x", "m")
        assert result.success
        got = store.get_node(node.id)
        assert got.data == "The user dislikes coffee."
        assert got.version == 2  # version is intrinsic; bumps even without an audit sink
    finally:
        store.close()
