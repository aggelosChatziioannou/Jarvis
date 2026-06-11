"""Live eval: spoken replies respect the hard length rail (1-2 sentences).

The user's standing directive is short replies, yet casual turns came back
as 3-5 spoken sentences (8.5s of TTS for a window move confirmation). This
gates the system-prompt HARD LENGTH RAIL: casual prompts must yield at most
two sentences. Run: EVAL_JUDGE_MODEL=qwen3.5:9b-4k pytest evals/test_voice_brevity.py
"""

import re

import pytest

from conftest import requires_judge_llm
from helpers import JUDGE_BASE_URL, JUDGE_MODEL


def _sentences(text: str) -> int:
    # Sentence-ish count: terminal punctuation runs; robust enough to gate
    # "1-2 sentences vs 4+" without being a linguistics project.
    parts = [p for p in re.split(r"[.!;…]+\s+|[.!;…]+$", text.strip()) if p.strip()]
    return len(parts)


@pytest.mark.eval
@requires_judge_llm
@pytest.mark.parametrize("prompt", [
    "I just moved Spotify to your left screen for you.",  # confirmation phrasing context
    "what time do you make it?",
    "thanks, that worked",
])
def test_casual_replies_stay_under_three_sentences(prompt):
    from jarvis.llm import call_llm_direct
    from jarvis.system_prompt import build_system_prompt

    reply = call_llm_direct(
        base_url=JUDGE_BASE_URL,
        chat_model=JUDGE_MODEL,
        system_prompt=build_system_prompt("Jarvis"),
        user_content=prompt,
        timeout_sec=30.0,
        thinking=False,
    )
    assert reply and reply.strip(), "empty reply"
    n = _sentences(reply)
    assert n <= 2, f"{n} sentences for casual prompt {prompt!r}: {reply[:200]!r}"
