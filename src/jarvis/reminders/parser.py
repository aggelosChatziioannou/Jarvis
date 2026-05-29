"""Natural-language time parsing for reminders.

Routing (cheapest first, LLM last):
  1. Recurrence: a leading/standalone "every"/"κάθε" with a resolvable weekday
     (or daily marker) + time becomes a 5-field cron string.
  2. One-time: ``dateparser`` resolves relative (EL/EN) and absolute (EN) phrases
     to a future instant.
  3. Fallback: anything dateparser can't pin to a future time goes to a strict,
     low-temperature LLM call that must reply with an ISO datetime, a 5-field
     cron, or NONE.

The parser fails *closed*: an unresolvable phrase yields ``None`` rather than a
guessed time, so a wrong-time reminder is never created.

The EN/EL recurrence table is a deterministic fast path for the two declared
product languages. Other languages and phrasings are NOT excluded: they still
resolve via dateparser (multilingual) or the LLM fallback.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from jarvis.debug import debug_log
from jarvis.llm import call_llm_direct

from .models import ParsedWhen

# cron day-of-week numbering: 0 = Sunday … 6 = Saturday
_WEEKDAYS = {
    "monday": 1, "mon": 1, "δευτέρα": 1, "δευτερα": 1,
    "tuesday": 2, "tue": 2, "τρίτη": 2, "τριτη": 2,
    "wednesday": 3, "wed": 3, "τετάρτη": 3, "τεταρτη": 3,
    "thursday": 4, "thu": 4, "πέμπτη": 4, "πεμπτη": 4,
    "friday": 5, "fri": 5, "παρασκευή": 5, "παρασκευη": 5,
    "saturday": 6, "sat": 6, "σάββατο": 6, "σαββατο": 6,
    "sunday": 0, "sun": 0, "κυριακή": 0, "κυριακη": 0,
}
_RECURRENCE_RE = re.compile(r"\b(every|κάθε|καθε)\b", re.UNICODE)
_DAILY_MARKERS = (
    "every day", "everyday", "daily",
    "κάθε μέρα", "καθε μερα", "κάθε μερα", "καθε μέρα", "καθημεριν",
)
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|π\.?μ\.?|μ\.?μ\.?)?", re.UNICODE)


def parse_when(text: str, cfg, now: datetime, language: Optional[str] = None) -> Optional[ParsedWhen]:
    """Resolve a natural-language time phrase to a ParsedWhen, or None."""
    if not text or not text.strip():
        return None

    cron = _try_recurrence_cron(text)
    if cron:
        debug_log(f"reminder parse: recurrence -> cron '{cron}'", "reminders")
        return ParsedWhen(cron=cron)

    dt = _dateparser_parse(text, now, language)
    if dt is not None and dt > now:
        debug_log("reminder parse: dateparser resolved a future instant", "reminders")
        return ParsedWhen(trigger_at=dt)

    debug_log("reminder parse: ambiguous, consulting LLM fallback", "reminders")
    return _llm_fallback(text, cfg, now)


def _try_recurrence_cron(text: str) -> Optional[str]:
    low = text.strip().lower()
    if not _RECURRENCE_RE.search(low):
        return None
    hm = _extract_time(low)
    if hm is None:
        return None
    dow = _extract_dow(low)
    if dow is None:
        return None
    hour, minute = hm
    return f"{minute} {hour} * * {dow}"


def _extract_dow(low: str):
    if any(marker in low for marker in _DAILY_MARKERS):
        return "*"
    for token, num in _WEEKDAYS.items():
        if re.search(r"\b" + re.escape(token) + r"\b", low, re.UNICODE):
            return num
    return None


def _extract_time(low: str):
    match = _TIME_RE.search(low)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    marker = (match.group(3) or "").replace(".", "")
    if marker in ("pm", "μμ") and hour < 12:
        hour += 12
    elif marker in ("am", "πμ") and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _dateparser_parse(text: str, now: datetime, language: Optional[str]):
    try:
        import dateparser
    except ImportError:
        debug_log("dateparser unavailable; routing to LLM fallback", "reminders")
        return None
    langs = ["en", "el"]
    if language and language not in langs:
        langs = [language] + langs
    settings = {
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "RELATIVE_BASE": now,
    }
    try:
        return dateparser.parse(text, languages=langs, settings=settings)
    except Exception as exc:  # dateparser can raise on odd locale input
        debug_log(f"dateparser error (non-fatal): {type(exc).__name__}", "reminders")
        return None


def _llm_fallback(text: str, cfg, now: datetime) -> Optional[ParsedWhen]:
    model = _resolve_model(cfg)
    if not model:
        return None
    system_prompt = (
        "You convert a reminder time phrase into a machine format. Output EXACTLY "
        "one line and nothing else: either an ISO-8601 local datetime "
        "'YYYY-MM-DDTHH:MM:SS' for a one-time reminder, OR a 5-field cron string "
        "for a recurring one, OR the literal NONE if no time is expressed. "
        f"The current local time is {now.isoformat()}."
    )
    # Fence the user text as untrusted data, not instructions.
    user_content = "<<<REMINDER_TIME_PHRASE\n" + text + "\nREMINDER_TIME_PHRASE>>>"
    timeout = float(getattr(cfg, "reminder_parse_timeout_sec", 8.0))
    try:
        raw = call_llm_direct(
            getattr(cfg, "ollama_base_url", ""),
            model,
            system_prompt,
            user_content,
            timeout_sec=timeout,
            thinking=False,
            num_ctx=1024,
            temperature=0.0,
        )
    except Exception as exc:
        debug_log(f"reminder parse LLM fallback failed (non-fatal): {type(exc).__name__}", "reminders")
        return None
    return _interpret_llm_output(raw)


def _interpret_llm_output(raw: Optional[str]) -> Optional[ParsedWhen]:
    if not raw:
        return None
    stripped = _strip_fence(raw).strip()
    if not stripped:
        return None
    first = stripped.splitlines()[0].strip()
    if not first or first.upper() == "NONE":
        return None
    try:
        dt = datetime.fromisoformat(first)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return ParsedWhen(trigger_at=dt)
    except ValueError:
        pass
    if _is_valid_cron(first):
        return ParsedWhen(cron=first)
    return None


def _is_valid_cron(value: str) -> bool:
    if len(value.split()) != 5:
        return False
    try:
        from croniter import croniter
    except ImportError:
        return True  # trust a 5-field shape when croniter isn't installed
    return croniter.is_valid(value)


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped


def _resolve_model(cfg) -> str:
    """Warm small-model chain, inlined to avoid a heavy/circular import.

    Mirrors ``jarvis.reply.engine.resolve_tool_router_model``:
    tool_router_model -> intent_judge_model -> ollama_chat_model.
    """
    for attr in ("tool_router_model", "intent_judge_model", "ollama_chat_model"):
        value = (getattr(cfg, attr, "") or "").strip()
        if value:
            return value
    return ""
