"""Unit tests for the in-process STT backend hot-switch on VoiceListener.

Covers the thread-safe request API and the runtime teardown — the pure
pieces of the swap that don't need a real audio device or Whisper model.
The dispatcher loop itself (run()) drives real backends and is exercised
end-to-end manually; here we lock down the contract its helpers rely on.

Constructed via ``__new__`` so no control-bus port / API server / model is
started — we set only the attributes the switch helpers touch.
"""

import threading
from unittest.mock import MagicMock

from jarvis.listening.listener import VoiceListener


def _bare_listener(backend: str = "whisper") -> VoiceListener:
    listener = VoiceListener.__new__(VoiceListener)
    listener._stt_backend = backend
    listener._switch_event = threading.Event()
    listener._pending_backend = None
    listener._switch_from = None
    listener._consecutive_fast_failures = 0
    listener._wispr_bridge = None
    listener.model = object()
    listener._whisper_backend = "faster-whisper"
    return listener


# ── request_stt_switch ───────────────────────────────────────────────────────


def test_request_switch_schedules_pending_and_sets_event():
    listener = _bare_listener("whisper")
    assert listener.request_stt_switch("wispr") is True
    assert listener._pending_backend == "wispr"
    assert listener._switch_event.is_set()


def test_request_switch_is_case_insensitive():
    listener = _bare_listener("whisper")
    assert listener.request_stt_switch("WISPR") is True
    assert listener._pending_backend == "wispr"


def test_request_switch_rejects_invalid_backend():
    listener = _bare_listener("whisper")
    assert listener.request_stt_switch("banana") is False
    assert listener._pending_backend is None
    assert not listener._switch_event.is_set()


def test_request_switch_same_backend_is_noop():
    listener = _bare_listener("whisper")
    assert listener.request_stt_switch("whisper") is False
    assert not listener._switch_event.is_set()


# ── _teardown_stt_runtime ────────────────────────────────────────────────────


def test_teardown_whisper_releases_model():
    listener = _bare_listener("whisper")
    listener._teardown_stt_runtime("whisper")
    assert listener.model is None
    assert listener._whisper_backend is None


def test_teardown_wispr_stops_and_nulls_bridge():
    listener = _bare_listener("wispr")
    bridge = MagicMock()
    listener._wispr_bridge = bridge
    listener._teardown_stt_runtime("wispr")
    bridge.stop.assert_called_once()
    assert listener._wispr_bridge is None


def test_teardown_never_raises_when_bridge_stop_fails():
    listener = _bare_listener("wispr")
    bridge = MagicMock()
    bridge.stop.side_effect = RuntimeError("boom")
    listener._wispr_bridge = bridge
    # Must not propagate — teardown failing would wedge the dispatcher.
    listener._teardown_stt_runtime("wispr")
    assert listener._wispr_bridge is None
