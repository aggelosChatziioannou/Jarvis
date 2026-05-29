"""Write-time hygiene gate for the graph-memory extractor.

``extract_graph_memories`` asks a small LLM to pull enduring facts out of a
conversation summary. The model occasionally proposes garbage: a Whisper
hallucination that leaked through STT ("subtitles by AUTHORWAVE"), or a
transient tool reading dressed up as a fact ("It is 12 degrees and partly
cloudy"). The prompt discourages both, but small models drift, so a
deterministic gate (the belt) drops them after parsing and before returning.

These tests drive the gate through the REAL code path: we patch
``call_llm_direct`` (the only LLM call the extractor makes) to return the
JSON the model would have produced, then assert that the parsed-and-gated
output drops the garbage and keeps legitimate facts.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import jarvis.memory.graph_ops as go


def _run(facts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Run the extractor with the LLM mocked to emit ``facts``.

    ``call_llm_direct`` is the extractor's sole LLM call; it returns a raw
    string that the extractor parses into ``{"branch", "fact"}`` objects. We
    serialise the desired ``(branch, fact)`` tuples into that exact JSON shape
    so the real parse + hygiene gate both execute.
    """
    payload = json.dumps(
        [{"branch": branch.upper(), "fact": fact} for branch, fact in facts]
    )
    with patch.object(go, "call_llm_direct", return_value=payload):
        return go.extract_graph_memories("summary", "http://x", "gemma4:e2b")


def test_drops_known_hallucination_fact():
    """A Whisper-subtitle residue that slipped through STT must never be
    stored as a fact."""
    out = _run([("WORLD", "Subtitles by the Amara.org community")])
    assert out == []


def test_drops_known_greek_hallucination_fact():
    """The canonical Greek silence hallucination (AUTHORWAVE) must be dropped
    even when the model wraps it in a fact sentence."""
    out = _run([("user", "Υπότιτλοι AUTHORWAVE")])
    assert out == []


def test_drops_transient_weather_as_fact():
    """A current-weather snapshot goes stale within hours and is not enduring
    knowledge — the transient-shape gate must drop it."""
    out = _run([("world", "Ioannina is experiencing partly cloudy weather 12.6C")])
    assert out == []


def test_drops_transient_time_as_fact():
    """The current time of day is transient, not a fact."""
    out = _run([("world", "It is currently 3:45 PM on a Sunday")])
    assert out == []


def test_keeps_legitimate_user_fact():
    """A genuine enduring user fact must survive the gate unchanged."""
    out = _run([("user", "The user lives in Ioannina")])
    assert ("user", "The user lives in Ioannina") in out


def test_keeps_legitimate_world_fact_mentioning_climate_word():
    """The transient gate keys on *current-reading* wording, not any mention
    of weather. An enduring climate fact must survive."""
    out = _run([("world", "Ioannina has cold, snowy winters")])
    assert ("world", "Ioannina has cold, snowy winters") in out


def test_drops_only_the_garbage_in_a_mixed_batch():
    """A mixed batch keeps the legitimate fact and drops the transient one —
    never an all-or-nothing wipe."""
    out = _run([
        ("user", "The user adopted a cat named Miso"),
        ("world", "It is 22 degrees and sunny in Hackney right now"),
    ])
    assert ("user", "The user adopted a cat named Miso") in out
    assert all("22 degrees" not in fact for _, fact in out)
