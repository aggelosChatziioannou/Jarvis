import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import types
import jarvis.api_server as api
from fastapi.testclient import TestClient

client = TestClient(api.app)


def test_unknown_op_returns_not_ok():
    r = client.post("/api/spotify/control", json={"op": "frobnicate"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "op" in body["reason"]


def test_not_authorised_when_no_cache(monkeypatch):
    monkeypatch.setattr(api, "_mcp_env", lambda: {})
    r = client.post("/api/spotify/control", json={"op": "playpause"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_playpause_happy_path(monkeypatch, tmp_path):
    calls = {"paused": False, "started": False}

    class FakeSpotify:
        def __init__(self, *a, **k): pass
        def devices(self): return {"devices": [{"id": "dev1", "is_active": True}]}
        def current_playback(self): return {"is_playing": True, "item": {"name": "X"}}
        def pause_playback(self, *a, **k): calls["paused"] = True
        def start_playback(self, *a, **k): calls["started"] = True
        def next_track(self, *a, **k): pass
        def previous_track(self, *a, **k): pass

    class FakeOAuth:
        def __init__(self, *a, **k):
            self.cache_handler = types.SimpleNamespace(get_cached_token=lambda: {"access_token": "t"})

    fake_spotipy = types.ModuleType("spotipy")
    fake_spotipy.Spotify = FakeSpotify
    fake_oauth = types.ModuleType("spotipy.oauth2")
    fake_oauth.SpotifyOAuth = FakeOAuth
    monkeypatch.setitem(sys.modules, "spotipy", fake_spotipy)
    monkeypatch.setitem(sys.modules, "spotipy.oauth2", fake_oauth)

    cache = tmp_path / ".spotify_cache"
    cache.write_text("{}")
    monkeypatch.setattr(api, "_MCPS_ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(api, "_mcp_env", lambda: {"SPOTIFY_CLIENT_ID": "id"})

    r = client.post("/api/spotify/control", json={"op": "playpause"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["is_playing"] is False
    assert calls["paused"] is True
