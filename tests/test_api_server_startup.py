"""Behaviour tests for api_server startup hardening.

These verify observable outcomes — not how the helper is wired internally:
  - Detect a busy port and refuse to launch into the void.
  - Surface a uvicorn startup crash to callers instead of swallowing it.

The fastapi `app` object is imported lazily inside the test so a missing
optional dependency in CI just skips this module instead of failing collection.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest


def _grab_free_port() -> int:
    """Reserve an ephemeral port, return it after releasing the socket."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# _check_port_available
# ---------------------------------------------------------------------------


def test_check_port_available_returns_true_for_free_port() -> None:
    from jarvis.api_server import _check_port_available

    port = _grab_free_port()
    assert _check_port_available("127.0.0.1", port) is True


def test_check_port_available_returns_false_when_port_busy() -> None:
    from jarvis.api_server import _check_port_available

    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        busy_port = holder.getsockname()[1]
        assert _check_port_available("127.0.0.1", busy_port) is False
    finally:
        holder.close()


# ---------------------------------------------------------------------------
# start_in_background — port-busy and uvicorn-crash propagation
# ---------------------------------------------------------------------------


def test_start_in_background_returns_false_when_port_busy(monkeypatch) -> None:
    from jarvis import api_server

    busy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy_socket.bind(("127.0.0.1", 0))
    busy_socket.listen(1)
    busy_port = busy_socket.getsockname()[1]

    monkeypatch.setattr(api_server, "API_PORT", busy_port)
    # Reset module state so a previous test doesn't short-circuit this one
    monkeypatch.setattr(api_server, "_server_thread", None)
    monkeypatch.setattr(api_server, "_server_instance", None)

    try:
        result = api_server.start_in_background()
        assert result is False, "expected start_in_background to refuse busy port"
        assert api_server.get_startup_error() is not None, (
            "expected a startup error to be recorded when port is busy"
        )
    finally:
        busy_socket.close()


# ---------------------------------------------------------------------------
# /api/audio/devices — delegates to the real-device cleaner
# ---------------------------------------------------------------------------


def test_audio_devices_endpoint_returns_filtered_shape(monkeypatch) -> None:
    """The endpoint must return the cleaned list_real_devices() result, keeping
    the {inputs, outputs, current_in, current_out} shape the UI expects."""
    from jarvis import api_server
    from jarvis.output import audio_devices

    cleaned = {
        "inputs": [{"index": 18, "name": "Microphone (PD200X Podcast Microphone)"}],
        "outputs": [
            {"index": 15, "name": "Headset (Realtek(R) Audio)"},
            {"index": 16, "name": "Speakers (PD200X Podcast Microphone)"},
        ],
        "current_in": 18,
        "current_out": 15,
    }
    monkeypatch.setattr(audio_devices, "list_real_devices", lambda: cleaned)

    result = api_server.list_audio_devices()

    # Endpoint passes the cleaned data straight through — no junk re-introduced.
    assert result == cleaned


def test_audio_devices_endpoint_fails_open_to_empty(monkeypatch) -> None:
    """If the cleaner raises, the endpoint returns the safe empty shape rather
    than 500-ing the settings UI."""
    from jarvis import api_server
    from jarvis.output import audio_devices

    def _boom():
        raise RuntimeError("portaudio exploded")

    monkeypatch.setattr(audio_devices, "list_real_devices", _boom)

    result = api_server.list_audio_devices()

    assert result == {"inputs": [], "outputs": [], "current_in": None, "current_out": None}


def test_start_in_background_records_uvicorn_crash(monkeypatch) -> None:
    """If the uvicorn thread's run() raises, the error must be retrievable."""
    from jarvis import api_server

    monkeypatch.setattr(api_server, "_server_thread", None)
    monkeypatch.setattr(api_server, "_server_instance", None)

    class _ExplodingServer:
        should_exit = False

        def run(self) -> None:
            raise RuntimeError("uvicorn boom")

    def _fake_server(*args, **kwargs):
        return _ExplodingServer()

    monkeypatch.setattr(api_server.uvicorn, "Server", _fake_server)
    # Force the port check to pass so the run() call is reached
    monkeypatch.setattr(api_server, "_check_port_available", lambda *_: True)

    result = api_server.start_in_background()
    # Give the daemon thread a moment to raise + record the error
    for _ in range(50):
        if api_server.get_startup_error() is not None:
            break
        time.sleep(0.02)

    assert result is False, "expected start_in_background to surface crash as False"
    err = api_server.get_startup_error()
    assert err is not None and "boom" in str(err), (
        f"expected recorded crash to mention 'boom', got: {err!r}"
    )
