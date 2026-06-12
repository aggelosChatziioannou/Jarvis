"""API tests for the console VRAM controls (/api/models*)."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jarvis import api_server, model_admin, runtime_flags

pytestmark = pytest.mark.unit

client = TestClient(api_server.app)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "stt_backend": "wispr", "vision_enabled": True,
        "vision_model": "qwen2.5vl:3b", "chat_model": "qwen3.5:9b-4k",
        "a": 1, "b": 2, "c": 3, "d": 4,
    }), encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg))
    runtime_flags.set_brain_paused(False)
    yield cfg
    runtime_flags.set_brain_paused(False)


def _fake_loaded(*_a, **_k):
    return [
        {"name": "qwen3.5:9b-4k", "size_vram": 9_000_000_000},
        {"name": "qwen2.5vl:3b", "size_vram": 3_000_000_000},
    ]


class TestGetModels:
    def test_reports_loaded_models_and_flags(self):
        with patch.object(model_admin, "list_loaded_models", _fake_loaded):
            data = client.get("/api/models").json()
        assert [m["name"] for m in data["loaded"]] == ["qwen3.5:9b-4k", "qwen2.5vl:3b"]
        assert data["total_vram"] == 12_000_000_000
        assert data["brain_paused"] is False
        assert isinstance(data["vision_enabled"], bool)


class TestVisionToggle:
    def test_disable_persists_and_unloads_vision_model(self, _reset):
        calls = []
        with patch.object(model_admin, "unload_model",
                          side_effect=lambda b, n: calls.append(n) or True):
            resp = client.post("/api/models/vision", json={"enabled": False})
        assert resp.json() == {"vision_enabled": False}
        assert calls == ["qwen2.5vl:3b"]
        persisted = json.loads(_reset.read_text(encoding="utf-8"))
        assert persisted["vision_enabled"] is False
        # The rest of the config must survive the toggle write untouched.
        assert persisted["stt_backend"] == "wispr"

    def test_enable_persists_without_unloading(self, _reset):
        with patch.object(model_admin, "unload_model") as unload:
            client.post("/api/models/vision", json={"enabled": True})
        unload.assert_not_called()
        assert json.loads(_reset.read_text(encoding="utf-8"))["vision_enabled"] is True


class TestFlushToggle:
    def test_flush_pauses_brain_and_unloads_everything(self):
        with patch.object(model_admin, "unload_all",
                          return_value=["qwen3.5:9b-4k", "qwen2.5vl:3b"]) as ua:
            data = client.post("/api/models/flush", json={"paused": True}).json()
        ua.assert_called_once()
        assert data["brain_paused"] is True
        assert runtime_flags.is_brain_paused() is True

    def test_unflush_clears_the_pause_flag(self):
        runtime_flags.set_brain_paused(True)
        with patch.object(api_server.threading, "Thread") as th:  # no real warm-up
            data = client.post("/api/models/flush", json={"paused": False}).json()
        assert data["brain_paused"] is False
        assert runtime_flags.is_brain_paused() is False
        th.assert_called_once()  # re-warm scheduled in the background

    def test_flush_is_runtime_only_never_persisted(self, _reset):
        """A restart must always bring the brain back: the pause flag may
        never reach the config file, and the persisted toggles must keep
        their values. (Byte-equality is too strict — load_settings() itself
        may rewrite the file with migrated defaults.)"""
        with patch.object(model_admin, "unload_all", return_value=[]):
            client.post("/api/models/flush", json={"paused": True})
        persisted = json.loads(_reset.read_text(encoding="utf-8"))
        assert "brain_paused" not in persisted
        assert persisted["stt_backend"] == "wispr"
        assert persisted["vision_enabled"] is True
