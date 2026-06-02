"""Embedding-based near-duplicate detection for graph facts.

String-fold dedup misses paraphrases ('the user lives in London' vs 'user
resides in London, UK'). A cosine-similarity check over nomic-embed catches
them. High threshold + opt-in by design: wrongly dropping a distinct fact harms
memory integrity, so this is conservative.
"""

from jarvis.memory.embeddings import cosine_similarity, is_semantic_duplicate


def test_cosine_basic():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine_similarity([], [1.0]) == 0.0  # safe on bad input


def test_near_duplicate_detected_above_threshold():
    vecs = {
        "the user lives in London": [1.0, 0.0],
        "user resides in London, UK": [0.99, 0.02],
        "the user has a cat": [0.0, 1.0],
    }
    embed = lambda t: vecs[t]
    assert is_semantic_duplicate("user resides in London, UK", ["the user lives in London"], embed, 0.9) is True
    assert is_semantic_duplicate("the user has a cat", ["the user lives in London"], embed, 0.9) is False


def test_failopen_when_embed_returns_none():
    # If embedding fails, never claim duplicate (don't drop a fact on error).
    assert is_semantic_duplicate("x", ["y"], lambda t: None, 0.9) is False


def test_empty_existing_lines_is_not_duplicate():
    assert is_semantic_duplicate("x", [], lambda t: [1.0], 0.9) is False
