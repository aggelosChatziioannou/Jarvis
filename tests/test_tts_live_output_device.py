"""Behaviour tests for the TTS output device resolver (Task 4).

Goal (audio device redesign, Phase 2):
  * TTS output resolves the PERSISTED endpoint id fresh on every playback via
    ``audio_devices.resolve_endpoint_to_sd_index(cfg.audio_output_endpoint_id,
    cfg.audio_output_name, kind="output")`` — no caching, so a just-saved
    selection applies without a restart.
  * The "(Follow Windows default)" branch is REMOVED. ``get_default_output_name``
    must NOT be consulted on the normal resolution path.
  * When the selected device is absent the resolver returns None and playback
    fails open (no exception) so there is still sound (last-resort default).
  * The WASAPI-exclusive low-latency path (Chatterbox) is only used when the
    freshly-resolved device IS the WASAPI default device — otherwise PortAudio
    rejects the exclusive extra_settings (-9984). A configured device that
    differs from the WASAPI default must play SHARED on that device.

These assert observable outcomes (which index playback targets, which call the
resolver makes, which mode is used) rather than internal cache state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fresh resolver: endpoint-id resolution, no follow-default, no caching
# ---------------------------------------------------------------------------


def test_resolver_uses_persisted_endpoint_id():
    """The resolver passes the persisted endpoint id + name straight to
    ``resolve_endpoint_to_sd_index`` for the output flow and returns its
    index."""
    from src.jarvis.output import tts

    fake_cfg = MagicMock()
    fake_cfg.audio_output_endpoint_id = "{0.0.0.00000000}.{spk-guid}"
    fake_cfg.audio_output_name = "Speakers (PD200X Podcast Microphone)"

    with patch("src.jarvis.output.tts.load_settings", return_value=fake_cfg, create=True), \
         patch("src.jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
               return_value=16) as p_resolve:
        idx = tts._resolve_output_device_live()

    assert idx == 16
    p_resolve.assert_called_once()
    # First positional arg is the endpoint id; second the saved name.
    call = p_resolve.call_args
    id_arg = call.args[0] if call.args else call.kwargs.get("endpoint_id")
    name_arg = call.args[1] if len(call.args) > 1 else call.kwargs.get("name")
    assert id_arg == "{0.0.0.00000000}.{spk-guid}"
    assert name_arg == "Speakers (PD200X Podcast Microphone)"
    assert call.kwargs.get("kind") == "output"


def test_resolver_does_not_consult_windows_default():
    """The follow-Windows-default branch is gone: ``get_default_output_name``
    must never be called by the resolver, even when nothing is configured."""
    from src.jarvis.output import tts

    fake_cfg = MagicMock()
    fake_cfg.audio_output_endpoint_id = ""
    fake_cfg.audio_output_name = ""

    with patch("src.jarvis.output.tts.load_settings", return_value=fake_cfg, create=True), \
         patch("src.jarvis.output.audio_devices.get_default_output_name") as p_default, \
         patch("src.jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
               return_value=None):
        idx = tts._resolve_output_device_live()

    assert idx is None
    p_default.assert_not_called()


def test_resolver_applies_selection_change_live_without_restart():
    """Two consecutive resolves with a CHANGED persisted selection return the
    two different indices — proving there is no module-level cache pinning the
    first value (the restart-required bug)."""
    from src.jarvis.output import tts

    fake_cfg = MagicMock()
    fake_cfg.audio_output_endpoint_id = "{ep-a}"
    fake_cfg.audio_output_name = "Headset (Realtek(R) Audio)"

    # The resolver should reflect a changed selection on the very next call.
    with patch("src.jarvis.output.tts.load_settings", return_value=fake_cfg, create=True), \
         patch("src.jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
               side_effect=[15, 16]):
        first = tts._resolve_output_device_live()
        second = tts._resolve_output_device_live()

    assert first == 15
    assert second == 16


def test_resolver_fails_open_to_none_when_device_absent():
    """If the selected device is absent (resolve returns None), the resolver
    returns None so playback falls back to PortAudio's own default device."""
    from src.jarvis.output import tts

    fake_cfg = MagicMock()
    fake_cfg.audio_output_endpoint_id = "{ep-gone}"
    fake_cfg.audio_output_name = "Vanished Speakers"

    with patch("src.jarvis.output.tts.load_settings", return_value=fake_cfg, create=True), \
         patch("src.jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
               return_value=None):
        assert tts._resolve_output_device_live() is None


# ---------------------------------------------------------------------------
# Piper play path resolves the device FRESH on each play
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self):
        self.active = False

    def start(self):
        self.active = False  # finishes immediately so the wait loop exits

    def close(self):
        self.active = False

    def abort(self):
        self.active = False


def test_piper_play_path_opens_resolved_device():
    """PiperTTS._play_int16_array opens its OutputStream against the freshly
    resolved persisted index (here 16), not a cached one."""
    from src.jarvis.output.tts import PiperTTS

    tts = PiperTTS(enabled=True, model_path="/fake/model.onnx")
    tts._sample_rate = 22050

    opened_devices = []

    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = {"default_samplerate": 22050}

    def fake_output_stream(**kwargs):
        opened_devices.append(kwargs.get("device"))
        return _FakeStream()

    fake_sd.OutputStream.side_effect = fake_output_stream
    fake_sd.CallbackAbort = Exception
    fake_sd.CallbackStop = Exception

    audio = np.zeros(512, dtype=np.int16)

    with patch.dict("sys.modules", {"sounddevice": fake_sd}), \
         patch("src.jarvis.output.tts._resolve_output_device_live", return_value=16) as p_resolve, \
         patch.object(tts, "_publish_tts_state"):
        played_ok, interrupted = tts._play_int16_array(audio)

    assert played_ok is True
    # The stream was opened against the freshly-resolved device.
    assert opened_devices and opened_devices[0] == 16
    p_resolve.assert_called()


