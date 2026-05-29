"""Tier 2.4 latency optimization — Fused Intent Engine.

Collapses three sequential LLM calls (intent judge + tool router + planner,
~15-21s total) into one structured JSON call (~5-7s), saving 10-14s per query.

This module is standalone — DO NOT import from `listener.py` or
`intent_judge.py` (avoids circular dependencies; the orchestrator wires it in).

Uses Ollama's `/api/generate` with:
- `format=<JSON schema>` for structured output (Ollama 0.5+).
- `cache_prompt=True` to reuse the KV cache for the system prompt across calls.
- `keep_alive="30m"` to keep the model warm.

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


# Hardcoded tool catalogue. KNOWN ISSUE: will rot when the real MCP/tool
# registry changes. Future work: pass dynamically via cfg/registry. The vision
# entries below use the EXACT builtin tool names (seeScreen, readScreen, …) so
# the engine's allow-list resolves them against BUILTIN_TOOLS — see
# src/jarvis/vision/vision.spec.md.
_TOOL_CATALOGUE = [
    "time.now — get current time. args: {}",
    "time.date — get today's date. args: {}",
    "weather.current — get current weather. args: {location?: str}",
    "spotify.play — play music. args: {query: str}",
    "spotify.pause — pause playback. args: {}",
    "spotify.next — skip to next track. args: {}",
    "gmail.send — send an email. args: {to: str, subject: str, body: str}",
    "calendar.list — list upcoming events. args: {days?: int}",
    "notes.create — create a note. args: {title: str, body: str}",
    "web.search — web search. args: {query: str}",
    # Vision & Screen Interaction (JARVIS can see/act on the user's screen)
    "seeScreen — describe what is currently on the user's screen (windows, apps, UI elements). args: {monitor?: str}",
    "readScreen — OCR and transcribe the exact text shown on the screen (English/Greek). args: {monitor?: str}",
    "locateOnScreen — find where a UI element is and return its coordinates, without clicking. args: {target: str}",
    "clickScreen — click a UI element identified by its visible label/description. args: {target: str}",
    "typeOnScreen — type text via the keyboard. args: {text: str}",
    "scrollScreen — scroll the active window up or down. args: {direction: str, amount?: int}",
    "confirmScreenAction — execute the screen action awaiting confirmation, when the user agrees. args: {}",
]


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
    DEFAULT_TIMEOUT_SEC = 8.0

    SAFE_DEFAULT_PLAN = ["Reply to user."]

    def __init__(self, cfg):
        self.cfg = cfg
        self.base_url = str(
            getattr(cfg, "ollama_base_url", "http://localhost:11434")
        ).rstrip("/")
        self.model = str(getattr(cfg, "intent_judge_model", "gemma4:e2b"))
        # Match intent_judge.py's configured timeout, but cap at 8s per spec.
        configured = float(getattr(cfg, "intent_judge_timeout_sec", 6.0))
        self.timeout_sec = min(configured, self.DEFAULT_TIMEOUT_SEC)
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        tool_list = "\n".join(f"- {t}" for t in _TOOL_CATALOGUE)
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
            '- "fast_path_match": if utterance matches a common pattern (time.now, weather.current, spotify.play, etc.), name it; else null.\n'
            "- SCREEN AWARENESS: JARVIS can see the user's screen. When the user asks (in ANY language) "
            "what you see/observe, to look at / read / describe the screen, or to find / click / type on / "
            "scroll the screen, you MUST select a screen tool (seeScreen / readScreen / locateOnScreen / "
            "clickScreen / typeOnScreen / scrollScreen). Treat a bare \"what do you see?\" as a request to "
            "look at the screen (seeScreen), not casual chat. To click/press/tap something, use clickScreen "
            "(NOT locateOnScreen); use locateOnScreen ONLY when the user just wants to know where something "
            "is without pressing it.\n\n"
            f"Available tools (builtins + MCPs):\n{tool_list}\n"
        )

    def _build_user_prompt(
        self,
        transcript: str,
        in_hot_window: bool,
        language: str,
        last_tts_text: Optional[str],
    ) -> str:
        last = last_tts_text if last_tts_text else "None"
        return (
            f'Transcript: "{transcript}"\n'
            f"Context:\n"
            f"- in_hot_window: {str(in_hot_window).lower()}\n"
            f"- language: {language}\n"
            f"- last_tts_text: {last}\n"
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
            "keep_alive": "30m",
            "cache_prompt": True,                # Ollama: reuse KV cache for system prompt
            "think": False,                      # Disable chain-of-thought (qwen3/etc emit to `thinking` field)
            "format": FUSED_INTENT_SCHEMA,       # Ollama: enforce JSON schema
            "options": {
                "temperature": temperature,
                "num_predict": 300,
                "num_ctx": 4096,                 # smaller than judge's 8k — our prompt is short
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
        )

    def classify_route_plan(
        self,
        transcript: str,
        *,
        in_hot_window: bool = False,
        language: str = "en",
        last_tts_text: Optional[str] = None,
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
        user_prompt = self._build_user_prompt(
            transcript, in_hot_window, language, last_tts_text
        )

        last_raw = ""
        # Attempt 1: temperature=0.1 (slight randomness). Attempt 2: greedy.
        for attempt, temp in enumerate((0.1, 0.0), start=1):
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
                    f"{'retrying with temp=0.0' if attempt == 1 else 'returning safe default'}",
                    "voice",
                )
                continue
            except Exception as e:
                # Network / timeout / HTTP error — don't retry, fall through.
                debug_log(f"🧠 Fused intent attempt {attempt} error: {e}", "voice")
                break

        elapsed = (time.time() - t0) * 1000.0
        return self._safe_default(raw=last_raw, elapsed_ms=elapsed)
