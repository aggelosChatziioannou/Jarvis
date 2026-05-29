"""Semantic-recall regression tests for the python/FAISS vector-store path.

On the live Windows setup ``db.is_vss_enabled`` is False (no sqlite-vss), so the
active path is the fallback vector store (FAISS when faiss-cpu is installed,
otherwise the pure-Python store) reached via ``db.upsert_summary_embedding``.
These tests pin that path: a summary's embedding must persist and be retrievable
by vector search, the write entrypoint must embed on this path, and a backfill
helper must embed pre-existing summaries.
"""

import pytest

from jarvis.memory.db import Database
import jarvis.memory.conversation as conv
import jarvis.utils.vector_store as vs
import jarvis.utils.fast_vector_store as fvs


@pytest.fixture(autouse=True)
def _reset_vector_store_singletons():
    """The fallback vector stores are module-level singletons keyed to the first
    db_path they ever saw. Reset them between tests so each temp DB gets a fresh,
    isolated store instead of leaking another test's vectors."""
    vs._python_vector_store = None
    fvs._faiss_vector_store = None
    yield
    vs._python_vector_store = None
    fvs._faiss_vector_store = None


def test_python_vector_store_roundtrip(tmp_path):
    """When sqlite-vss is unavailable, an upserted summary embedding must be
    retrievable via vector search (this is the path the live Windows DB uses)."""
    db = Database(str(tmp_path / "t.db"), sqlite_vss_path=None)
    assert db.is_vss_enabled is False  # fallback vector-store path is active

    summary_id = db.upsert_conversation_summary(
        date_utc="2026-05-29",
        summary="Angelos lives in Ioannina",
        topics="user",
        source_app="test",
    )
    emb = [0.01] * 768
    db.upsert_summary_embedding(summary_id, emb)

    hits = db.search_summaries_by_vector(emb, top_k=3)
    assert any(h["summary_id"] == summary_id for h in hits), "stored vector must be searchable"
    db.close()


def test_summary_write_populates_vector_store(tmp_path, monkeypatch):
    """Writing a summary with an embed model configured must store a vector,
    even when sqlite-vss is unavailable (the fallback store path)."""
    db = Database(str(tmp_path / "t.db"), sqlite_vss_path=None)
    assert db.is_vss_enabled is False

    # Keep the test off the network: deterministic summary + deterministic embed.
    monkeypatch.setattr(
        conv, "generate_conversation_summary",
        lambda *a, **k: ("The user lives in Ioannina.", "user, location"),
    )
    monkeypatch.setattr(
        conv, "get_embedding",
        lambda text, base, model, timeout_sec=15.0: [0.02] * 768,
    )

    summary_id = conv.update_daily_conversation_summary(
        db,
        new_chunks=["User: I live in Ioannina", "Assistant: Noted."],
        ollama_base_url="http://x",
        ollama_chat_model="gemma4:e2b",
        ollama_embed_model="nomic-embed-text",
        source_app="test",
    )
    assert summary_id is not None, "the write must succeed and return a summary id"

    rows = db.get_all_conversation_summaries()
    assert rows, "a summary row must exist"

    hits = db.search_summaries_by_vector([0.02] * 768, top_k=3)
    assert any(h["summary_id"] == summary_id for h in hits), (
        "the written summary must be vector-searchable on the python store path"
    )
    db.close()
