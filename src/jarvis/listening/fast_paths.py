"""Fast-path phrase matcher: route common voice commands directly to MCP tools.

When a user query matches a known phrase pattern, skip the intent judge and
chat LLM entirely. The matched MCP tool is invoked directly and its response
is spoken back. This trades a small set of common commands for ~5x latency
reduction (skip 2-3s of LLM thinking).

If no pattern matches, return None — caller falls back to the full pipeline.

Patterns are case-insensitive and unicode-aware; covers Greek + English.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Pattern, Tuple


@dataclass(frozen=True)
class FastPathMatch:
    """Result of a successful fast-path match.

    Attributes:
        mcp_server / tool_name / arguments: MCP call target.
        response_override: If set, speak this string instead of waiting for
            the MCP's response — the MCP call runs in a background thread so
            the spoken acknowledgment is instant. Use for "action" commands
            (next song, pause) where the user doesn't need dynamic info.
        action_only: True when this command's effect is the action itself
            (skip, pause, volume) and a short cached ack suffices.
    """
    mcp_server: str
    tool_name: str
    arguments: Dict[str, Any]
    response_override: Optional[str] = None
    action_only: bool = False


_PatternEntry = Tuple[Pattern[str], str, str, Dict[str, Any], Optional[str], bool, Optional[str]]
_PATTERNS: List[_PatternEntry] = []


def _register(
    pattern: str,
    server: str,
    tool: str,
    args: Optional[Dict[str, Any]] = None,
    response_override: Optional[str] = None,
    action_only: bool = False,
    capture_arg: Optional[str] = None,
) -> None:
    """Compile and register a fast-path pattern. Earlier entries match first.

    When `response_override` is set, the listener plays that exact string
    (ideally pre-cached) instead of waiting on the MCP's reply, and the MCP
    call is dispatched in a background thread.

    When `capture_arg` is set, the regex's first capture group is extracted
    and bound to that argument name in the MCP call. Use for commands like
    "play [song name]" where the variable part feeds the tool.
    """
    _PATTERNS.append((
        re.compile(pattern, re.IGNORECASE | re.UNICODE),
        server, tool, args or {}, response_override,
        action_only or response_override is not None,
        capture_arg,
    ))


# ---------------------- Local (no MCP roundtrip) ----------------------
# `_local` is a pseudo-server: the listener's _try_fast_path detects it and
# computes the response in-process, bypassing the LLM entirely. Used for
# trivial dynamic answers (current time, today's date) where the full
# pipeline (intent judge → router → chat LLM) is pure overhead.

# Time (now)
_register(r"^(τι\s+ώρα|τι\s+ωρα)(\s+είναι|\s+ειναι)?\s*$", "_local", "time_now")
_register(r"^what(?:'?s|\s+is)?\s+the\s+time\s*$", "_local", "time_now")
_register(r"^what\s+time\s+is\s+it\s*$", "_local", "time_now")
_register(r"^(?:tell\s+me\s+)?the\s+time\s*$", "_local", "time_now")

# Date (today)
_register(r"^(τι\s+μέρα|τι\s+μερα|τι\s+ημερομηνία|τι\s+ημερομηνια)(\s+είναι|\s+ειναι|\s+έχουμε|\s+εχουμε)?\s*$", "_local", "date_today")
_register(r"^what(?:'?s|\s+is)?\s+(?:today'?s\s+)?(?:the\s+)?date\s*$", "_local", "date_today")
_register(r"^what\s+day\s+is\s+(?:it|today)\s*$", "_local", "date_today")

# Stop (when not already speaking — already handled mid-TTS by is_stop_command,
# but cold-start "stop" would otherwise grind through the full pipeline). Use
# response_override so it acks instantly and does nothing else.
_register(r"^(σταμάτα|σταματα|σώπα|σωπα)\s*$", "_local", "noop", response_override="OK.")
_register(r"^(stop|cancel|nevermind|never\s+mind|forget\s+it)\s*$", "_local", "noop", response_override="OK.")


# ---------------------- Spotify (Greek + English) ----------------------
# Action commands run in background thread + speak cached short ack.
# Query commands wait for MCP and speak dynamic response.

# Next track (ACTION)
_register(r"\b(επόμενο|επομενο|παρακάτω|παρακατω|αλλαξε|άλλαξε)\s*(τραγού?δι|κομμάτι|κομματι)?\b", "spotify", "next_track", response_override="Skipped.")
_register(r"\b(next|skip|skip\s+this)(\s+(song|track|one))?\b", "spotify", "next_track", response_override="Skipped.")
_register(r"\b(βαριέμαι\s+αυτό|βαριεμαι\s+αυτο)\b", "spotify", "next_track", response_override="Skipped.")
_register(r"\bχέσε\s+το\b", "spotify", "next_track", response_override="Skipped.")

# Previous track (ACTION)
_register(r"\b(προηγούμενο|προηγουμενο|πίσω)\s*(τραγού?δι|κομμάτι|κομματι)?\b", "spotify", "previous_track", response_override="Going back.")
_register(r"\b(πάμε|παμε)\s+πίσω\b", "spotify", "previous_track", response_override="Going back.")
_register(r"\b(previous|go back|back one track|previous\s+(song|track))\b", "spotify", "previous_track", response_override="Going back.")

# Pause (ACTION)
_register(r"\b(παύση|παυση|σταμάτα\s+(τη\s+)?μουσική|σταματα\s+τη\s+μουσικη|κανε\s+παυση)\b", "spotify", "play_pause", response_override="Paused.")
_register(r"\b(pause|stop\s+the\s+music|pause\s+music)\b", "spotify", "play_pause", response_override="Paused.")

# Resume (ACTION) — anchor at end so "παίξε X" falls through to search_and_play
_register(r"\b(συνέχισε|συνεχισε|ξεκίνα|ξεκινα|παίξε|παιξε)(\s+(τη\s+)?(μουσική|μουσικη|τραγού?δι))?\s*$", "spotify", "play_pause", response_override="Resuming.")
_register(r"\b(resume|continue\s+playing|play\s+music|unpause)\b", "spotify", "play_pause", response_override="Resuming.")

# Volume (ACTION — but with dynamic argument, so we strip the number from query and call set_volume)
# Note: real arg extraction requires regex groups; here we use static set_volume(50) as a stop-gap.
# Better integration would parse the number. For now, separate handlers for common levels.
_register(r"\b(ηχεία\s+)?(πιο\s+)?δυνατά\b", "spotify", "set_volume", {"percent": 70}, response_override="Volume up.")
_register(r"\b(ηχεία\s+)?(πιο\s+)?σιγά\b", "spotify", "set_volume", {"percent": 30}, response_override="Volume down.")
_register(r"\bvolume\s+up\b", "spotify", "set_volume", {"percent": 70}, response_override="Volume up.")
_register(r"\bvolume\s+down\b", "spotify", "set_volume", {"percent": 30}, response_override="Volume down.")

# What's playing (QUERY — full dynamic response)
_register(r"\b(τι\s+παίζει|τι\s+παιζει|τι\s+ακούω|τι\s+ακουω|ποιο\s+τραγού?δι|ποιο\s+είναι\s+αυτό)\b", "spotify", "get_current_track")
_register(r"\bwhat'?s\s+(playing|this\s+song)\b", "spotify", "get_current_track")
_register(r"\bcurrent\s+(song|track)\b", "spotify", "get_current_track")

# Play [song/artist/album] (ACTION with dynamic capture)
# Triggers search_and_play with the captured query. Patterns ordered most→
# least specific so "play some pop music" doesn't accidentally swallow the
# "music" keyword as the search query.
_register(r"\b(?:play|παίξε|παιξε|βάλε|βαλε)\s+(?:το\s+τραγού?δι\s+|the\s+song\s+|some\s+|κάτι\s+|καποιο\s+)?(.{2,80}?)(?:\s+(?:στο\s+spotify|on\s+spotify))?$",
          "spotify", "search_and_play",
          response_override="Got it.", capture_arg="query")

# ---------------------- Weather ----------------------

# Current weather
_register(r"\b(τι\s+καιρό|τι\s+καιρο|καιρός|καιρος)(\s+κάνει|\s+κανει|\s+έχει|\s+εχει)?\b", "weather", "get_current_weather")
_register(r"\b(what'?s|what is|tell me)\s+the\s+weather\b", "weather", "get_current_weather")
_register(r"\bcurrent\s+weather\b", "weather", "get_current_weather")

# Forecast
_register(r"\b(πρόγνωση|προγνωση|πρόβλεψη|προβλεψη)(\s+καιρού|\s+καιρου)?\b", "weather", "get_forecast")
_register(r"\b(weather\s+)?forecast\b", "weather", "get_forecast")

# ---------------------- Gmail ----------------------

# Unread count
_register(r"\b(πόσα|ποσα).{0,20}(νέα|νεα|αδιάβαστα|αδιαβαστα)\s+(emails?|mails?|μηνύματα|μηνυματα)\b", "gmail", "get_unread_count")
_register(r"\bhow\s+many\s+(unread|new)\s+emails?\b", "gmail", "get_unread_count")
_register(r"\bunread\s+(emails?\s+)?count\b", "gmail", "get_unread_count")

# Last email
_register(r"\b(τελευταί[οαό]|τελευταιο)\s+(emails?|mails?|μήνυμα|μηνυμα)\b", "gmail", "read_email", {"message_index": 1})
_register(r"\b(διάβασε|διαβασε)\s+(μου\s+)?(το\s+)?(τελευταί[οαό]\s+)?(emails?|mails?|μήνυμα|μηνυμα)\b", "gmail", "read_email", {"message_index": 1})
_register(r"\b(read|tell\s+me)\s+(my\s+)?(last|latest|most\s+recent)\s+email\b", "gmail", "read_email", {"message_index": 1})

# Recent emails list
_register(r"\b(δείξε|δειξε)\s+(μου\s+)?(τα\s+)?(πρόσφατα|προσφατα|τελευταία|τελευταια)\s+(email|mail)\b", "gmail", "list_recent_emails", {"count": 5})
_register(r"\b(list|show)\s+(my\s+)?(recent|last|latest)\s+emails?\b", "gmail", "list_recent_emails", {"count": 5})


# ---------------------- App Launcher (Greek + English, ACTION) ----------------------

# Spotify open/close
_register(r"\b(άνοιξε|ανοιξε|βαλε|βάλε)\s+(το\s+)?spotify\b", "apps", "open_app", {"name": "spotify"}, response_override="Opening Spotify.")
_register(r"\bopen\s+spotify\b", "apps", "open_app", {"name": "spotify"}, response_override="Opening Spotify.")
_register(r"\b(κλείσε|κλεισε)\s+(το\s+)?spotify\b", "apps", "close_app", {"name": "spotify"}, response_override="Closing Spotify.")
_register(r"\bclose\s+spotify\b", "apps", "close_app", {"name": "spotify"}, response_override="Closing Spotify.")

# Chrome
_register(r"\b(άνοιξε|ανοιξε)\s+(το\s+)?(google\s+)?chrome\b", "apps", "open_app", {"name": "chrome"}, response_override="Opening Chrome.")
_register(r"\bopen\s+chrome\b", "apps", "open_app", {"name": "chrome"}, response_override="Opening Chrome.")
_register(r"\b(κλείσε|κλεισε)\s+(το\s+)?chrome\b", "apps", "close_app", {"name": "chrome"}, response_override="Closing Chrome.")
_register(r"\bclose\s+chrome\b", "apps", "close_app", {"name": "chrome"}, response_override="Closing Chrome.")

# VS Code
_register(r"\b(άνοιξε|ανοιξε)\s+(το\s+)?(vs\s*code|visual\s+studio|code)\b", "apps", "open_app", {"name": "vscode"}, response_override="Opening VS Code.")
_register(r"\bopen\s+(vs\s*code|visual\s+studio|code)\b", "apps", "open_app", {"name": "vscode"}, response_override="Opening VS Code.")

# Discord
_register(r"\b(άνοιξε|ανοιξε)\s+(το\s+)?discord\b", "apps", "open_app", {"name": "discord"}, response_override="Opening Discord.")
_register(r"\bopen\s+discord\b", "apps", "open_app", {"name": "discord"}, response_override="Opening Discord.")

# File explorer
_register(r"\b(άνοιξε|ανοιξε)\s+(τον\s+)?(εξερευνητή|εξερευνητη|files|αρχεία|αρχεια)\b", "apps", "open_app", {"name": "explorer"}, response_override="Opening Explorer.")
_register(r"\bopen\s+(file\s+)?explorer\b", "apps", "open_app", {"name": "explorer"}, response_override="Opening Explorer.")

# Terminal / PowerShell
_register(r"\b(άνοιξε|ανοιξε)\s+(το\s+)?(terminal|powershell|τερματικό|τερματικο)\b", "apps", "open_app", {"name": "terminal"}, response_override="Opening Terminal.")
_register(r"\bopen\s+(terminal|powershell)\b", "apps", "open_app", {"name": "terminal"}, response_override="Opening Terminal.")

# Calculator
_register(r"\b(άνοιξε|ανοιξε)\s+(το\s+)?(αριθμομηχανή|αριθμομηχανη|calculator)\b", "apps", "open_app", {"name": "calculator"}, response_override="Opening Calculator.")
_register(r"\bopen\s+calculator\b", "apps", "open_app", {"name": "calculator"}, response_override="Opening Calculator.")

# Generic "what apps are running"
_register(r"\b(τι\s+)?(apps?|εφαρμογές|εφαρμογες)\s+(τρέχ\w+|τρεχ\w+|running)\b", "apps", "list_open_apps")
_register(r"\bwhat\s+apps\s+are\s+running\b", "apps", "list_open_apps")


# ---------------------- Browser (Greek + English) ----------------------

# Close browser (ACTION)
_register(r"\b(κλείσε|κλεισε)\s+(τον\s+)?(browser|περιηγητή|περιηγητη)\b", "browser", "close_browser", response_override="Browser closed.")
_register(r"\bclose\s+(the\s+)?browser\b", "browser", "close_browser", response_override="Browser closed.")


# ---------------------- Notes & Reminders (Greek + English) ----------------------

# List recent notes (QUERY)
_register(r"\b(δείξε|δειξε)\s+(μου\s+)?(τις\s+)?(σημειώσεις|σημειωσεις|notes)\b", "notes", "list_notes", {"limit": 5})
_register(r"\b(list|show)\s+(my\s+)?notes\b", "notes", "list_notes", {"limit": 5})

# List due reminders
_register(r"\b(υπενθυμίσεις|υπενθυμισεις|reminders)\s+(due|σήμερα|σημερα)?\b", "notes", "list_due_reminders")
_register(r"\b(any\s+)?(due\s+)?reminders?\b", "notes", "list_due_reminders")

# List upcoming
_register(r"\b(επόμενες|επομενες)\s+(υπενθυμίσεις|υπενθυμισεις)\b", "notes", "list_upcoming_reminders")
_register(r"\bupcoming\s+reminders?\b", "notes", "list_upcoming_reminders")


# ---------------------- Calendar (Greek + English) ----------------------

# Today's schedule
_register(r"\b(τι\s+έχω\s+σήμερα|τι\s+εχω\s+σημερα|πρόγραμμα\s+σήμερα|προγραμμα\s+σημερα)\b", "calendar", "list_events_today")
_register(r"\bwhat'?s\s+on\s+my\s+schedule\s+(today)?\b", "calendar", "list_events_today")
_register(r"\bevents?\s+today\b", "calendar", "list_events_today")

# Upcoming
_register(r"\b(τι\s+έχω|τι\s+εχω)\s+(αυτή\s+τη\s+βδομάδα|αυτη\s+τη\s+βδομαδα|αύριο|αυριο)\b", "calendar", "list_events_upcoming", {"days": 7})
_register(r"\bupcoming\s+events?\b", "calendar", "list_events_upcoming", {"days": 7})
_register(r"\bevents?\s+(this\s+)?week\b", "calendar", "list_events_upcoming", {"days": 7})


# Window-placement commands must reach the tool router (manageWindow), not
# this keyword layer: "βάλε το spotify στην αριστερή οθόνη" is an arrangement
# command, but the "βάλε X" music catch-all (and the bare app-launch
# patterns) would swallow it and play a song called "spotify στην αριστερή
# οθόνη". Skipping the WHOLE layer is safe — the only cost is the smarter
# (slower) router answering instead. This file is already an explicitly
# EL+EN pattern layer, so the hint list lives within that design.
_PLACEMENT_HINT = re.compile(
    r"οθόν|οθον|παράθυρ|παραθυρ|screen|monitor|\bwindow|split|"
    r"αριστερ|δεξι|\bleft\b|\bright\b|maximi[sz]e|minimi[sz]e",
    re.IGNORECASE,
)


def match(query: str) -> Optional[FastPathMatch]:
    """Try to match a query against registered fast-path patterns.

    Returns the first matching FastPathMatch, or None if no patterns match.
    """
    if not query or not query.strip():
        return None
    cleaned = re.sub(r"[?!.,;:·]+$", "", query.strip())
    if _PLACEMENT_HINT.search(cleaned):
        return None
    for pattern, server, tool, args, response_override, action_only, capture_arg in _PATTERNS:
        m = pattern.search(cleaned)
        if m:
            resolved_args = dict(args)
            if capture_arg and m.groups():
                captured = (m.group(1) or "").strip()
                if captured:
                    resolved_args[capture_arg] = captured
                else:
                    # Empty capture — skip this pattern, try next.
                    continue
            return FastPathMatch(
                mcp_server=server,
                tool_name=tool,
                arguments=resolved_args,
                response_override=response_override,
                action_only=action_only,
            )
    return None


def extract_mcp_text(result: Any) -> str:
    """Extract a plain-text response from an MCP tool call result.

    MCP responses come as a list of Content objects with `text` attributes,
    or as dicts with 'content' lists. Be defensive about the shape.
    """
    if result is None:
        return ""
    # mcp SDK CallToolResult has .content list
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    if content is None:
        return str(result)
    parts: List[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is None and isinstance(item, dict):
            text = item.get("text")
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip() if parts else str(result)
