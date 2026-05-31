"""Behavioural tests for the live Wispr-Flow listener path.

Covers three behaviours of ``VoiceListener``:

L1 — ``_dispatch_query`` forwards the pre-computed fused tools/plan
     (stashed by the Tier-2 intent cascade) to ``run_reply_engine`` so the
     engine can skip its internal router + planner, then clears them.

L2 — ``_on_wispr_dictation_end(captured=False)`` stops a stuck thinking
     tune (and resets the face) when a dictation produced no transcript;
     ``captured=True`` keeps the current no-op behaviour.

L3 — a failed (clipboard-timeout) dictation surfaces a visible notice
     instead of failing silently.
"""

from unittest.mock import patch, MagicMock

import pytest


def _create_mock_config(**kwargs):
    """Minimal config mock for constructing a VoiceListener in tests."""
    mock_cfg = MagicMock()
    mock_cfg.whisper_model = kwargs.get("whisper_model", "small")
    mock_cfg.whisper_device = kwargs.get("whisper_device", "auto")
    mock_cfg.whisper_compute_type = kwargs.get("whisper_compute_type", "int8")
    mock_cfg.whisper_backend = kwargs.get("whisper_backend", "faster-whisper")
    mock_cfg.sample_rate = kwargs.get("sample_rate", 16000)
    mock_cfg.vad_enabled = kwargs.get("vad_enabled", True)
    mock_cfg.vad_aggressiveness = kwargs.get("vad_aggressiveness", 2)
    mock_cfg.echo_tolerance = kwargs.get("echo_tolerance", 0.3)
    mock_cfg.echo_energy_threshold = kwargs.get("echo_energy_threshold", 2.0)
    mock_cfg.hot_window_seconds = kwargs.get("hot_window_seconds", 3.0)
    mock_cfg.voice_collect_seconds = kwargs.get("voice_collect_seconds", 2.0)
    mock_cfg.voice_max_collect_seconds = kwargs.get("voice_max_collect_seconds", 60.0)
    mock_cfg.voice_device = kwargs.get("voice_device", None)
    mock_cfg.voice_debug = kwargs.get("voice_debug", False)
    mock_cfg.tune_enabled = kwargs.get("tune_enabled", False)
    return mock_cfg


def _make_listener():
    """Construct a VoiceListener without loading any audio/model backend."""
    from jarvis.listening.listener import VoiceListener

    db = MagicMock()
    cfg = _create_mock_config()
    tts = MagicMock()
    dialogue_memory = MagicMock()
    return VoiceListener(db, cfg, tts, dialogue_memory)


class _StubTunePlayer:
    """Stub thinking-tune player that records whether stop_tune was called."""

    def __init__(self, playing: bool = True):
        self._playing = playing
        self.stop_called = False

    def is_playing(self) -> bool:
        return self._playing

    def stop_tune(self) -> None:
        self.stop_called = True
        self._playing = False


# ── L1: forward + clear the pre-computed fused tools/plan ────────────────────


class TestDispatchForwardsFusedToolsAndPlan:
    def test_dispatch_forwards_fused_tools_plan_then_clears(self):
        """`_dispatch_query` passes the stashed fused tools/plan to the engine
        and clears them afterwards so the next query starts clean."""
        listener = _make_listener()

        # Isolate the dispatch: no easter egg, no fast-path, no audio buffers,
        # and no TTS branch (engine returns None).
        listener._try_easter_egg_daddys_home = lambda q: False
        listener._try_fast_path = lambda q: None
        listener._clear_audio_buffers = lambda: None
        listener._stop_thinking_tune = lambda: None
        listener.tts = None

        # Sentinels stashed by the Tier-2 cascade.
        tools_sentinel = [{"name": "webSearch", "arguments": {"query": "x"}}]
        plan_sentinel = ["Search the web.", "Reply to the user."]
        listener._last_fused_tools = tools_sentinel
        listener._last_fused_plan = plan_sentinel

        captured = {}

        def _fake_engine(*args, **kwargs):
            captured["kwargs"] = kwargs
            return None

        # The listener imports run_reply_engine lazily from this module.
        with patch("jarvis.reply.engine.run_reply_engine", _fake_engine):
            listener._dispatch_query("hello")

        # The stashed fused tools/plan reach the engine as the documented
        # kwargs, so it can skip its internal router + planner.
        assert captured["kwargs"].get("fused_tools") is tools_sentinel
        assert captured["kwargs"].get("fused_plan") is plan_sentinel
        # And they are cleared after dispatch so the values don't leak into
        # the next query (which may have no fused intent).
        assert not listener._last_fused_tools
        assert not listener._last_fused_plan


