"""Behaviour tests for the forgetMemory tool (voice "forget that").

A user can ask Jarvis to forget/correct a stored fact by voice. The tool
PROPOSES the deletion first (lists matching facts, deletes nothing) and only
removes them on an explicit confirm — mirroring the vision engine's
propose -> confirmScreenAction safety so a misheard "forget" can't wipe memory.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.memory.graph import GraphMemoryStore, BRANCH_USER
import jarvis.tools.builtin.forget_memory as fm
from jarvis.tools.builtin.forget_memory import ForgetMemoryTool
from jarvis.tools.base import ToolContext


@pytest.fixture
def graph_db(tmp_path):
    path = str(tmp_path / "g.db")
    store = GraphMemoryStore(path)
    store.create_node(
        "Profile", "user profile",
        data="the user lives in London\nthe user likes hiking",
        parent_id=BRANCH_USER,
    )
    store.close()
    return path


def _ctx(db_path, redacted=""):
    cfg = SimpleNamespace(db_path=db_path)
    return ToolContext(
        db=None, cfg=cfg, system_prompt="", original_prompt="",
        redacted_text=redacted, max_retries=0, user_print=Mock(),
    )


def _all_data(db_path):
    store = GraphMemoryStore(db_path)
    try:
        return "\n".join(n.data for n in store.get_all_nodes() if n.data)
    finally:
        store.close()


def test_propose_lists_candidates_without_deleting(graph_db):
    fm._reset_pending()
    res = ForgetMemoryTool().run({"subject": "lives in London"}, _ctx(graph_db))
    assert res.success
    assert "London" in (res.reply_text or "")
    assert "lives in London" in _all_data(graph_db)  # NOT deleted on propose


def test_confirm_deletes_the_proposed_fact(graph_db):
    fm._reset_pending()
    tool = ForgetMemoryTool()
    tool.run({"subject": "lives in London"}, _ctx(graph_db))      # propose
    res = tool.run({"confirm": True}, _ctx(graph_db))             # confirm
    assert res.success
    data = _all_data(graph_db)
    assert "lives in London" not in data       # forgotten
    assert "likes hiking" in data              # unrelated fact retained


def test_confirm_without_prior_proposal_deletes_nothing(graph_db):
    fm._reset_pending()
    ForgetMemoryTool().run({"confirm": True}, _ctx(graph_db))
    assert "lives in London" in _all_data(graph_db)


def test_no_match_deletes_nothing(graph_db):
    fm._reset_pending()
    ForgetMemoryTool().run({"subject": "quantum chromodynamics"}, _ctx(graph_db))
    ForgetMemoryTool().run({"confirm": True}, _ctx(graph_db))
    assert "lives in London" in _all_data(graph_db)


def test_registered_in_builtin_tools():
    from jarvis.tools.registry import BUILTIN_TOOLS
    assert "forgetMemory" in BUILTIN_TOOLS
