"""Query enrichment must not re-inject facts already in the always-on warm profile.

The warm profile renders User facts on every turn under 'INFORMATION THE USER
HAS SHARED ...'. Query-driven graph enrichment injects matched node data under a
near-identical heading, so the same fact could appear twice in the system
prompt — wasted budget and a mild over-weighting risk for the small model.
"""

from jarvis.reply.engine import _strip_facts_already_in_warm
from jarvis.memory.graph import normalise_fact


def test_strips_facts_already_in_warm_profile():
    warm = {normalise_fact("the user lives in London"), normalise_fact("the user likes hiking")}
    preview = "the user lives in London\nthe user has a cat named Milo"
    out = _strip_facts_already_in_warm(preview, warm)
    assert "lives in London" not in out          # already in warm -> dropped
    assert "cat named Milo" in out               # new fact -> kept


def test_no_warm_keys_returns_unchanged():
    assert _strip_facts_already_in_warm("a fact\nanother fact", set()) == "a fact\nanother fact"


def test_empty_preview_safe():
    assert _strip_facts_already_in_warm("", {normalise_fact("x")}) == ""
