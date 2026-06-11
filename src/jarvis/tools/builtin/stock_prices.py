"""Market prices via the Tiingo API: stocks, crypto, FX/metals (gold).

One tool answers "how is NVDA doing?", "price of bitcoin", "πόσο πάει ο
χρυσός;". The symbol the user names (any language) is normalised to the
right Tiingo endpoint; the tool returns raw figures and the LLM loop
phrases the reply (CLAUDE.md tool conventions).

API key: ``TIINGO_API_KEY`` in ``mcps/.env`` (local, gitignored — privacy
first, the key never leaves this machine except towards api.tiingo.com).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from ...debug import debug_log
from ..base import Tool, ToolContext
from ..types import ToolExecutionResult

_MCPS_ENV = Path(__file__).resolve().parents[4] / "mcps" / ".env"

# Common spoken names -> (kind, tiingo ticker). NOT a language table — these
# are canonical ASSET names/tickers the router emits, not user phrases.
_ALIASES: Dict[str, Tuple[str, str]] = {
    "gold": ("fx", "xauusd"),
    "xau": ("fx", "xauusd"),
    "xauusd": ("fx", "xauusd"),
    "silver": ("fx", "xagusd"),
    "xag": ("fx", "xagusd"),
    "btc": ("crypto", "btcusd"),
    "bitcoin": ("crypto", "btcusd"),
    "eth": ("crypto", "ethusd"),
    "ethereum": ("crypto", "ethusd"),
    "sol": ("crypto", "solusd"),
    "solana": ("crypto", "solusd"),
    "eurusd": ("fx", "eurusd"),
    "gbpusd": ("fx", "gbpusd"),
}


def classify_symbol(symbol: str) -> Tuple[str, str]:
    """Map a spoken asset name/ticker to (kind, tiingo ticker).

    kind: 'stock' | 'crypto' | 'fx'. Unknown names default to a stock
    ticker (uppercased) — honest failure happens at the API if wrong.
    """
    s = (symbol or "").strip().lower().replace("/", "").replace("-", "")
    if not s:
        return ("stock", "")
    if s in _ALIASES:
        return _ALIASES[s]
    if s.endswith("usd") and len(s) <= 7 and not s[:1].isdigit():
        # btcusd-style pairs the router may emit directly.
        return ("crypto", s)
    return ("stock", s.upper())


def read_tiingo_key() -> str:
    """TIINGO_API_KEY from mcps/.env (same credential file the MCPs use)."""
    try:
        from dotenv import dotenv_values

        return (dotenv_values(str(_MCPS_ENV)).get("TIINGO_API_KEY") or "").strip()
    except Exception:
        return ""


def _fmt(v: Any) -> str:
    try:
        f = float(v)
        return f"{f:,.4f}".rstrip("0").rstrip(".") if f < 10 else f"{f:,.2f}"
    except Exception:
        return str(v)


_LABELS = {"xauusd": "Gold", "xagusd": "Silver", "btcusd": "BTC", "ethusd": "ETH", "solusd": "SOL"}


def fetch_quote(symbol: str, key: str) -> Optional[Dict[str, Any]]:
    """One live quote: {symbol, label, kind, price, prev, pct, low, high}.

    Shared by the getStockPrice tool and the dashboard /api/markets card.
    Returns None when the asset is unknown or Tiingo has no data; raises
    nothing (network errors return None).
    """
    kind, ticker = classify_symbol(symbol)
    if not ticker or not key:
        return None
    headers = {"Content-Type": "application/json"}
    try:
        if kind == "stock":
            r = requests.get(f"https://api.tiingo.com/iex/{ticker}",
                             params={"token": key}, headers=headers, timeout=8)
            rows = r.json() if r.ok else []
            if not rows:
                return None
            row = rows[0]
            last = row.get("last") or row.get("tngoLast") or row.get("mid")
            prev = row.get("prevClose")
            if last is None:
                return None
            pct = ((float(last) - float(prev)) / float(prev) * 100) if prev else None
            return {"symbol": symbol, "label": ticker, "kind": kind, "price": float(last),
                    "prev": float(prev) if prev else None,
                    "pct": round(pct, 2) if pct is not None else None,
                    "low": row.get("low"), "high": row.get("high")}

        endpoint = "crypto" if kind == "crypto" else "fx"
        r = requests.get(f"https://api.tiingo.com/tiingo/{endpoint}/top",
                         params={"tickers": ticker, "token": key}, headers=headers, timeout=8)
        rows = r.json() if r.ok else []
        if not rows:
            return None
        # Crypto nests quotes under topOfBookData; FX rows are flat.
        top = (rows[0].get("topOfBookData") or [rows[0]])[0] if kind == "crypto" else rows[0]
        price = top.get("lastPrice") or top.get("midPrice") or top.get("bidPrice")
        if not price:
            return None
        return {"symbol": symbol, "label": _LABELS.get(ticker, ticker.upper()), "kind": kind,
                "price": float(price), "prev": None, "pct": None,
                "bid": top.get("bidPrice"), "ask": top.get("askPrice")}
    except Exception as e:
        debug_log(f"fetch_quote({symbol}) failed: {type(e).__name__}", "tools")
        return None


class StockPriceTool(Tool):
    @property
    def name(self) -> str:
        return "getStockPrice"

    @property
    def description(self) -> str:
        return (
            "Get the live market price of a stock, cryptocurrency, gold/silver "
            "or FX pair (via Tiingo). Use whenever the user asks the price or "
            "performance of a ticker or asset, e.g. 'price of NVDA', 'how is "
            "bitcoin doing', 'gold price'. symbol is the asset name or ticker."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker or asset name, e.g. NVDA, AAPL, bitcoin, gold, EURUSD.",
                },
            },
            "required": ["symbol"],
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        symbol = str((args or {}).get("symbol", "")).strip()
        if not symbol:
            return ToolExecutionResult(success=False, reply_text=None,
                                       error_message="symbol is required")
        key = read_tiingo_key()
        if not key:
            return ToolExecutionResult(
                success=True,
                reply_text="Market data is not configured: TIINGO_API_KEY is missing from mcps/.env.",
            )

        try:
            q = fetch_quote(symbol, key)
            if q is None:
                _kind, ticker = classify_symbol(symbol)
                return ToolExecutionResult(
                    success=True,
                    reply_text=f"No market data found for '{symbol}' (ticker {ticker}).",
                )
            parts = [f"{q['label']}: {_fmt(q['price'])} USD"]
            if q.get("pct") is not None:
                parts.append(f"({q['pct']:+.2f}% vs prev close {_fmt(q.get('prev'))})")
            if q.get("low") is not None and q.get("high") is not None:
                parts.append(f"day range {_fmt(q['low'])}–{_fmt(q['high'])}")
            if q.get("bid") is not None:
                parts.append(f"bid {_fmt(q['bid'])} / ask {_fmt(q.get('ask'))}")
            return ToolExecutionResult(success=True, reply_text=" ".join(parts) + ".")
        except Exception as e:
            debug_log(f"getStockPrice failed: {e!r}", "tools")
            return ToolExecutionResult(success=False, reply_text=None,
                                       error_message=f"Market lookup failed: {type(e).__name__}")
