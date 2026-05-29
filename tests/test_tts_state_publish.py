"""TTS phase -> React HUD state publishing.

Regression: PiperTTS (the default engine) used the old `desktop_app.face_widget`
path with an enum-vs-string comparison, so it never published `speaking`/`idle`
to the React HUD -> the floating widget got stuck on PROCESSING. Both engines
must publish through the QObject-free `api_server.publish_state` path.
"""
import tempfile

import jarvis.output.tts as tts
from jarvis import api_server


def test_react_state_helper_maps_and_publishes(monkeypatch):
    calls = []
    monkeypatch.setattr(api_server, "publish_state", lambda **kw: calls.append(kw))
    monkeypatch.setattr(tts, "_JARVIS_STATE_FILE", tempfile.mktemp(prefix="jstate_"))

    tts._publish_tts_react_state("synthesizing")
    tts._publish_tts_react_state("speaking")
    tts._publish_tts_react_state("idle")

    assert {"state": "thinking"} in calls   # synthesizing -> thinking (PROCESSING)
    assert {"state": "speaking"} in calls    # the bug: this was never published by Piper
    assert {"state": "idle"} in calls


def test_helper_accepts_enum_value(monkeypatch):
    """The helper must accept both a plain string and an object with `.value`."""
    calls = []
    monkeypatch.setattr(api_server, "publish_state", lambda **kw: calls.append(kw))
    monkeypatch.setattr(tts, "_JARVIS_STATE_FILE", tempfile.mktemp(prefix="jstate_"))

    class _FakeEnum:
        value = "speaking"

    tts._publish_tts_react_state(_FakeEnum())
    assert {"state": "speaking"} in calls


def test_piper_publish_state_delegates_to_helper(monkeypatch):
    seen = []
    monkeypatch.setattr(tts, "_publish_tts_react_state", lambda s: seen.append(s))
    # Body must not depend on `self`; passing None proves it delegates cleanly.
    tts.PiperTTS._publish_tts_state(None, "speaking")
    assert seen == ["speaking"]


def test_chatterbox_publish_state_delegates_to_helper(monkeypatch):
    seen = []
    monkeypatch.setattr(tts, "_publish_tts_react_state", lambda s: seen.append(s))
    tts.ChatterboxTTS._publish_tts_state(None, "speaking")
    assert seen == ["speaking"]
