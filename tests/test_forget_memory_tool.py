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


# ── Paraphrase recall (embedding fallback) ──────────────────────────────────
# The strict matcher misses paraphrases: "resides in London" never matches the
# stored "the user lives in London" because the tokens differ. A fail-open
# embedding pass runs ONLY when the strict pass finds nothing, so a near-
# paraphrase is surfaced for the user to confirm. propose -> confirm is
# untouched: looser recall can only PROPOSE an extra candidate, never delete.

def _embed_ctx(db_path, threshold=0.8):
    cfg = SimpleNamespace(
        db_path=db_path,
        ollama_base_url="http://stub",
        ollama_embed_model="stub-embed",
        memory_forget_semantic_threshold=threshold,
    )
    return ToolContext(
        db=None, cfg=cfg, system_prompt="", original_prompt="",
        redacted_text="", max_retries=0, user_print=Mock(),
    )


def _location_cluster_embed(text, *args, **kwargs):
    """Stub: location facts share a vector; hiking is orthogonal."""
    t = (text or "").lower()
    if "hiking" in t:
        return [0.0, 1.0]
    return [1.0, 0.0]  # 'lives/resides in london' cluster


def test_propose_finds_paraphrase_via_embeddings(graph_db, monkeypatch):
    fm._reset_pending()
    monkeypatch.setattr(fm, "_embed_text", _location_cluster_embed)
    res = ForgetMemoryTool().run({"subject": "resides in London"}, _embed_ctx(graph_db))
    assert res.success
    assert "London" in (res.reply_text or "")            # surfaced by semantic recall
    assert "lives in London" in _all_data(graph_db)      # NOTHING deleted on propose


def test_paraphrase_then_confirm_deletes_only_match(graph_db, monkeypatch):
    fm._reset_pending()
    monkeypatch.setattr(fm, "_embed_text", _location_cluster_embed)
    tool = ForgetMemoryTool()
    tool.run({"subject": "resides in London"}, _embed_ctx(graph_db))   # paraphrase propose
    tool.run({"confirm": True}, _embed_ctx(graph_db))                  # confirm
    data = _all_data(graph_db)
    assert "lives in London" not in data                 # the matched fact is gone
    assert "likes hiking" in data                        # orthogonal fact retained


def test_semantic_recall_fails_open_when_embeddings_unavailable(graph_db, monkeypatch):
    fm._reset_pending()
    monkeypatch.setattr(fm, "_embed_text", lambda *a, **k: None)  # embed server down
    res = ForgetMemoryTool().run({"subject": "resides in London"}, _embed_ctx(graph_db))
    # No exception; with no embeddings it degrades to the strict matcher, which
    # cannot match the paraphrase -> proposes nothing, deletes nothing.
    assert res.success
    assert "lives in London" in _all_data(graph_db)


def test_paraphrase_threshold_is_config_driven(graph_db, monkeypatch):
    fm._reset_pending()

    # Borderline cosine ~0.6 between subject and the london line.
    def borderline_embed(text, *a, **k):
        t = (text or "").lower()
        if "hiking" in t:
            return [0.0, 1.0]
        if "resides" in t:               # the subject
            return [0.8, 0.6]
        return [1.0, 0.0]                 # stored london line  (cos = 0.8 with subject)

    monkeypatch.setattr(fm, "_embed_text", borderline_embed)
    # Threshold ABOVE the pair similarity -> nothing proposed (no_match).
    res_hi = ForgetMemoryTool().run({"subject": "resides in London"}, _embed_ctx(graph_db, threshold=0.95))
    assert "no_match:" in (res_hi.reply_text or "")
    assert "lives in London" in _all_data(graph_db)      # nothing staged for deletion
    fm._reset_pending()
    # Threshold BELOW the pair similarity -> proposed. Behaviour is driven by
    # the cfg threshold, not a hardcoded constant in the tool.
    res_lo = ForgetMemoryTool().run({"subject": "resides in London"}, _embed_ctx(graph_db, threshold=0.5))
    assert "requires_confirmation" in (res_lo.reply_text or "")


# ── Premature-confirm guard (test-only: this is already the live behaviour) ──

def test_first_call_confirm_true_does_not_delete(graph_db):
    """A model that sets confirm:true on the very first call must not wipe
    memory — with no fresh pending proposal the tool proposes instead."""
    fm._reset_pending()
    res = ForgetMemoryTool().run(
        {"subject": "lives in London", "confirm": True}, _ctx(graph_db)
    )
    assert "lives in London" in _all_data(graph_db)      # not deleted
    assert "requires_confirmation" in (res.reply_text or "")  # proposed instead


