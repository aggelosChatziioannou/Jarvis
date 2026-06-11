"""Live eval: the fused-intent engine routes window/market commands correctly.

Gate for the new capability slice: "put Chrome on the right screen" must
reach manageWindow, "what's open" must reach listOpenWindows, and "price of
gold" must reach getStockPrice — in English AND Greek — through the same
fused router the live voice path uses.

Run: ./scripts/run_evals.sh test_fused_window_market
"""

from types import SimpleNamespace

import pytest

from conftest import requires_judge_llm
from helpers import JUDGE_BASE_URL, JUDGE_MODEL


def _engine():
    from jarvis.listening.fused_intent import FusedIntentEngine
    cfg = SimpleNamespace(
        ollama_base_url=JUDGE_BASE_URL,
        intent_judge_model=JUDGE_MODEL,
        intent_judge_timeout_sec=8.0,
    )
    return FusedIntentEngine(cfg)


def _tool_names(judgment):
    return [t.get("name") for t in judgment.tools if isinstance(t, dict)]


class TestFusedWindowMarketRoutingLive:
    @pytest.mark.eval
    @requires_judge_llm
    @pytest.mark.parametrize("query,lang,expected", [
        pytest.param("put chrome on the right screen", "en", "manageWindow", id="move (en)"),
        pytest.param("βάλε το spotify στην αριστερή οθόνη", "el", "manageWindow", id="move (el)"),
        pytest.param("split chrome and spotify side by side", "en", "manageWindow", id="split (en)"),
        pytest.param("what windows do I have open", "en", "listOpenWindows", id="list (en)"),
        pytest.param("τι παράθυρα έχω ανοιχτά;", "el", "listOpenWindows", id="list (el)"),
        pytest.param("what's the price of gold", "en", "getStockPrice", id="gold (en)"),
        pytest.param("πόσο πάει το bitcoin;", "el", "getStockPrice", id="btc (el)"),
        pytest.param("how is NVDA doing today", "en", "getStockPrice", id="nvda (en)"),
    ])
    def test_routes_to_expected_tool(self, query, lang, expected):
        engine = _engine()
        r = engine.classify_route_plan(query, language=lang)
        names = _tool_names(r)
        # ascii-safe: Windows test consoles are cp1252; Greek queries must not
        # turn a routing PASS into a UnicodeEncodeError "failure".
        safe_q = query.encode("ascii", "backslashreplace").decode()
        print(f"\n  Fused routing ({JUDGE_MODEL}): '{safe_q}' -> intent={r.intent} tools={names}")
        assert expected in names, (
            f"{query!r} routed to {names or 'no tools'}, expected {expected}"
        )
