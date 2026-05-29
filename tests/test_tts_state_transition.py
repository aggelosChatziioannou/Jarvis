"""Regression tests for TTS → IDLE state transition bug and SYNTHESIZING state.

Before the fix, _notify_speaking_state(False) did nothing, so the popup UI
stayed stuck in "SPEAKING" forever after TTS ended.

With the SYNTHESIZING state addition, the flow is now:
  SYNTHESIZING (when TTS starts synthesis) → SPEAKING (when audio playback starts) → IDLE (when playback ends)

These tests verify that both PiperTTS and ChatterboxTTS correctly implement
this three-phase state machine.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestPublishTtsState:
    """Tests for _publish_tts_state in both TTS implementations."""

    @pytest.fixture
    def fresh_state_manager(self):
        """Provide a clean JarvisStateManager for each test."""
        from desktop_app.face_widget import JarvisStateManager
        mgr = JarvisStateManager()
        with patch("desktop_app.face_widget._jarvis_state_instance", mgr):
            with patch("desktop_app.face_widget._jarvis_state_lock"):
                yield mgr

    @patch("src.jarvis.output.tts.debug_log")
    def test_piper_synthesizing_to_speaking_to_idle(self, _mock_debug, fresh_state_manager):
        """PiperTTS should flow SYNTHESIZING → SPEAKING → IDLE."""
        from src.jarvis.output.tts import PiperTTS
        from desktop_app.face_widget import JarvisState

        tts = PiperTTS(enabled=False)

        tts._publish_tts_state(JarvisState.SYNTHESIZING)
        assert fresh_state_manager.state == JarvisState.SYNTHESIZING

        tts._publish_tts_state(JarvisState.SPEAKING)
        assert fresh_state_manager.state == JarvisState.SPEAKING

        tts._publish_tts_state(JarvisState.IDLE)
        assert fresh_state_manager.state == JarvisState.IDLE

    @patch("src.jarvis.output.tts.debug_log")
    def test_chatterbox_synthesizing_to_speaking_to_idle(self, _mock_debug, fresh_state_manager):
        """ChatterboxTTS should flow SYNTHESIZING → SPEAKING → IDLE."""
        from src.jarvis.output.tts import ChatterboxTTS
        from desktop_app.face_widget import JarvisState

        tts = ChatterboxTTS(enabled=False)

        tts._publish_tts_state(JarvisState.SYNTHESIZING)
        assert fresh_state_manager.state == JarvisState.SYNTHESIZING

        tts._publish_tts_state(JarvisState.SPEAKING)
        assert fresh_state_manager.state == JarvisState.SPEAKING

        tts._publish_tts_state(JarvisState.IDLE)
        assert fresh_state_manager.state == JarvisState.IDLE

    @patch("src.jarvis.output.tts.debug_log")
    def test_piper_respects_listening_state_on_idle(self, _mock_debug, fresh_state_manager):
        """If state is already LISTENING when TTS ends, don't overwrite it."""
        from src.jarvis.output.tts import PiperTTS
        from desktop_app.face_widget import JarvisState

        tts = PiperTTS(enabled=False)

        # User started speaking during pending hot window
        fresh_state_manager.set_state(JarvisState.LISTENING)

        # TTS ends — should NOT overwrite LISTENING
        tts._publish_tts_state(JarvisState.IDLE)
        assert fresh_state_manager.state == JarvisState.LISTENING

    @patch("src.jarvis.output.tts.debug_log")
    def test_chatterbox_respects_thinking_state_on_idle(self, _mock_debug, fresh_state_manager):
        """If state is already THINKING when TTS ends, don't overwrite it."""
        from src.jarvis.output.tts import ChatterboxTTS
        from desktop_app.face_widget import JarvisState

        tts = ChatterboxTTS(enabled=False)

        # Reply engine already set THINKING
        fresh_state_manager.set_state(JarvisState.THINKING)

        # TTS ends — should NOT overwrite THINKING
        tts._publish_tts_state(JarvisState.IDLE)
        assert fresh_state_manager.state == JarvisState.THINKING

    @patch("src.jarvis.output.tts.debug_log")
    def test_piper_idle_from_synthesizing_interrupted(self, _mock_debug, fresh_state_manager):
        """If interrupted during SYNTHESIZING, IDLE should still clear it."""
        from src.jarvis.output.tts import PiperTTS
        from desktop_app.face_widget import JarvisState

        tts = PiperTTS(enabled=False)

        tts._publish_tts_state(JarvisState.SYNTHESIZING)
        assert fresh_state_manager.state == JarvisState.SYNTHESIZING

        # Interrupted before SPEAKING — IDLE should clear SYNTHESIZING
        tts._publish_tts_state(JarvisState.IDLE)
        assert fresh_state_manager.state == JarvisState.IDLE
