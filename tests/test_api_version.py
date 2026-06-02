"""GET /api/version exposes the app version + release channel.

The redesigned console StatusBar shows the running version instead of a
hardcoded string. The endpoint is local-only and leaks nothing sensitive.
"""

from src.jarvis.api_server import get_version_info


def test_version_endpoint_returns_version_and_channel():
    out = get_version_info()
    assert isinstance(out.get("version"), str)
    assert out["version"]  # non-empty
    assert out.get("channel") in {"stable", "develop"}
