from __future__ import annotations
import math
from typing import Callable, Optional, Sequence
import requests


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors. Returns 0.0 on empty/mismatched input."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def is_semantic_duplicate(
    candidate: str,
    existing_lines: Sequence[str],
    embed_fn: Callable[[str], Optional[Sequence[float]]],
    threshold: float,
) -> bool:
    """True if ``candidate`` is a near-duplicate of any existing line.

    Catches paraphrases that string-fold dedup misses. Fail-open: if any
    embedding can't be computed, the comparison is skipped (never reports a
    duplicate on error), so a transient embed failure can't drop a fact.
    Conservative by design — callers should use a high threshold, because
    wrongly dropping a distinct fact harms memory integrity.
    """
    if not candidate or not existing_lines:
        return False
    cand_vec = embed_fn(candidate)
    if not cand_vec:
        return False
    for line in existing_lines:
        line_vec = embed_fn(line)
        if not line_vec:
            continue
        if cosine_similarity(cand_vec, line_vec) >= threshold:
            return True
    return False


def get_embedding(text: str, base_url: str, model: str, timeout_sec: float = 15.0) -> list[float] | None:
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        data = resp.json()
        vec = data.get("embedding")
        if isinstance(vec, list):
            return [float(x) for x in vec]
    except Exception:
        return None
    return None
