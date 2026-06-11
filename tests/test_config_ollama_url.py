"""Behaviour: `localhost` in ollama_base_url is normalised to 127.0.0.1.

On Windows, `localhost` resolves IPv6-first (::1). Ollama binds IPv4 only, so
every NEW connection pays a ~2s fallback penalty before reaching 127.0.0.1 —
a flat 2s tax on every LLM call in the app (fused intent, replies, embeddings,
vision). Normalising centrally in load_settings() removes the tax for every
consumer regardless of what the user's config.json says.
"""

import json

import pytest

from jarvis.config import load_settings, normalise_ollama_base_url


class TestNormaliseOllamaBaseUrl:
    @pytest.mark.parametrize("given,expected", [
        ("http://localhost:11434", "http://127.0.0.1:11434"),
        ("http://LOCALHOST:11434", "http://127.0.0.1:11434"),
        ("http://localhost", "http://127.0.0.1"),
        ("https://localhost:11434", "https://127.0.0.1:11434"),
    ])
    def test_localhost_rewritten_to_ipv4_loopback(self, given, expected):
        assert normalise_ollama_base_url(given) == expected

    @pytest.mark.parametrize("untouched", [
        "http://127.0.0.1:11434",
        "http://192.168.1.50:11434",
        "http://my-ollama-box:11434",
        "http://localhost.example.com:11434",  # only the exact host is rewritten
        "http://[::1]:11434",  # explicit IPv6 is an intentional choice
    ])
    def test_other_hosts_left_alone(self, untouched):
        assert normalise_ollama_base_url(untouched) == untouched

    def test_garbage_input_returned_as_is(self):
        assert normalise_ollama_base_url("") == ""
        assert normalise_ollama_base_url("not a url") == "not a url"


class TestLoadSettingsNormalisesUrl:
    def test_localhost_in_config_json_arrives_as_loopback_ip(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"ollama_base_url": "http://localhost:11434"}))
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg))
        settings = load_settings()
        assert settings.ollama_base_url == "http://127.0.0.1:11434"
