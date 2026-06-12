# getStockPrice Tool Spec

## Purpose

Live market prices by voice: stocks (Tiingo IEX), crypto (Tiingo crypto
top-of-book), FX/metals (Tiingo fx top-of-book — gold = XAUUSD). One tool,
one `symbol` argument; the router fills it with the asset the user named
in any language. Arg forgiveness (`effective_symbol`): `query`, `ticker`,
`name`, `asset` are accepted as synonyms — the legacy planner emitted
`query='NVDA'` and the call failed over the key name while the value was
perfectly usable.

## Principles

- **Raw data out**: figures + day range; the LLM loop phrases the reply.
- **Symbol normalisation, not language patterns**: `_ALIASES` maps
  canonical asset names/tickers (gold, btc, eurusd…) to the right
  endpoint. Unknown input is treated as a stock ticker — wrong guesses
  fail honestly at the API ("No market data found"), never confabulate.
- **Key handling**: `TIINGO_API_KEY` lives in `mcps/.env` (gitignored).
  Missing key → honest "not configured" reply, success=True (the model
  should tell the user, not retry).
- Fixed host (api.tiingo.com), 8s timeout, every failure caught — the
  tool never raises into the engine and never hangs a thread.
