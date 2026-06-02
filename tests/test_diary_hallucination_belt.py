"""The diary summariser must drop pure-hallucination chunks before summarising.

The graph extractor pairs its prompt with a deterministic looks_like_hallucination
belt; the diary had none, so an STT artifact that survives on the cloud backend
('thanks for watching', 'subtitles by amara.org', pure punctuation) could be
woven into the daily summary, which then feeds vector recall and the graph
extractor. Share the same language-agnostic blocklist with the diary write path.
"""

from jarvis.memory.conversation import _drop_hallucination_chunks


def test_drops_youtube_subtitle_artifact():
    out = _drop_hallucination_chunks(["User: thanks for watching", "User: I ate a sandwich"])
    assert "User: thanks for watching" not in out
    assert "User: I ate a sandwich" in out


def test_drops_punctuation_only_chunk():
    assert _drop_hallucination_chunks(["User: ."]) == []


def test_keeps_real_content():
    chunks = ["User: remind me to call mum at 6", "Assistant: Will do."]
    assert _drop_hallucination_chunks(chunks) == chunks