def test_piper_play_path_fails_open_when_device_absent():
    """When the persisted device is absent (resolver returns None), Piper still
    plays (fails open) by opening the OutputStream with device=None — there is
    still sound rather than a crash."""
    from src.jarvis.output.tts import PiperTTS

    tts = PiperTTS(enabled=True, model_path="/fake/model.onnx")
    tts._sample_rate = 22050

    opened_devices = []

    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = {"default_samplerate": 22050}

    def fake_output_stream(**kwargs):
        opened_devices.append(kwargs.get("device"))
        return _FakeStream()

    fake_sd.OutputStream.side_effect = fake_output_stream
    fake_sd.CallbackAbort = Exception
    fake_sd.CallbackStop = Exception

    audio = np.zeros(512, dtype=np.int16)

    with patch.dict("sys.modules", {"sounddevice": fake_sd}), \
         patch("src.jarvis.output.tts._resolve_output_device_live", return_value=None), \
         patch.object(tts, "_publish_tts_state"):
        played_ok, interrupted = tts._play_int16_array(audio)

    # Fails open: playback still happened (no exception) on the OS default.
    assert played_ok is True
    assert opened_devices and opened_devices[0] is None


# ---------------------------------------------------------------------------
# Chatterbox path: WASAPI-exclusive ONLY when resolved device == WASAPI default
# ---------------------------------------------------------------------------


def _chatterbox_sd_with_wasapi(wasapi_default_index):
    """A fake sounddevice exposing one WASAPI host API whose default output is
    ``wasapi_default_index``, plus query_devices + play/stop/sleep stubs."""
    fake_sd = MagicMock()
    fake_sd.query_hostapis.return_value = [
        {"name": "Windows WASAPI", "default_output_device": wasapi_default_index}
    ]
    fake_sd.query_devices.return_value = {"default_samplerate": 48000}

    class _WasapiSettings:
        def __init__(self, exclusive=True):
            self.exclusive = exclusive

    fake_sd.WasapiSettings = _WasapiSettings
    fake_sd.PortAudioError = type("PortAudioError", (Exception,), {})

    play_calls = []

    def fake_play(*args, **kwargs):
        play_calls.append(kwargs)

    fake_sd.play.side_effect = fake_play

    stream = MagicMock()
    stream.active = False
    fake_sd.get_stream.return_value = stream
    fake_sd.sleep.return_value = None
    fake_sd.stop.return_value = None
    return fake_sd, play_calls


def test_chatterbox_uses_exclusive_when_resolved_equals_wasapi_default(tmp_path):
    """When the resolved device IS the WASAPI default, the exclusive path is
    used (extra_settings passed, device == WASAPI default)."""
    from src.jarvis.output import tts

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")  # contents irrelevant; soundfile.read is mocked

    fake_sd, play_calls = _chatterbox_sd_with_wasapi(wasapi_default_index=5)
    fake_sf = MagicMock()
    fake_sf.read.return_value = (np.zeros(480, dtype=np.float32), 48000)

    with patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": fake_sf}), \
         patch("src.jarvis.output.tts._resolve_output_device_live", return_value=5), \
         patch("sys.platform", "win32"):
        tts._play_via_sounddevice(str(wav), volume=1.0, should_interrupt=None)

    assert play_calls, "expected sd.play to be called"
    first = play_calls[0]
    # Exclusive path: extra_settings present AND device is the WASAPI default.
    assert first.get("extra_settings") is not None
    assert first.get("device") == 5


def test_chatterbox_uses_shared_when_resolved_differs_from_wasapi_default(tmp_path):
    """When the resolved device differs from the WASAPI default (the
    custom-device case), the exclusive path is SKIPPED and audio plays SHARED
    on the resolved device (no extra_settings) — avoiding PortAudio -9984."""
    from src.jarvis.output import tts

    wav = tmp_path / "b.wav"
    wav.write_bytes(b"RIFF")

    # WASAPI default is index 5, but the user picked a different device
    # (index 14, e.g. a Corsair headset on a NON-WASAPI host API).
    fake_sd, play_calls = _chatterbox_sd_with_wasapi(wasapi_default_index=5)
    fake_sf = MagicMock()
    fake_sf.read.return_value = (np.zeros(480, dtype=np.float32), 48000)

    with patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": fake_sf}), \
         patch("src.jarvis.output.tts._resolve_output_device_live", return_value=14), \
         patch("sys.platform", "win32"):
        tts._play_via_sounddevice(str(wav), volume=1.0, should_interrupt=None)

    assert play_calls, "expected sd.play to be called"
    # Shared path: NO exclusive extra_settings, targeting the resolved device.
    assert all(c.get("extra_settings") is None for c in play_calls), (
        f"exclusive settings must not be used for a non-WASAPI-default device; "
        f"calls={play_calls}"
    )
    assert play_calls[-1].get("device") == 14
