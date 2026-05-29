"""VoiceListener.reconnect_audio: route a Core Audio device change to the mic.

It delegates to the Wispr bridge (the only backend owning a wake-mic stream),
is a no-op in whisper mode (no bridge), and is fail-open. Exercised through the
UNBOUND method on a lightweight stand-in so we avoid constructing the full
VoiceListener thread (heavy: models, control bus, etc.).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from jarvis.listening.listener import VoiceListener


def test_reconnect_audio_delegates_to_bridge():
    bridge = MagicMock()
    bridge.reconnect.return_value = True
    fake = SimpleNamespace(_wispr_bridge=bridge)

    assert VoiceListener.reconnect_audio(fake) is True
    bridge.reconnect.assert_called_once_with()


def test_reconnect_audio_noop_without_bridge():
    fake = SimpleNamespace(_wispr_bridge=None)
    assert VoiceListener.reconnect_audio(fake) is False


def test_reconnect_audio_fail_open_when_bridge_raises():
    bridge = MagicMock()
    bridge.reconnect.side_effect = OSError("device busy")
    fake = SimpleNamespace(_wispr_bridge=bridge)

    assert VoiceListener.reconnect_audio(fake) is False  # no raise
