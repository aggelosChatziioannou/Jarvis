"""Tests for the review-gated graph-fact scrub (`graph_ops.scrub_graph_facts`
and `graph_ops.apply_graph_scrub`).

The scrub mirrors the diary deflection scrub: an LLM proposes per-fact
deletion verdicts, but NOTHING is mutated until the local user confirms.
``scrub_graph_facts`` returns proposals only; ``apply_graph_scrub`` removes
exactly the approved lines and nothing else.

Tests stub the LLM verdict so they stay deterministic and offline.
"""

from __future__ import annotations

from unittest.mock import patch

import jarvis.memory.graph_ops as go
from jarvis.memory.graph import (
    BRANCH_DIRECTIVES,
    BRANCH_USER,
    BRANCH_WORLD,
)


class FakeStore:
    """Minimal stand-in for ``GraphMemoryStore`` covering the node API the
    scrub touches: ``get_node`` (returns an object with ``.data``) and
    ``update_node(node_id, *, data=...)``.
    """

    def __init__(self, branches: dict) -> None:
        self._b = dict(branches)
        self.updates: list[tuple[str, str]] = []

    def get_node(self, node_id):
        if node_id not in self._b:
            return None

        class _N:
            pass

        n = _N()
        n.id = node_id
        n.data = self._b.get(node_id, "")
        return n

    def update_node(self, node_id, *, data):
        self._b[node_id] = data
        self.updates.append((node_id, data))


# ── Task 7: scrub_graph_facts (proposal generator) ────────────────────


def test_scrub_proposes_drops_with_reasons():
    store = FakeStore({BRANCH_USER: "The user lives in Ioannina\nThe user speaks Welsh"})
    # Mock the per-branch LLM verdict: keep line 0, drop line 1.
    with patch.object(
        go,
        "_judge_facts",
        return_value=[
            {"fact": "The user speaks Welsh", "drop": True, "reason": "transcription artefact"},
        ],
    ):
        result = go.scrub_graph_facts(store, "http://x", "gemma4:e2b")

    drops = [d for d in result["proposals"] if d["drop"]]
    assert any("Welsh" in d["fact"] for d in drops)
    assert all("reason" in d for d in drops)
    # Every proposal carries the branch it came from so apply can target it.
    assert all("branch" in d for d in result["proposals"])
    # PROPOSAL ONLY — nothing deleted yet.
    assert result["applied"] is False
    # The store must not have been mutated by a propose call.
    assert store.updates == []
    assert "Welsh" in store._b[BRANCH_USER]


def test_scrub_walks_all_three_branches():
    store = FakeStore(
        {
            BRANCH_USER: "The user lives in Ioannina",
            BRANCH_DIRECTIVES: "Always answer in British English",
            BRANCH_WORLD: "Possessor is a 2020 film",
        }
    )
    seen_branches: list[str] = []

    def _fake_judge(facts, branch, *args, **kwargs):
        seen_branches.append(branch)
        return []

    with patch.object(go, "_judge_facts", side_effect=_fake_judge):
        result = go.scrub_graph_facts(store, "http://x", "gemma4:e2b")

    assert set(seen_branches) == {BRANCH_USER, BRANCH_DIRECTIVES, BRANCH_WORLD}
    assert result["applied"] is False


def test_scrub_fails_open_on_llm_failure():
    """LLM/JSON failure -> empty proposals, never raises, never mutates."""
    store = FakeStore({BRANCH_USER: "The user lives in Ioannina"})

    with patch.object(go, "_judge_facts", side_effect=RuntimeError("ollama down")):
        result = go.scrub_graph_facts(store, "http://x", "gemma4:e2b")

    assert result["proposals"] == []
    assert result["applied"] is False
    assert store.updates == []


def test_scrub_skips_empty_branch_nodes():
    """A branch with no facts produces no proposals and no LLM call."""
    store = FakeStore({BRANCH_USER: "", BRANCH_DIRECTIVES: "   ", BRANCH_WORLD: ""})
    judged: list = []

    def _fake_judge(facts, branch, *args, **kwargs):
        judged.append(branch)
        return []

    with patch.object(go, "_judge_facts", side_effect=_fake_judge):
        result = go.scrub_graph_facts(store, "http://x", "gemma4:e2b")

    assert judged == []
    assert result["proposals"] == []
    assert result["applied"] is False


# ── Task 8: apply_graph_scrub (apply-on-confirm) ──────────────────────


def test_apply_removes_only_approved_facts():
    store = FakeStore({BRANCH_USER: "The user lives in Ioannina\nThe user speaks Welsh"})
    res = go.apply_graph_scrub(
        store, [{"branch": BRANCH_USER, "fact": "The user speaks Welsh"}]
    )
    assert "Welsh" not in store._b[BRANCH_USER]
    assert "Ioannina" in store._b[BRANCH_USER]  # untouched fact preserved
    assert res["removed"] == 1  # counts-only


def test_apply_returns_counts_only_no_raw_text():
    """The apply return value must never echo raw fact text — the streaming
    layer surfaces it, and that channel is counts-only.
    """
    store = FakeStore({BRANCH_USER: "The user lives in Ioannina\nThe user speaks Welsh"})
    res = go.apply_graph_scrub(
        store, [{"branch": BRANCH_USER, "fact": "The user speaks Welsh"}]
    )
    blob = repr(res).lower()
    assert "welsh" not in blob
    assert "ioannina" not in blob
    assert set(res.keys()) <= {"removed"}


def test_apply_preserves_other_lines_across_branches():
    store = FakeStore(
        {
            BRANCH_USER: "Fact A\nFact B\nFact C",
            BRANCH_WORLD: "World 1\nWorld 2",
        }
    )
    res = go.apply_graph_scrub(
        store,
        [
            {"branch": BRANCH_USER, "fact": "Fact B"},
            {"branch": BRANCH_WORLD, "fact": "World 1"},
        ],
    )
    assert store._b[BRANCH_USER] == "Fact A\nFact C"
    assert store._b[BRANCH_WORLD] == "World 2"
    assert res["removed"] == 2


def test_apply_empty_approved_list_is_noop():
    store = FakeStore({BRANCH_USER: "Fact A\nFact B"})
    res = go.apply_graph_scrub(store, [])
    assert res["removed"] == 0
    assert store.updates == []
    assert store._b[BRANCH_USER] == "Fact A\nFact B"


def test_apply_unknown_fact_removes_nothing():
    """An approved fact that no longer exists on the node removes nothing and
    is not counted — the node is left untouched.
    """
    store = FakeStore({BRANCH_USER: "Fact A\nFact B"})
    res = go.apply_graph_scrub(
        store, [{"branch": BRANCH_USER, "fact": "Fact that is not present"}]
    )
    assert res["removed"] == 0
    assert store._b[BRANCH_USER] == "Fact A\nFact B"


def test_apply_fails_open_on_missing_branch_node():
    """An approved fact for a branch with no node is skipped, not fatal."""
    store = FakeStore({BRANCH_USER: "Fact A"})
    res = go.apply_graph_scrub(
        store, [{"branch": "nonexistent", "fact": "whatever"}]
    )
    assert res["removed"] == 0
