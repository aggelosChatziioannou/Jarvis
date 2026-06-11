"""Bare wake word → quick ack + open listening window, NOT a full LLM turn.

Live failure this guards: the user said "Hey Jarvis." and PAUSED for an
acknowledgement (natural assistant etiquette). The bare wake word was
dispatched through the full pipeline (fused intent 2.5s + chat reply) and
Jarvis rambled for ~20 seconds; the actual command, spoken right after the
ramble, arrived with no wake signal active and was dropped on the floor
("Heard: 'Spotify and Spotify in the left monitor.'" → idle, nothing ran).
"""

import time

from jarvis.listening.wake_detection import is_wake_only_utterance
from jarvis.listening.state_manager import StateManager, ListeningState


WAKE = "jarvis"
ALIASES = ["jarvis", "hey jarvis", "τζάρβις"]


class TestIsWakeOnlyUtterance:
    def test_bare_wake_variants_are_wake_only(self):
        for text in [
            "hey jarvis.",
            "jarvis",
            "jarvis?",
            "hey jarvis!",
            "τζάρβις;",
        ]:
            assert is_wake_only_utterance(text, WAKE, ALIASES), text

    def test_wake_plus_command_is_not_wake_only(self):
        for text in [
            "hey jarvis put spotify on the left",
            "jarvis what time is it",
            "τζάρβις βάλε μουσική",
            "hey jarvis. spotify in the left monitor",
        ]:
            assert not is_wake_only_utterance(text, WAKE, ALIASES), text

    def test_no_wake_word_is_not_wake_only(self):
        assert not is_wake_only_utterance("put spotify on the left", WAKE, ALIASES)
        assert not is_wake_only_utterance("", WAKE, ALIASES)


class TestActivateHotWindowNow:
    def test_opens_immediately_with_custom_duration(self):
        sm = StateManager(hot_window_seconds=3.0)
        sm.activate_hot_window_now(duration_sec=0.4)
        assert sm.is_hot_window_active()
        time.sleep(0.8)
        assert not sm.is_hot_window_active()

    def test_does_not_clobber_collecting_state(self):
        sm = StateManager(hot_window_seconds=3.0)
        sm.start_collection("some query")
        sm.activate_hot_window_now(duration_sec=0.4)
        assert sm.get_state() == ListeningState.COLLECTING