# ── L1b: thinking tune is a PROCESSING indicator, not a LISTENING one ────────


class TestThinkingTuneBoundToProcessing:
    """The 'thinking/σκέφτομαι' tune must play only while the model is
    processing the query — NOT while the user is still speaking (listening).
    On the Wispr path it used to start at wake time."""

    def test_wispr_wake_does_not_start_tune(self):
        listener = _make_listener()
        starts = []
        listener._start_thinking_tune = lambda: starts.append(1)
        faces = []
        listener._set_face_state_listening = lambda: faces.append(1)

        listener._on_wispr_wake()

        assert starts == []      # tune NOT started during listening
        assert faces == [1]      # but the face/popup still shows LISTENING

    def test_dispatch_query_starts_tune_at_processing(self):
        listener = _make_listener()
        listener._try_easter_egg_daddys_home = lambda q: False
        listener._try_fast_path = lambda q: None
        listener._clear_audio_buffers = lambda: None
        listener._stop_thinking_tune = lambda: None
        listener.tts = None
        starts = []
        listener._start_thinking_tune = lambda: starts.append(1)

        with patch("jarvis.reply.engine.run_reply_engine", lambda *a, **k: None):
            listener._dispatch_query("what time is it")

        assert starts and starts[0] == 1   # tune starts when processing begins


# ── L1c: STOP button must abort the Wispr side too ───────────────────────────


class TestStopButtonAbortsWispr:
    """reset_everything (the STOP entry point) must cancel the Wispr side:
    stop recording and discard any in-flight transcript, not just the LLM/TTS."""

    def test_reset_everything_aborts_wispr_bridge(self):
        listener = _make_listener()
        bridge = MagicMock()
        listener._wispr_bridge = bridge
        listener.tts = None
        listener._clear_audio_buffers = lambda: None
        listener._stop_thinking_tune = lambda: None

        listener.reset_everything()

        bridge.abort.assert_called_once()


# ── L2: failed dictation must not leave the tune/face stuck ──────────────────


class TestWisprDictationEndStopsStuckTune:
    def test_failed_dictation_stops_thinking_tune(self):
        """`captured=False` (clipboard timeout) stops the active thinking tune."""
        listener = _make_listener()
        stub = _StubTunePlayer(playing=True)
        listener._tune_player = stub

        listener._on_wispr_dictation_end(captured=False)

        assert stub.stop_called is True
        # The tune is fully torn down (stop also resets the face to IDLE).
        assert listener._tune_player is None

    def test_successful_dictation_does_not_stop_tune(self):
        """`captured=True` keeps the current no-op: the transcript path owns state."""
        listener = _make_listener()
        stub = _StubTunePlayer(playing=True)
        listener._tune_player = stub

        listener._on_wispr_dictation_end(captured=True)

        assert stub.stop_called is False
        assert listener._tune_player is stub

    def test_default_is_captured_true(self):
        """Calling with no argument keeps any pre-existing caller safe (no-op)."""
        listener = _make_listener()
        stub = _StubTunePlayer(playing=True)
        listener._tune_player = stub

        listener._on_wispr_dictation_end()

        assert stub.stop_called is False
        assert listener._tune_player is stub


# ── L3: do not fail silently on clipboard timeout ───────────────────────────


class TestWisprDictationEndSurfacesFailure:
    def test_failed_dictation_prints_notice(self, capsys):
        """A clipboard-timeout dictation prints a visible notice to the user."""
        listener = _make_listener()
        listener._tune_player = _StubTunePlayer(playing=True)

        listener._on_wispr_dictation_end(captured=False)

        out = capsys.readouterr().out
        assert "🔇" in out
        assert "transcript" in out.lower()

    def test_failed_dictation_does_not_speak(self, capsys):
        """The failure notice is logged/printed but NOT spoken (avoid noise)."""
        listener = _make_listener()
        listener.tts = MagicMock()
        listener.tts.enabled = True
        listener._tune_player = _StubTunePlayer(playing=True)

        listener._on_wispr_dictation_end(captured=False)

        listener.tts.speak.assert_not_called()

    def test_successful_dictation_prints_no_notice(self, capsys):
        """A successful dictation prints no failure notice."""
        listener = _make_listener()
        listener._tune_player = _StubTunePlayer(playing=True)

        listener._on_wispr_dictation_end(captured=True)

        out = capsys.readouterr().out
        assert "🔇" not in out
