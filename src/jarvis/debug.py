"""Debug logging utilities for Jarvis."""
import sys
import time
from typing import Optional
from .config import load_settings


_last_check_time: float = 0.0
_cached_voice_debug: Optional[bool] = None
_CACHE_TTL_SECONDS: float = 2.0

# State transition tracking
_last_face_state: Optional[str] = None


def _is_debug_enabled() -> bool:
    global _last_check_time, _cached_voice_debug
    now = time.time()
    if _cached_voice_debug is None or (now - _last_check_time) > _CACHE_TTL_SECONDS:
        try:
            _cached_voice_debug = bool(load_settings().voice_debug)
        except Exception:
            _cached_voice_debug = False
        _last_check_time = now
    return bool(_cached_voice_debug)


def info_log(message: str, emoji: str = "") -> None:
    """Always-visible structured log for state changes and summaries (INFO level).

    Args:
        message: The info message to log
        emoji: Optional emoji prefix for visual scanning
    """
    full = f"{emoji} {message}" if emoji else message
    # Print to stderr ONLY. The _StdoutMirror (installed at daemon early-init)
    # tees every printed line to the Live Logs feed exactly once. Calling
    # publish_log() here as well made every line appear TWICE in the feed.
    try:
        print(full, file=sys.stderr, flush=True)
    except Exception:
        pass


def debug_log(message: str, category: str = "debug") -> None:
    """Debug-only logging function for Jarvis internals.

    Only printed when voice_debug is enabled. All verbose internals
    (progress bars, repeated checks, raw data) should use this.

    Args:
        message: The debug message to log
        category: The log category (e.g., "debug", "voice", "echo", "tts", etc.)
    """
    # Errors/crashes are ALWAYS surfaced; other internals only when voice_debug
    # is on. We print to stderr and let the _StdoutMirror publish to the Live
    # Logs feed exactly once. We deliberately do NOT call publish_log() here:
    # doing so (a) duplicated every line in the feed, and (b) leaked all the
    # verbose internals into the feed even when debug was off.
    is_error = category in ("error", "crash")
    if not is_error and not _is_debug_enabled():
        return
    try:
        print(f"[{category}] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


def log_state_transition(new_state: str, reason: str = "") -> None:
    """Log a face-state transition as a single highly-visible flow line.

    Only emits when the state actually changes.  Repeated calls with the
    same state are silently ignored.

    Args:
        new_state: The new face state (e.g. "IDLE", "LISTENING", ...)
        reason: Optional short reason shown in parentheses
    """
    global _last_face_state
    if _last_face_state == new_state:
        return

    state_emojis = {
        "IDLE": "💤",
        "LISTENING": "🎤",
        "THINKING": "🧠",
        "SPEAKING": "🗣️",
        "DICTATING": "📝",
        "DICTATION_PROCESSING": "⚙️",
        "ASLEEP": "😴",
    }
    old_emoji = state_emojis.get(_last_face_state, _last_face_state or "❓")
    new_emoji = state_emojis.get(new_state, new_state)
    msg = f"{old_emoji} {_last_face_state or 'UNKNOWN'} → {new_emoji} {new_state}"
    if reason:
        msg += f" ({reason})"
    info_log(msg)
    _last_face_state = new_state
