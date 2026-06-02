"""Live eval: the fused-intent engine routes a forget CONFIRMATION correctly
when told a deletion is pending (pending_confirmation="forgetMemory"). In ANY
language the router must:
  - route a YES to forgetMemory (NOT to a semantically-adjacent destructive
    tool like deleteMeal), echoing the pending fact as the subject,
  - route a NO to NO tool (so a refusal never reaches the tool, hence can
    never delete),
  - not confirm a deletion from a bare "yes" with no pending proposal.

Demonstrates the improvement from the pending-confirmation rule: WITHOUT it the
router non-deterministically routes a refusal ("no, actually keep it") to
forgetMemory, which — combined with the tool's subject-match confirm and
force-exec — risks deleting on a refusal. WITH it, a refusal reliably routes to
no tool. The engine then force-executes forgetMemory with the router's echoed
args and the tool confirms only when a provided subject positively matches the
pending proposal (see forget_memory.spec.md). The journey bug was a yes routed
to deleteMeal; this pins both that and the refusal-safety contract.

Run: ./scripts/run_evals.sh test_fused_forget   (EVAL_JUDGE_MODEL=qwen3.5:9b-4k
mirrors the live deployment).
"""

from types import SimpleNamespace

import pytest

from conftest import requires_judge_llm
from helpers import JUDGE_BASE_URL, JUDGE_MODEL


def _is_small(model_name: str) -> bool:
    from jarvis.reply.prompts import detect_model_size, ModelSize
    return detect_model_size(model_name) == ModelSize.SMALL


def _engine():
    from jarvis.listening.fused_intent import FusedIntentEngine
    cfg = SimpleNamespace(
        ollama_base_url=JUDGE_BASE_URL,
        intent_judge_model=JUDGE_MODEL,
        intent_judge_timeout_sec=8.0,
    )
    return FusedIntentEngine(cfg)


def _forget_entry(judgment):
    for t in judgment.tools:
        if isinstance(t, dict) and t.get("name") == "forgetMemory":
            return t
    return None


_PROPOSE = "I have the stored fact that you live in Berlin. Shall I remove it?"


class TestFusedForgetConfirmationLive:
    @pytest.mark.eval
    @requires_judge_llm
    @pytest.mark.parametrize("reply,lang", [
        pytest.param("yes, please delete it", "en", id="assent (en)"),
        pytest.param("ναι, διέγραψέ το", "el", id="assent (el)"),
        pytest.param("go ahead", "en", id="assent-short (en)"),
    ])
    def test_assent_routes_to_forget_not_deletemeal(self, reply, lang):
        """A yes (any language) routes to forgetMemory (and NOT to a
        semantically-adjacent destructive tool like deleteMeal). The tool then
        confirms via the echoed-subject match / confirm flag; this eval pins the
        router behaviour that the journey bug got wrong (yes -> deleteMeal)."""
        engine = _engine()
        r = engine.classify_route_plan(
            reply, language=lang, last_tts_text=_PROPOSE,
            pending_confirmation="forgetMemory",
        )
        names = [t.get("name") for t in r.tools if isinstance(t, dict)]
        print(f"\n  Fused confirm ({JUDGE_MODEL}): {reply!r} -> intent={r.intent} tools={r.tools}")
        assert "deleteMeal" not in names, \
            f"assent '{reply}' must NOT route to deleteMeal; got {names}"
        if "forgetMemory" not in names:
            msg = f"assent '{reply}' should route to forgetMemory; got {names}"
            if _is_small(JUDGE_MODEL):
                pytest.xfail(f"Small model {JUDGE_MODEL}: {msg}")
            pytest.fail(msg)

    @pytest.mark.eval
    @requires_judge_llm
    @pytest.mark.parametrize("reply,lang", [
        pytest.param("no, actually keep it", "en", id="refusal (en)"),
        pytest.param("όχι, κράτησέ το", "el", id="refusal (el)"),
    ])
    def test_refusal_does_not_confirm(self, reply, lang):
        """SAFETY: a no must NOT route to forgetMemory (so it cannot delete)."""
        engine = _engine()
        r = engine.classify_route_plan(
            reply, language=lang, last_tts_text=_PROPOSE,
            pending_confirmation="forgetMemory",
        )
        names = [t.get("name") for t in r.tools if isinstance(t, dict)]
        print(f"\n  Fused refusal ({JUDGE_MODEL}): {reply!r} -> intent={r.intent} tools={names}")
        assert "forgetMemory" not in names, \
            f"refusal '{reply}' must not route to forgetMemory; got {names}"

    @pytest.mark.eval
    @requires_judge_llm
    def test_bare_yes_without_pending_does_not_confirm(self):
        """Control: a bare 'yes' with NO pending confirmation must not confirm a
        deletion (no stray deletes from an unrelated affirmative)."""
        engine = _engine()
        r = engine.classify_route_plan("yes", language="en")
        entry = _forget_entry(r)
        print(f"\n  Fused control ({JUDGE_MODEL}): 'yes' (no pending) -> tools={r.tools}")
        assert entry is None or not (entry.get("arguments") or {}).get("confirm"), \
            f"bare 'yes' with no pending must not confirm a deletion; got {r.tools}"
