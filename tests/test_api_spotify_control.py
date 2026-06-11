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
        def __init__(self, *a, **k):
            # Behavioural contract: the client must be built from the plain
            # validated access token (never an auth_manager, which can fall
            # back to an interactive stdin prompt) and must be time-bounded.
            calls["client_kwargs"] = k
        def devices(self): return {"devices": [{"id": "dev1", "is_active": True}]}
        def current_playback(self): return {"is_playing": True, "item": {"name": "X"}}
        def pause_playback(self, *a, **k): calls["paused"] = True
        def start_playback(self, *a, **k): calls["started"] = True
        def next_track(self, *a, **k): pass
        def previous_track(self, *a, **k): pass

    class FakeOAuth:
        def __init__(self, *a, **k):
            self.cache_handler = types.SimpleNamespace(get_cached_token=lambda: {"access_token": "t"})

        def validate_token(self, token):
            # Real spotipy returns the token only when fresh AND its scope
            # covers the requested one; the endpoint must rely on this.
            return token

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
    assert calls["client_kwargs"].get("auth") == "t"
    assert calls["client_kwargs"].get("requests_timeout") is not None


def test_underscoped_token_fails_fast_not_interactive(monkeypatch, tmp_path):
    """A cached token that fails scope validation must return a fast, clean
    failure — never reach the Spotify client (where spotipy would start an
    interactive OAuth prompt that hangs forever under pythonw)."""
    class BoomSpotify:
        def __init__(self, *a, **k):
            raise AssertionError("client must not be constructed without a valid token")

    class FakeOAuth:
        def __init__(self, *a, **k):
            self.cache_handler = types.SimpleNamespace(
                get_cached_token=lambda: {"access_token": "t", "scope": "user-read-playback-state"})

        def validate_token(self, token):
            return None  # scope check failed

    fake_spotipy = types.ModuleType("spotipy")
    fake_spotipy.Spotify = BoomSpotify
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
    assert body["ok"] is False
    assert "authorise" in body["reason"]
