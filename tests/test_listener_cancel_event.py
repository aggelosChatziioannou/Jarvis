"""Behavioural tests for STOP/barge-in cancel-event wiring in the listener.

``reset_everything()`` sets ``self._llm_cancel_event``; ``_dispatch_query``
must (1) CLEAR that event immediately before invoking ``run_reply_engine`` so
a stale STOP from a previous turn cannot abort this fresh reply, and (2) pass
the event to the engine as ``cancel_event``. When the engine returns the
no-speak sentinel (empty string), the listener must NOT call ``tts.speak``.
"""

from unittest.mock import patch, MagicMock


def _create_mock_config(**kwargs):
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


def _isolate_dispatch(listener):
    """Strip out the easter-egg / fast-path / audio side effects so the test
    drives only the run_reply_engine call site."""
    listener._try_easter_egg_daddys_home = lambda q: False
    listener._try_fast_path = lambda q: None
    listener._clear_audio_buffers = lambda: None
    listener._stop_thinking_tune = lambda: None
    listener._last_fused_tools = None
    listener._last_fused_plan = None


def test_dispatch_clears_then_passes_cancel_event():
    """`_dispatch_query` clears the cancel event BEFORE calling the engine and
    passes the same event instance as ``cancel_event``."""
    listener = _make_listener()
    _isolate_dispatch(listener)
    listener.tts = None  # engine returns None → no TTS branch

    # A stale STOP from a previous turn: the event starts set.
    listener._llm_cancel_event.set()

    captured = {}

    def _fake_engine(*args, **kwargs):
        # Snapshot the event's state AT the moment the engine is invoked.
        captured["cancel_event"] = kwargs.get("cancel_event")
        captured["was_set_at_call"] = kwargs.get("cancel_event").is_set()
        return None

    with patch("jarvis.reply.engine.run_reply_engine", _fake_engine):
        listener._dispatch_query("hello")

    # Same event instance is threaded through.
    assert captured["cancel_event"] is listener._llm_cancel_event
    # And it was CLEARED before the engine ran (stale STOP discarded).
    assert captured["was_set_at_call"] is False, (
        "The cancel event must be cleared before run_reply_engine is invoked "
        "so a stale STOP from a previous turn cannot abort this fresh reply"
    )


def test_dispatch_does_not_speak_on_cancel_sentinel():
    """When the engine returns the no-speak sentinel (empty string), the
    listener must not call tts.speak."""
    listener = _make_listener()
    _isolate_dispatch(listener)
    listener.tts = MagicMock()
    listener.tts.enabled = True

    def _fake_engine(*args, **kwargs):
        return ""  # cancellation sentinel

    with patch("jarvis.reply.engine.run_reply_engine", _fake_engine):
        listener._dispatch_query("hello")

    listener.tts.speak.assert_not_called()


def test_dispatch_speaks_normal_reply():
    """Sanity check: a normal non-empty reply IS spoken (the guard only
    suppresses falsy/sentinel returns)."""
    listener = _make_listener()
    _isolate_dispatch(listener)
    listener.tts = MagicMock()
    listener.tts.enabled = True
    # track_tts_start / echo plumbing are noisy; stub the bits the TTS branch
    # touches so the test stays focused on the speak() decision.
    listener.track_tts_start = lambda text: None
    listener._set_bridge_speaking = lambda flag: None
    listener._on_playback_ended = lambda *a, **k: None
    listener.echo_detector = None

    def _fake_engine(*args, **kwargs):
        return "It's sunny in London."

    with patch("jarvis.reply.engine.run_reply_engine", _fake_engine):
        listener._dispatch_query("weather?")

    listener.tts.speak.assert_called_once()
    spoken = listener.tts.speak.call_args.args[0]
    assert spoken == "It's sunny in London."
