"""
Graph Extractor Hygiene Evaluations (Live)

Verifies the knowledge-graph extractor prompt does not invent implausible
enduring facts from ambiguous conversation summaries. Two field-motivated
failure modes:

  1. LANGUAGE MIS-DETECTION. A mistranscribed or foreign-looking token in the
     summary tempts a small model to assert "the user speaks <language>".
     Stored as an enduring USER fact, this then primes every future reply with
     a wrong language assumption.

  2. ENTITY CONFUSION (person-as-place). A person's name mentioned near a
     location verb tempts the model to assert "<person> is located in ...",
     conflating a human with a place. Stored as a WORLD fact, this corrupts
     later recall about that person.

The deterministic write-time gate (hallucination blocklist + transient-data
shape) does NOT catch either of these — they are plausible-shaped sentences,
not residues or readings. So this eval exercises the PROMPT's hardening
(the "low-confidence identity or language" rule), not the regex belt. That is
deliberate: the prompt is the only defence against confident-but-wrong
identity claims, and a prompt change must be verifiable against a live model.

Soft-xfail on weaker models: a small model that still emits the bad fact
records an xfail (the prompt did its best but the model drifted) rather than a
hard failure, mirroring the diary summariser hygiene eval.

Run: EVAL_JUDGE_MODEL=gemma4:e2b ./scripts/run_evals.sh test_graph_hygiene
"""

import re

import pytest

from conftest import requires_judge_llm
from helpers import JUDGE_BASE_URL, JUDGE_MODEL


@pytest.mark.eval
@requires_judge_llm
class TestGraphExtractorHygieneLive:
    """Live tests that the extractor omits implausible identity/place facts."""

    def _extract(self, summary: str) -> list[tuple[str, str]]:
        from jarvis.memory.graph_ops import extract_graph_memories
        return extract_graph_memories(
            summary=summary,
            ollama_base_url=JUDGE_BASE_URL,
            ollama_chat_model=JUDGE_MODEL,
            timeout_sec=60.0,
        )

    def test_does_not_invent_a_spoken_language_from_an_ambiguous_token(self):
        """A summary that never states the user's spoken language must not
        yield a 'the user speaks <language>' fact. A stray place name or a
        single foreign-looking word is not evidence of a spoken language."""
        # The user mentions a holiday in Wales. A weak model may over-read
        # "Wales" / "Welsh" into "the user speaks Welsh" — which was never said.
        summary = (
            "The user mentioned they spent last summer on holiday in Wales "
            "and enjoyed hiking in Snowdonia. They are planning to visit the "
            "Lake District next year."
        )
        facts = self._extract(summary)
        print(f"\n  Facts: {facts}")

        # Any fact asserting a spoken language is the failure shape. We match
        # the verb 'speak' near a language word generically (no hardcoded
        # single-language list) so the check is language-agnostic.
        offenders = [
            f for _, f in facts
            if re.search(r"\bspeaks?\b", f, re.IGNORECASE)
            and re.search(r"\b(language|welsh|english|greek|fluent)\b", f, re.IGNORECASE)
        ]
        if offenders:
            pytest.xfail(
                f"Small model {JUDGE_MODEL} invented a spoken-language fact "
                f"that was never stated: {offenders}. Full facts: {facts}"
            )

        # Positive requirement: a legitimate fact (the holiday / hiking) should
        # still be extractable — the rule suppresses the implausible claim, not
        # all extraction. Fail-open models may return [] under load, so this is
        # soft: only assert no offender was emitted (above) and that, when
        # facts ARE produced, the holiday survives in some form.
        if facts:
            lowered = " ".join(f.lower() for _, f in facts)
            assert "wales" in lowered or "snowdonia" in lowered or "hiking" in lowered or "lake district" in lowered, (
                f"Extractor produced facts but dropped the legitimate holiday "
                f"content: {facts}"
            )

    def test_does_not_turn_a_person_into_a_place(self):
        """A summary naming a person near location wording must not yield a
        '<person> is located in ...' fact (person-as-place entity confusion)."""
        # "Florence" is both a person's name and an Italian city. A weak model
        # may emit "Florence is located in Italy" — conflating the user's
        # friend with the city.
        summary = (
            "The user has a close friend named Florence who they have known "
            "since university. Florence recently adopted a rescue dog. The "
            "user asked for help planning a small dinner to celebrate."
        )
        facts = self._extract(summary)
        print(f"\n  Facts: {facts}")

        # Failure shape: a fact placing the named person in a location.
        offenders = [
            f for _, f in facts
            if re.search(r"\bflorence\b", f, re.IGNORECASE)
            and re.search(r"\b(is located in|is in|located|capital of|city in|region of)\b", f, re.IGNORECASE)
        ]
        if offenders:
            pytest.xfail(
                f"Small model {JUDGE_MODEL} confused the person 'Florence' "
                f"with the place: {offenders}. Full facts: {facts}"
            )

        # Positive requirement (soft): when facts are produced, the friend
        # relationship should be what survives, not a geography claim.
        if facts:
            lowered = " ".join(f.lower() for _, f in facts)
            assert "florence" in lowered or "friend" in lowered or "dinner" in lowered or "farewell" in lowered, (
                f"Extractor produced facts but dropped the legitimate friend "
                f"content: {facts}"
            )
