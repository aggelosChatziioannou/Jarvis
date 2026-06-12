"""Tier 2.4 latency optimization — Fused Intent Engine.

Collapses three sequential LLM calls (intent judge + tool router + planner,
~15-21s total) into one structured JSON call (~5-7s), saving 10-14s per query.

This module is standalone — DO NOT import from `listener.py` or
`intent_judge.py` (avoids circular dependencies; the orchestrator wires it in).

Uses Ollama's `/api/generate` with:
- `format=<JSON schema>` for structured output (Ollama 0.5+).
- `cache_prompt=True` to reuse the KV cache for the system prompt across calls.
- `keep_alive=-1` so the shared brain stays resident (a finite value here
  re-armed an unload timer on every voice query).

The system prompt is in English; multilingual handling (Greek + English
transcripts) relies on the LLM's intrinsic capacity.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional, Any

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    requests = None
    REQUESTS_AVAILABLE = False

# Optional: try ollama python client; we don't use it (sticking to requests for
# parity with intent_judge.py), but keep the import probe for future migration.
try:
    import ollama as _ollama_pkg
    OLLAMA_PKG_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ollama_pkg = None
    OLLAMA_PKG_AVAILABLE = False

from ..debug import debug_log
from ..llm import shared_num_ctx as _shared_num_ctx


# JSON Schema constant — exact shape we want the model to return.
FUSED_INTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["directed", "query", "stop", "clarification"],
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "med", "low"],
        },
        "tools": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
        "plan": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
        },
        "fast_path_match": {
            "type": ["string", "null"],
        },
        "explanation": {
            "type": "string",
            "maxLength": 50,
        },
    },
    "required": ["intent", "confidence", "tools", "plan", "fast_path_match", "explanation"],
}


# Tools the reply engine always injects itself (``stop``) or that exist only as
# a mid-loop escape hatch (``toolSearchTool``); excluded from the routable
# catalogue the fused engine advertises so the small model focuses on real,
# user-facing tools.
_NON_ROUTABLE_TOOLS = frozenset({"stop", "toolSearchTool"})


# Minimal REAL-name fallback used ONLY when the live tool registry can't be
# imported (keeps the engine functional and — crucially — never advertises a
# name that doesn't resolve against BUILTIN_TOOLS). ``build_tool_catalogue``
# below is the normal path and also picks up configured MCP tools.
_FALLBACK_CATALOGUE: list[tuple[str, str]] = [
    ("getWeather", "get the current weather / forecast for a location"),
    ("webSearch", "search the web for current information"),
    ("fetchWebPage", "fetch and read the text of a specific web page"),
    ("logMeal", "log a meal the user says they ate"),
    ("fetchMeals", "look up the user's logged meals / nutrition"),
    ("deleteMeal", "delete a logged meal"),
    ("createReminder", "set a time-based reminder"),
    ("listReminders", "list the user's reminders"),
    ("cancelReminder", "cancel a reminder"),
    ("snoozeReminder", "snooze a reminder"),
    ("forgetMemory", "forget or correct something remembered about the user"),
    ("localFiles", "read or write files in the user's workspace"),
    ("screenshot", "capture a screenshot of the screen"),
    # Vision & Screen Interaction (JARVIS can see/act on the user's screen).
    ("seeScreen", "describe what is currently on the user's screen"),
    ("readScreen", "OCR and transcribe the exact text shown on the screen"),
    ("locateOnScreen", "find where a UI element is, without clicking"),
    ("clickScreen", "click a UI element by its visible label/description"),
    ("typeOnScreen", "type text via the keyboard"),
    ("scrollScreen", "scroll the active window up or down"),
    ("confirmScreenAction", "execute the screen action awaiting confirmation"),
    # Window management + markets (see window_manager.spec.md / stock_prices.spec.md).
    ("listOpenWindows", "list the windows/apps open on the computer"),
    ("manageWindow", "move/focus/split/maximise app windows across the user's screens"),
    ("getStockPrice", "live price of a stock, crypto, gold or an FX pair"),
]


def build_tool_catalogue() -> list[tuple[str, str]]:
    """Return the ``(name, short-description)`` catalogue the fused engine advertises.

    Built from the LIVE tool registry — real ``BUILTIN_TOOLS`` names plus any
    discovered MCP tools — so the names the model emits actually resolve in the
    reply engine's allow-list. ``generate_tools_json_schema`` silently drops
    unknown names (``BUILTIN_TOOLS.get(name)`` -> ``None`` -> ``continue``), so a
    fake/dotted name like ``weather.current`` produces an EMPTY tool schema and
    the tool can never fire — the bug this replaces.

    The import is deferred so this module stays standalone (no import cycle with
    ``listener.py``). Falls back to a minimal real-name list if the registry is
    unavailable, never to fake names.
    """
    try:
        from ..tools.registry import BUILTIN_TOOLS, get_cached_mcp_tools
    except Exception:  # pragma: no cover - registry should normally import
        return list(_FALLBACK_CATALOGUE)

    def _first_line(text: str) -> str:
        lines = (text or "").strip().splitlines()
        return (lines[0].strip() if lines else "")[:120]

    def _arg_keys(schema) -> str:
        # Advertise each tool's REAL argument keys: without them the model
        # invents plausible ones (live failure: app_name='Spotify' for a
        # tool whose only key is `name`), the concrete step parser rejects
        # the call, and the whole sequence silently degrades to prose.
        try:
            props = (schema or {}).get("properties") or {}
            keys = ", ".join(sorted(props.keys()))
            return f" (args: {keys})" if keys else ""
        except Exception:
            return ""

    out: list[tuple[str, str]] = []
    for name, tool in BUILTIN_TOOLS.items():
        if name in _NON_ROUTABLE_TOOLS:
            continue
        try:
            desc = _first_line(getattr(tool, "description", "") or "")
            desc += _arg_keys(getattr(tool, "inputSchema", None))
        except Exception:
            desc = ""
        out.append((name, desc))

    try:
        for name, spec in (get_cached_mcp_tools() or {}).items():
            desc = _first_line(getattr(spec, "description", "") or "")
            desc += _arg_keys(getattr(spec, "inputSchema", None))
            out.append((name, desc))
    except Exception:
        pass

    return out or list(_FALLBACK_CATALOGUE)


@dataclass
class FusedJudgment:
    """One-shot intent classification + tool routing + plan result.

    Note: intentionally NOT compatible with `intent_judge.IntentJudgment`
    (different fields). The orchestrator decides which to consume.
    """
    intent: str            # "directed" | "query" | "stop" | "clarification"
    confidence: str        # "high" | "med" | "low"
    tools: list            # list[dict] — [{"name": ..., "arguments": ...}]
    plan: list             # list[str] — execution steps (max 4)
    fast_path_match: Optional[str]
    explanation: str
    elapsed_ms: float
    llm_raw: str = ""
    # True when this judgment is the safe-default fallback (timeout / parse
    # failure) rather than a real model decision. Consumers must NOT treat
    # its empty tools as "no tools needed" — the engine's own router should
    # run instead.
    degraded: bool = False


class FusedIntentEngine:
    """Single-call replacement for judge -> router -> planner pipeline.

    Trades 3 sequential ~5s LLM calls for one ~5-7s structured call.

    Usage:
        engine = FusedIntentEngine(cfg)
        result = engine.classify_route_plan(
            transcript="τι ώρα είναι;",
            in_hot_window=False,
            language="el",
            last_tts_text=None,
        )
        # result.intent, result.tools, result.plan, result.elapsed_ms
    """

    # 8s hard cap per spec. intent_judge.py uses 6s; we add headroom because
    # this prompt is wider (judge + router + plan combined).
    # Generous cap: the first query after boot pays a cold multi-k-token
    # prompt eval (and the warm-up prime can be evicted by any interleaved
    # request), which reliably needs >10s on a loaded GPU. Waiting a few
    # extra seconds ONCE beats falling back to the legacy router, which is
    # markedly less reliable at picking the window/market tools.
    DEFAULT_TIMEOUT_SEC = 18.0

    SAFE_DEFAULT_PLAN = ["Reply to user."]

    def __init__(self, cfg):
        self.cfg = cfg
        self.base_url = str(
            getattr(cfg, "ollama_base_url", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.model = str(getattr(cfg, "intent_judge_model", "gemma4:e2b"))
        # The fused call does judge+router+planner in one shot over a multi-
        # k-token prompt — give it its own floor (15s) regardless of the
        # plain intent judge's tighter setting, capped by DEFAULT_TIMEOUT_SEC.
        configured = float(getattr(cfg, "intent_judge_timeout_sec", 6.0))
        self.timeout_sec = min(max(configured, 15.0), self.DEFAULT_TIMEOUT_SEC)
        # Build the tool catalogue from the LIVE registry (real names + MCP),
        # not a hardcoded list. ``_catalogue_names`` is the signature used to
        # rebuild the prompt when MCP tools are discovered after construction.
        self._catalogue: list[tuple[str, str]] = build_tool_catalogue()
        self._catalogue_names: frozenset = frozenset(n for n, _ in self._catalogue)
        self._system_prompt = self._build_system_prompt()

    def _maybe_refresh_catalogue(self) -> None:
        """Rebuild the catalogue/prompt if the live tool set changed.

        MCP tools are discovered asynchronously at startup, often AFTER the
        engine is constructed. Re-deriving the catalogue when the name set
        changes lets the fused engine route to MCP tools (Spotify, Gmail, …)
        on the live path without an extra LLM call. Cheap: a dict copy + set
        compare per utterance, prompt rebuild only on change.
        """
        try:
            current = build_tool_catalogue()
        except Exception:  # pragma: no cover - defensive
            return
        names = frozenset(n for n, _ in current)
        if names != self._catalogue_names:
            self._catalogue = current
            self._catalogue_names = names
            self._system_prompt = self._build_system_prompt()
            debug_log(f"🧠 Fused catalogue refreshed: {len(names)} tools", "voice")

    def _build_system_prompt(self) -> str:
        tool_list = "\n".join(
            (f"- {name}: {desc}" if desc else f"- {name}")
            for name, desc in self._catalogue
        )
        return (
            "You are JARVIS's intent classification + tool routing + execution planning engine.\n\n"
            "Respond ONLY with one JSON object matching this schema. No preamble. No markdown.\n\n"
            "{\n"
            '  "intent": "directed" | "query" | "stop" | "clarification",\n'
            '  "confidence": "high" | "med" | "low",\n'
            '  "tools": [{"name": string, "arguments": object}],\n'
            '  "plan": [string, ...],\n'
            '  "fast_path_match": string | null,\n'
            '  "explanation": string (max 50 chars, for log only)\n'
            "}\n\n"
            "Rules:\n"
            '- "intent":\n'
            '  - "directed" if the user is talking to JARVIS and asking for something.\n'
            '  - "query" if it\'s a follow-up question / chat (hot window).\n'
            '  - "stop" if the user is asking JARVIS to stop / be quiet.\n'
            '  - "clarification" if the utterance is ambiguous and needs to be re-asked.\n'
            '- "tools": ordered list. Empty if no tools needed.\n'
            '- "plan": short ordered list of execution steps (max 4). For chat-only replies use ["Reply to user."].\n'
            '- "fast_path_match": if the utterance matches a common pattern (e.g. getWeather, webSearch, logMeal), name it; else null.\n'
            "- SCREEN AWARENESS: JARVIS can see the user's screen. When the user asks (in ANY language) "
            "what you see/observe, to look at / read / describe the screen, or to find / click / type on / "
            "scroll the screen, you MUST select a screen tool (seeScreen / readScreen / locateOnScreen / "
            "clickScreen / typeOnScreen / scrollScreen). Treat a bare \"what do you see?\" as a request to "
            "look at the screen (seeScreen), not casual chat. To click/press/tap something, use clickScreen "
            "(NOT locateOnScreen); use locateOnScreen ONLY when the user just wants to know where something "
            "is without pressing it.\n\n"
            "- COMPUTER CONTROL: JARVIS can arrange real OS windows. When the user asks (in ANY language) "
            "what windows/apps are open or running, select listOpenWindows. When they ask to move, focus, "
            "maximise, minimise, close, snap or split an app/window, or to put an app on the left/right "
            "screen or half, select manageWindow with the app name in `window`. manageWindow arguments use "
            "EXACTLY these values: action is one of focus|move|maximize|minimize|close|split, monitor is "
            "left|right|primary|current, position is left-half|right-half|top-half|bottom-half|full. "
            "SEMANTICS: 'left/right window' or 'left/right side' (no screen/monitor word) means SNAP on "
            "the CURRENT screen — action=move, monitor=current, position=left-half/right-half. Only an "
            "explicit 'left/right SCREEN/MONITOR/οθόνη' means the other physical display (monitor=left/right). "
            "Use action=split ONLY when the user names TWO apps side by side (second app in second_window). "
            "When they ask "
            "to OPEN/launch an app that may not be running AND place it somewhere, emit the app-launcher "
            "tool (open_app) first and manageWindow second, with a 2-step plan.\n"
            "- MARKETS: when the user asks the price or performance of a stock, crypto coin, gold/silver or "
            "an FX pair (in ANY language), select getStockPrice with the asset name as `symbol`. Prefer it "
            "over webSearch for price questions.\n\n"
            "- PENDING CONFIRMATION: if the Context shows a non-empty "
            "`pending_confirmation` naming a tool, JARVIS has just asked the "
            "user to confirm that pending action. Judge the user's reply IN ITS "
            "OWN LANGUAGE. If they AGREE (yes / go ahead / do it / ναι / κάν' το / "
            "any affirmative), emit exactly that one tool and no other. If they "
            "REFUSE (no / keep it / cancel / leave it / όχι / άσ' το / any "
            "negative), emit NO tools at all. If they instead ask to act on "
            "something DIFFERENT, ignore the pending confirmation and route the "
            "new request normally.\n\n"
            f"Available tools (builtins + MCPs):\n{tool_list}\n"
        )

    def _build_user_prompt(
        self,
        transcript: str,
        in_hot_window: bool,
        language: str,
        last_tts_text: Optional[str],
        pending_confirmation: Optional[str] = None,
    ) -> str:
        last = last_tts_text if last_tts_text else "None"
        pending = pending_confirmation if pending_confirmation else "None"
        return (
            f'Transcript: "{transcript}"\n'
            f"Context:\n"
            f"- in_hot_window: {str(in_hot_window).lower()}\n"
            f"- language: {language}\n"
            f"- last_tts_text: {last}\n"
            f"- pending_confirmation: {pending}\n"
        )

    @staticmethod
    def _extract_json_object(text: str) -> str:
        """Brace-balanced JSON extractor.

        Copied from intent_judge._extract_json_object to avoid coupling. Handles
        nested braces and string escapes correctly. Returns "" if no balanced
        object is found.
        """
        start = text.find("{")
        if start == -1:
            return ""
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return ""

    def _ollama_call(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
    ) -> dict:
        """Single Ollama /api/generate call with format=<schema> + cache_prompt.

        Returns the parsed dict (with `_raw` appended for caller logging).
        Raises ValueError on JSON parse failure, RuntimeError on HTTP/network
        failure. Caller handles retry/fallback.
        """
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests library not available")

        payload = {
            "model": self.model,
            "prompt": user,
            "system": system,
            "stream": False,
            # -1 = stay resident. This call rides the SAME warm model as
            # chat/reply; a finite value here re-armed a 30m unload timer on
            # every voice query, evicting the brain after idle gaps.
            "keep_alive": -1,
            "cache_prompt": True,                # Ollama: reuse KV cache for system prompt
            "think": False,                      # Disable chain-of-thought (qwen3/etc emit to `thinking` field)
            "format": FUSED_INTENT_SCHEMA,       # Ollama: enforce JSON schema
            "options": {
                "temperature": temperature,
                "num_predict": 300,
                # Shared-brain context size — a per-call value here would
                # thrash the runner (~8.5s reload per num_ctx change).
                "num_ctx": _shared_num_ctx(),
            },
        }

        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout_sec,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        raw = body.get("response", "")
        # Fallback: if some model variant leaks JSON into `thinking` despite
        # think=false, try that field as a last resort.
        if not raw:
            thinking = body.get("thinking") or ""
            if thinking and "{" in thinking:
                raw = thinking
        if not raw:
            raise ValueError("empty response from Ollama (think suppressed)")

        # Schema-forced output is usually clean JSON, but be defensive and
        # brace-extract if the model leaks preamble around the object.
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            obj_text = self._extract_json_object(raw)
            if not obj_text:
                raise ValueError(f"no JSON object in response: {raw[:100]}")
            parsed = json.loads(obj_text)

        # Attach raw for caller logging/debugging.
        parsed["_raw"] = raw
        return parsed

    @staticmethod
    def _safe_default(raw: str = "", elapsed_ms: float = 0.0) -> "FusedJudgment":
        """Returned when both LLM attempts fail — keeps the pipeline alive."""
        return FusedJudgment(
            intent="query",
            confidence="low",
            tools=[],
            plan=["Reply to user."],
            fast_path_match=None,
            explanation="safe-default fallback",
            elapsed_ms=elapsed_ms,
            llm_raw=raw,
            degraded=True,
        )

    def classify_route_plan(
        self,
        transcript: str,
        *,
        in_hot_window: bool = False,
        language: str = "en",
        last_tts_text: Optional[str] = None,
        pending_confirmation: Optional[str] = None,
    ) -> FusedJudgment:
        """Single-call replacement for judge -> router -> planner pipeline.

        Args:
            transcript: The user's utterance (Greek or English).
            in_hot_window: True if a "hot window" is active (recent JARVIS reply).
            language: ISO code, e.g. "el" or "en".
            last_tts_text: Last thing JARVIS spoke, for context disambiguation.

        Returns:
            FusedJudgment with classification, tool calls, and execution plan.
            On total failure returns a safe default with intent="query".
        """
        t0 = time.time()
        # Pick up MCP tools discovered after construction so the catalogue the
        # model sees matches the reply engine's real allow-list.
        self._maybe_refresh_catalogue()
        user_prompt = self._build_user_prompt(
            transcript, in_hot_window, language, last_tts_text, pending_confirmation
        )

        last_raw = ""
        # Attempt 1: temperature=0.1 (slight randomness). Attempt 2: greedy.
        # GREEDY first: routing is classification, not creativity. temp 0.1
        # sampled the occasional miss live — "θα βρέξει αύριο;" judged
        # tools=[] and Jarvis confabulated "I can't see the forecast" while
        # the same phrase routed getWeather in every greedy battery run.
        # The 0.1 retry exists only to escape a deterministic parse failure.
        for attempt, temp in enumerate((0.0, 0.1), start=1):
            try:
                parsed = self._ollama_call(
                    self._system_prompt, user_prompt, temperature=temp
                )
                raw = parsed.pop("_raw", "")
                last_raw = raw
                # Tolerant field extraction — missing fields fall back to safe values.
                judgment = FusedJudgment(
                    intent=str(parsed.get("intent", "query")),
                    confidence=str(parsed.get("confidence", "low")),
                    tools=list(parsed.get("tools", []) or []),
                    plan=list(parsed.get("plan") or ["Reply to user."]),
                    fast_path_match=parsed.get("fast_path_match"),
                    explanation=str(parsed.get("explanation", ""))[:50],
                    elapsed_ms=(time.time() - t0) * 1000.0,
                    llm_raw=raw,
                )
                debug_log(
                    f"🧠 Fused intent ({(time.time()-t0)*1000:.0f}ms attempt {attempt}): "
                    f"intent={judgment.intent} conf={judgment.confidence} "
                    f"tools={len(judgment.tools)} plan_len={len(judgment.plan)}",
                    "voice",
                )
                return judgment
            except (ValueError, json.JSONDecodeError) as e:
                debug_log(
                    f"🧠 Fused intent attempt {attempt} parse error: {e}; "
                    f"{'retrying with temp=0.1' if attempt == 1 else 'returning safe default'}",
                    "voice",
                )
                continue
            except Exception as e:
                # Network / timeout / HTTP error — don't retry, fall through.
                debug_log(f"🧠 Fused intent attempt {attempt} error: {e}", "voice")
                break

        elapsed = (time.time() - t0) * 1000.0
        return self._safe_default(raw=last_raw, elapsed_ms=elapsed)
