"""The HUD orb must return to IDLE after a rejected wake (no stuck LISTENING).

On the Wispr path, _on_wispr_wake sets the face to LISTENING but starts NO
thinking tune. When the transcript is then rejected (ambient speech), the
cleanup only called _stop_thinking_tune, whose IDLE reset is guarded by
`tune_player is not None` — None here — so the orb stayed stuck on LISTENING.
A dedicated _set_face_state_idle helper fixes it, while never clobbering the
SPEAKING state mid-reply.
"""

import sys
import types

from unittest.mock import MagicMock


def _install_fake_face(monkeypatch):
    calls = []

    class _JarvisState:
        IDLE = "IDLE"
        LISTENING = "LISTENING"

    class _Mgr:
        def set_state(self, s):
            calls.append(s)

    pkg = types.ModuleType("desktop_app")
    mod = types.ModuleType("desktop_app.face_widget")
    mod.JarvisState = _JarvisState
    mod.get_jarvis_state = lambda: _Mgr()
    monkeypatch.setitem(sys.modules, "desktop_app", pkg)
    monkeypatch.setitem(sys.modules, "desktop_app.face_widget", mod)
    return calls


def _make_listener():
    from jarvis.listening.listener import VoiceListener
    cfg = MagicMock()
    cfg.tune_enabled = False
    return VoiceListener(MagicMock(), cfg, MagicMock(), MagicMock())


def test_set_face_state_idle_resets_to_idle(monkeypatch):
    calls = _install_fake_face(monkeypatch)
    listener = _make_listener()
    listener.tts = None
    listener._set_face_state_idle()
    assert calls == ["IDLE"]


def test_set_face_state_idle_skips_while_speaking(monkeypatch):
    calls = _install_fake_face(monkeypatch)
    listener = _make_listener()
    speaking = MagicMock()
    speaking.is_speaking.return_value = True
    listener.tts = speaking
    listener._set_face_state_idle()
    assert calls == []  # must not clobber the SPEAKING state mid-reply
