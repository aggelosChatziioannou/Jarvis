"""The weekly prune DELETE job must not be a default-enabled footgun.

prune_low_importance deletes importance==0 leaf nodes, but nothing in the
codebase ever sets importance below the default 2 — so the job is a proven
no-op today. Default-enabled, it would silently activate the moment importance
tagging lands. Keep it OFF by default and lock the no-op contract so a future
tagging change can't quietly start deleting user memory.
"""

from jarvis.config import get_default_config
from jarvis.memory.graph import GraphMemoryStore, BRANCH_USER


def test_weekly_prune_disabled_by_default():
    assert get_default_config()["memory_weekly_prune_enabled"] is False


def test_default_graph_yields_no_prune_candidates(tmp_path):
    store = GraphMemoryStore(str(tmp_path / "g.db"))
    try:
        store.create_node(
            "Profile", "user profile",
            data="the user lives in Athens",
            parent_id=BRANCH_USER,
        )
        # min_age_days=0 removes age as a factor — only importance gates here.
        assert store.prune_low_importance(min_age_days=0) == 0
    finally:
        store.close()
