"""
Thread-safety tests for the VoiceListener control-bus flags.

`_muted`, `_manual_trigger_active` and `_manual_finalize_requested` are shared
between the control-bus worker thread (`_handle_control_command`) and the audio
loop / `_dispatch_query`. These tests verify that the access is guarded by a
single lock and that the manual-finalize handshake (set -> consume -> clear)
cannot lose or duplicate an update.

We deliberately avoid timing/sleep-based race tests: instead we assert the
structural invariants (a lock exists; the consume path reads-and-clears
atomically and returns the request exactly once) and the observable
single-threaded behaviour (MUTE/UNMUTE toggle `_muted`).
"""

import threading
from unittest.mock import patch, MagicMock

import pytest


def _create_listener():
    """Construct a VoiceListener with mocked heavy dependencies (no run())."""
    with patch("jarvis.listening.listener.FASTER_WHISPER_AVAILABLE", True):
        with patch("jarvis.listening.listener.MLX_WHISPER_AVAILABLE", False):
            with patch("jarvis.listening.listener.WhisperModel"):
                with patch("jarvis.listening.listener.webrtcvad", None):
                    from jarvis.listening.listener import VoiceListener

                    mock_cfg = MagicMock()
                    mock_cfg.sample_rate = 16000
                    mock_cfg.vad_enabled = False
                    mock_cfg.echo_tolerance = 0.3
                    mock_cfg.echo_energy_threshold = 2.0
                    mock_cfg.hot_window_seconds = 3.0
                    mock_cfg.voice_collect_seconds = 2.0
                    mock_cfg.voice_max_collect_seconds = 60.0
                    mock_cfg.tune_enabled = False
                    # Force the legacy whisper branch in _handle_control_command
                    # so MUTE/UNMUTE simply toggle _muted (no bridge calls).
                    mock_cfg.stt_backend = "whisper"

                    listener = VoiceListener(
                        MagicMock(), mock_cfg, MagicMock(), MagicMock()
                    )
                    # Ensure no real Wispr bridge regardless of cfg.
                    listener._stt_backend = "whisper"
                    listener._wispr_bridge = None
                    return listener


class TestControlFlagLock:
    """The shared control-bus flags must be protected by a single lock."""

    def test_control_flags_lock_exists(self):
        """A reentrant-safe Lock guards the shared control-bus flags."""
        listener = _create_listener()
        assert hasattr(listener, "_control_flags_lock")
        # Acquirable and releasable like a threading.Lock.
        assert listener._control_flags_lock.acquire(blocking=False) is True
        listener._control_flags_lock.release()


class TestMuteUnmuteBehaviour:
    """MUTE/UNMUTE toggle the observable mute state."""

    def test_mute_then_unmute(self):
        listener = _create_listener()
        assert listener._muted is False

        assert listener._handle_control_command("MUTE") == "OK MUTED=True"
        assert listener._muted is True

        assert listener._handle_control_command("UNMUTE") == "OK UNMUTED"
        assert listener._muted is False

    def test_mute_toggles_back_off(self):
        """A second MUTE (no manual trigger) flips mute back off."""
        listener = _create_listener()
        listener._handle_control_command("MUTE")
        assert listener._muted is True
        # Not in manual-trigger collection mode, so MUTE toggles.
        assert listener._handle_control_command("MUTE") == "OK MUTED=False"
        assert listener._muted is False


class TestManualFinalizeHandshake:
    """The set -> consume -> clear handshake is atomic and fires once."""

    def test_consume_returns_request_once_and_clears(self):
        listener = _create_listener()
        # Initially nothing pending.
        assert listener._consume_manual_finalize() is False

        # Producer sets the request (as MUTE does during a manual trigger).
        listener._manual_finalize_requested = True

        # First consume sees it; second does not (atomic read-and-clear).
        assert listener._consume_manual_finalize() is True
        assert listener._manual_finalize_requested is False
        assert listener._consume_manual_finalize() is False

    def test_consume_clears_manual_trigger_active(self):
        """Consuming the finalize request also ends manual-trigger mode."""
        listener = _create_listener()
        listener._manual_trigger_active = True
        listener._manual_finalize_requested = True

        assert listener._consume_manual_finalize() is True
        assert listener._manual_trigger_active is False
        assert listener._manual_finalize_requested is False

    def test_mute_during_manual_trigger_sets_finalize(self):
        """MUTE while collecting under a manual trigger requests finalize."""
        listener = _create_listener()
        listener._manual_trigger_active = True
        listener.state_manager = MagicMock()
        listener.state_manager.is_collecting.return_value = True

        result = listener._handle_control_command("MUTE")

        assert result == "OK MUTED=True"
        assert listener._muted is True
        # The request is now pending and consumed exactly once.
        assert listener._consume_manual_finalize() is True
        assert listener._consume_manual_finalize() is False

    def test_concurrent_consume_yields_single_winner(self):
        """Under contention, exactly one consumer observes the request.

        This is a structural check on the read-and-clear, not a timing race:
        we fire many threads at a single pending request and assert the total
        number of True observations is exactly one.
        """
        listener = _create_listener()
        listener._manual_finalize_requested = True

        observations = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            observations.append(listener._consume_manual_finalize())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert observations.count(True) == 1
        assert listener._manual_finalize_requested is False
