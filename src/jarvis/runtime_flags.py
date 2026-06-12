"""Process-wide runtime flags shared across daemon / listener / API server.

Deliberately dependency-free (no jarvis imports) so any module can consult
them without import cycles. These are RUNTIME state, not configuration:
``brain_paused`` intentionally resets to False on every daemon start — a
restart must always bring the assistant back fully operational (leaving it
silently brainless after a reboot reads as "Jarvis is broken").
"""

from __future__ import annotations

_brain_paused: bool = False


def is_brain_paused() -> bool:
    """True while the user has flushed VRAM from the console (gaming mode).

    While paused, no LLM call may be issued anywhere in the process — the
    voice pipeline answers with a canned notice and background LLM jobs skip
    their cycle. CPU-only features (wake word, TTS, reminders firing,
    dictation via cloud STT) keep working.
    """
    return _brain_paused


def set_brain_paused(paused: bool) -> None:
    global _brain_paused
    _brain_paused = bool(paused)
