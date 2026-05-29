"""Behaviour tests for reminder delivery.

Delivery is the single seam that touches output: it speaks via core TTS, emits
a tray-toast over stdout IPC, and publishes a HUD event. Tests assert the
observable outputs (the IPC line, the spoken text) and that HUD-publish failure
is non-fatal. ``publish`` is injected to avoid importing the Flask HUD server.
"""
import json

import pytest

from jarvis.reminders.delivery import speak_and_toast, REMINDER_IPC_PREFIX


class FakeTTS:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


class Cfg:
    reminder_speak_on_fire = True


def _ipc_lines(out):
    return [ln for ln in out.splitlines() if ln.startswith(REMINDER_IPC_PREFIX)]


@pytest.mark.unit
def test_emits_tray_toast_ipc_line(capsys):
    speak_and_toast("drink water", "rid-1", Cfg(), tts=None, publish=lambda **k: None)
    lines = _ipc_lines(capsys.readouterr().out)
    assert lines, "expected a __REMINDER__: IPC line"
    payload = json.loads(lines[0][len(REMINDER_IPC_PREFIX):])
    assert payload["type"] == "toast"
    assert payload["id"] == "rid-1"
    assert payload["body"] == "drink water"
    assert payload["title"]


@pytest.mark.unit
def test_speaks_with_reminder_prefix_when_enabled(capsys):
    tts = FakeTTS(enabled=True)
    speak_and_toast("take meds", "rid", Cfg(), tts=tts, publish=lambda **k: None)
    assert tts.spoken and "take meds" in tts.spoken[0]
    assert tts.spoken[0].lower().startswith("reminder")


@pytest.mark.unit
def test_does_not_speak_when_tts_disabled(capsys):
    tts = FakeTTS(enabled=False)
    speak_and_toast("x", "rid", Cfg(), tts=tts, publish=lambda **k: None)
    assert tts.spoken == []


@pytest.mark.unit
def test_does_not_speak_when_config_off(capsys):
    class CfgOff:
        reminder_speak_on_fire = False

    tts = FakeTTS(enabled=True)
    speak_and_toast("x", "rid", CfgOff(), tts=tts, publish=lambda **k: None)
    assert tts.spoken == []


@pytest.mark.unit
def test_publish_failure_is_non_fatal_and_toast_still_emitted(capsys):
    def boom(**kwargs):
        raise RuntimeError("hud down")

    speak_and_toast("x", "rid", Cfg(), tts=None, publish=boom)  # must not raise
    assert _ipc_lines(capsys.readouterr().out)


@pytest.mark.unit
def test_greek_body_is_ascii_safe_on_the_ipc_line(capsys):
    speak_and_toast("πιες νερό", "rid", Cfg(), tts=None, publish=lambda **k: None)
    line = _ipc_lines(capsys.readouterr().out)[0]
    # line must be plain ASCII (escaped) so a cp1252 console can't crash on it
    assert line.encode("ascii")
    payload = json.loads(line[len(REMINDER_IPC_PREFIX):])
    assert payload["body"] == "πιες νερό"


@pytest.mark.unit
def test_default_publish_used_when_publish_omitted(monkeypatch):
    """With no injected publish, delivery routes the HUD event to _default_publish."""
    import jarvis.reminders.delivery as delivery_mod

    seen = {}
    monkeypatch.setattr(delivery_mod, "_default_publish", lambda **fields: seen.update(fields))
    speak_and_toast("ping", "rid-9", Cfg(), tts=None)  # publish omitted -> default path

    assert seen.get("reminderFired", {}).get("id") == "rid-9"
    assert seen["reminderFired"]["text"] == "ping"
