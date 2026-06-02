"""Privacy: GET /api/config must not leak secrets; PATCH must not wipe them.

The control API is unauthenticated loopback. Returning stored credentials
(Brave key, MCP env tokens) verbatim lets any local process or same-origin
page exfiltrate every secret with one GET. We mask secret-looking values on
read and preserve them across a masked round-trip on write.
"""

import json
import os

import pytest

from src.jarvis.api_server import get_config, patch_config, ConfigPatch


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    data = {
        "brave_search_api_key": "REAL-BRAVE-KEY",
        "ollama_chat_model": "qwen3.5:9b-4k",  # non-secret, must pass through
        "mcp_servers": [
            {
                "id": "spotify",
                "command": "npx",
                "args": ["spotify-mcp"],
                "env": {"SPOTIFY_CLIENT_SECRET": "shh-secret", "DEBUG": "1"},
            }
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(path))
    return path


def test_get_config_masks_top_level_secret(cfg_file):
    out = get_config()
    assert out["brave_search_api_key"] != "REAL-BRAVE-KEY"
    assert "REAL-BRAVE-KEY" not in json.dumps(out)


def test_get_config_masks_mcp_env_secrets(cfg_file):
    out = get_config()
    assert "shh-secret" not in json.dumps(out)


def test_get_config_passes_through_non_secret_values(cfg_file):
    out = get_config()
    assert out["ollama_chat_model"] == "qwen3.5:9b-4k"


def test_patch_with_masked_secret_preserves_stored_value(cfg_file):
    # UI fetched the masked config and sends it back unchanged.
    masked = get_config()
    patch_config(ConfigPatch(updates={"brave_search_api_key": masked["brave_search_api_key"]}))
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["brave_search_api_key"] == "REAL-BRAVE-KEY"


def test_patch_with_real_new_secret_is_written(cfg_file):
    patch_config(ConfigPatch(updates={"brave_search_api_key": "NEW-KEY"}))
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["brave_search_api_key"] == "NEW-KEY"
