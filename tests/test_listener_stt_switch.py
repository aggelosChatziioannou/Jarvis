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


# ── fast-fail revert keeps the user's configured default ────────────────────


def test_fast_fail_revert_is_runtime_only_and_never_rewrites_config(monkeypatch, tmp_path):
    """User directive (2026-06-12): the configured backend is a PREFERENCE —
    every restart must honour it. A backend that fails to start (e.g. Wispr
    Flow app not running at boot) reverts for the SESSION only; persisting the
    revert silently flipped the user's default to whisper forever.

    Observed through the config file itself (via JARVIS_CONFIG_PATH) so the
    test needs no jarvis.daemon import — importing the daemon installs the
    Live-Logs stdout mirror inside the test process and breaks pytest capture.
    """
    import json

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"stt_backend": "wispr"}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_path))

    listener = _bare_listener("wispr")
    listener._should_stop = False
    listener._STT_FAST_FAIL_SEC = 5.0

    calls = {"n": 0}

    def fake_dispatch_once():
        # First call: instant return = startup failure (fast fail).
        # Second call (after the runtime revert): stop the loop.
        calls["n"] += 1
        if calls["n"] >= 2:
            listener._should_stop = True

    listener._dispatch_once = fake_dispatch_once
    listener._teardown_stt_runtime = MagicMock()

    listener.run()

    assert listener._stt_backend == "whisper", "runtime fallback must still happen"
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert persisted["stt_backend"] == "wispr", (
        "a failed start must not rewrite the user's configured default"
    )
