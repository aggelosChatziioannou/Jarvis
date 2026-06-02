"""logMeal must not burn two serial chat-model calls on the reply hot path.

extract_and_log_meal ran an LLM extraction at the full 180s chat timeout and
then a SECOND chat call (follow-up coaching) also at 180s, serially. Make the
follow-up opt-in (default off) and give the extraction its own short timeout.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import jarvis.tools.builtin.nutrition.log_meal as lm

_MEAL_JSON = '{"description": "sandwich", "calories_kcal": 400, "protein_g": 20}'


def _cfg(**kw):
    base = dict(ollama_base_url="http://x", ollama_chat_model="m", llm_chat_timeout_sec=180.0)
    base.update(kw)
    return SimpleNamespace(**base)


def _db():
    db = Mock()
    db.insert_meal.return_value = 7
    return db


def test_followups_disabled_by_default_single_llm_call():
    calls = []

    def fake_llm(base, model, sys, user, timeout_sec=None, thinking=False):
        calls.append(timeout_sec)
        return _MEAL_JSON

    with patch.object(lm, "call_llm_direct", side_effect=fake_llm):
        reply = lm.extract_and_log_meal(_db(), _cfg(), "I ate a sandwich", "jarvis")

    assert reply is not None
    assert "Follow-ups:" not in reply
    assert len(calls) == 1  # extraction only — no second chat call


def test_followups_enabled_makes_second_call():
    n = {"i": 0}

    def fake_llm(base, model, sys, user, timeout_sec=None, thinking=False):
        n["i"] += 1
        return _MEAL_JSON if n["i"] == 1 else "Drink water and add veg."

    with patch.object(lm, "call_llm_direct", side_effect=fake_llm):
        reply = lm.extract_and_log_meal(
            _db(), _cfg(nutrition_followups_enabled=True), "I ate a sandwich", "jarvis"
        )

    assert "Follow-ups:" in reply
    assert n["i"] == 2


def test_extraction_uses_short_timeout_not_chat_180():
    timeouts = []

    def fake_llm(base, model, sys, user, timeout_sec=None, thinking=False):
        timeouts.append(timeout_sec)
        return _MEAL_JSON

    with patch.object(lm, "call_llm_direct", side_effect=fake_llm):
        lm.extract_and_log_meal(_db(), _cfg(), "I ate a sandwich", "jarvis")

    assert timeouts[0] <= 30.0  # extraction is a tiny structured task, not a 180s chat
