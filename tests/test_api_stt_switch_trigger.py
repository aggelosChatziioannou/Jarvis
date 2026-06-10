"""PATCH /api/config must hot-switch the STT backend when (and only when)
``stt_backend`` actually changes.

The endpoint fires the switch on a background thread (so the HTTP call
returns immediately), so the change-case test waits on an Event the fake
sets. ``request_stt_switch`` is monkeypatched on the same module instance
the endpoint resolves (``src.jarvis.daemon``) — see tests/conftest.py on the
src-prefix import duplication caveat.
"""

import json
import threading
import time

import pytest

from src.jarvis.api_server import patch_config, ConfigPatch
import src.jarvis.daemon as daemon_mod


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"stt_backend": "wispr", "voice_debug": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(path))
    return path


def test_changing_stt_backend_triggers_switch_and_writes(cfg_file, monkeypatch):
    calls = []
    done = threading.Event()

    def _fake(new_backend):
        calls.append(new_backend)
        done.set()
        return True

    monkeypatch.setattr(daemon_mod, "request_stt_switch", _fake)

    patch_config(ConfigPatch(updates={"stt_backend": "whisper"}))

    assert done.wait(3.0), "background switch was never triggered"
    assert calls == ["whisper"]
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["stt_backend"] == "whisper"


def test_unrelated_change_does_not_trigger_switch(cfg_file, monkeypatch):
    calls = []
    monkeypatch.setattr(daemon_mod, "request_stt_switch", lambda nb: calls.append(nb))

    patch_config(ConfigPatch(updates={"voice_debug": True}))

    time.sleep(0.3)  # give any (erroneous) background thread time to fire
    assert calls == []


def test_same_value_stt_backend_does_not_trigger(cfg_file, monkeypatch):
    calls = []
    monkeypatch.setattr(daemon_mod, "request_stt_switch", lambda nb: calls.append(nb))

    patch_config(ConfigPatch(updates={"stt_backend": "wispr"}))  # already wispr

    time.sleep(0.3)
    assert calls == []