# ── Unambiguous no-match contract (anti-confabulation) ──────────────────────

def test_no_match_result_is_unambiguous(graph_db):
    """A zero-match outcome must carry an explicit discriminator so the persona
    model cannot narrate it as a successful deletion."""
    fm._reset_pending()
    res = ForgetMemoryTool().run({"subject": "quantum chromodynamics"}, _ctx(graph_db))
    assert res.success
    assert "no_match:" in (res.reply_text or "")


# ── Utterance-subject fallback + pending-as-consent ─────────────────────────
# The live fused router emits unreliable argument names ('memory',
# 'memory_to_delete') and never sets `confirm`, and the chat model often does
# not emit the call at all. So the tool (force-executed by the engine) derives
# its subject from the user's own utterance, and treats "routed here again
# while a fresh proposal is pending" as consent — safe because the upstream
# router does NOT route refusals ("no, keep it") to forgetMemory.

def _utterance_ctx(db_path, utterance, threshold=0.8):
    cfg = SimpleNamespace(
        db_path=db_path,
        ollama_base_url="http://stub",
        ollama_embed_model="stub-embed",
        memory_forget_semantic_threshold=threshold,
    )
    return ToolContext(
        db=None, cfg=cfg, system_prompt="", original_prompt="",
        redacted_text=utterance, max_retries=0, user_print=Mock(),
    )


def _london_cluster_embed(text, *args, **kwargs):
    """Stub: anything about living/London clusters together; hiking is its own
    cluster; short affirmations ('yes delete it') are neutral and match nothing."""
    t = (text or "").lower()
    if "hiking" in t:
        return [0.0, 1.0]
    if "london" in t or "live" in t or "resid" in t:
        return [1.0, 0.0]
    return [0.5, 0.5]  # affirmations etc.


def test_subject_falls_back_to_utterance_when_args_wrong(graph_db, monkeypatch):
    fm._reset_pending()
    monkeypatch.setattr(fm, "_embed_text", _london_cluster_embed)
    # Wrong arg key ('memory'), no 'subject' — must use the utterance instead.
    ctx = _utterance_ctx(graph_db, "Please forget that I live in London")
    res = ForgetMemoryTool().run({"memory": "London"}, ctx)
    assert "requires_confirmation" in (res.reply_text or "")
    assert "lives in London" in _all_data(graph_db)   # proposed, nothing deleted


def test_routed_call_while_pending_confirms_and_deletes(graph_db, monkeypatch):
    fm._reset_pending()
    monkeypatch.setattr(fm, "_embed_text", _london_cluster_embed)
    tool = ForgetMemoryTool()
    tool.run({}, _utterance_ctx(graph_db, "forget that I live in London"))     # propose
    # A routed assent with no 'confirm' flag and no new subject -> consent.
    tool.run({}, _utterance_ctx(graph_db, "yes, delete it please"))            # confirm
    data = _all_data(graph_db)
    assert "lives in London" not in data
    assert "likes hiking" in data


def test_has_fresh_pending_tracks_proposal_lifecycle(graph_db):
    """The engine keeps forgetMemory in the allow-list while a proposal is
    pending; has_fresh_pending() drives that."""
    fm._reset_pending()
    assert fm.has_fresh_pending() is False
    ForgetMemoryTool().run({"subject": "lives in London"}, _ctx(graph_db))  # propose
    assert fm.has_fresh_pending() is True
    ForgetMemoryTool().run({"confirm": True}, _ctx(graph_db))               # confirm clears it
    assert fm.has_fresh_pending() is False


def test_distinct_new_subject_reproposes_instead_of_confirming(graph_db, monkeypatch):
    fm._reset_pending()
    monkeypatch.setattr(fm, "_embed_text", _london_cluster_embed)
    tool = ForgetMemoryTool()
    tool.run({}, _utterance_ctx(graph_db, "forget that I live in London"))     # propose London
    res = tool.run({}, _utterance_ctx(graph_db, "actually, forget that I like hiking"))  # pivot
    # Pivot re-proposes hiking; nothing deleted yet, both facts still present.
    assert "lives in London" in _all_data(graph_db)
    assert "likes hiking" in _all_data(graph_db)
    assert "hiking" in (res.reply_text or "")
