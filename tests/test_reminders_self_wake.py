"""Reminder delivery must pause wake detection while it speaks (self-wake fix).

On the Wispr backend the bridge only learns Jarvis is speaking via TTS playback
callbacks. Reminder delivery spoke with NO callbacks, so its own voice through
the mic could re-trigger the wake word and start capturing ambient audio into
the cloud STT + LLM unbidden. speak_and_toast now brackets the speech with
on_speak_start / on_speak_end hooks (wired in the daemon to the listener's
_set_bridge_speaking) and guarantees the end hook fires even on TTS error.
"""

from types import SimpleNamespace

from jarvis.reminders.delivery import speak_and_toast


def _cfg(speak=True):
    return SimpleNamespace(reminder_speak_on_fire=speak)


def test_speech_is_bracketed_start_speak_end():
    order = []
    tts = SimpleNamespace(enabled=True, speak=lambda text: order.append("speak"))
    speak_and_toast(
        "dentist", "r1", _cfg(), tts, publish=lambda **k: None,
        on_speak_start=lambda: order.append("start"),
        on_speak_end=lambda: order.append("end"),
    )
    assert order == ["start", "speak", "end"]


def test_end_hook_fires_even_if_tts_raises():
    order = []

    def boom(text):
        order.append("speak")
        raise RuntimeError("tts boom")

    tts = SimpleNamespace(enabled=True, speak=boom)
    speak_and_toast(
        "dentist", "r1", _cfg(), tts, publish=lambda **k: None,
        on_speak_start=lambda: order.append("start"),
        on_speak_end=lambda: order.append("end"),
    )
    assert order == ["start", "speak", "end"]  # cleanup guaranteed -> wake never stuck paused


def test_no_hooks_when_speech_disabled():
    order = []
    tts = SimpleNamespace(enabled=True, speak=lambda text: order.append("speak"))
    speak_and_toast(
        "x", "r1", _cfg(speak=False), tts, publish=lambda **k: None,
        on_speak_start=lambda: order.append("start"),
        on_speak_end=lambda: order.append("end"),
    )
    assert order == []  # no speech -> no pause hooks
