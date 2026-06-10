"""Behavioural tests for the live audio telemetry helpers + API plumbing."""

import math

import numpy as np
import pytest

from jarvis.listening.audio_telemetry import band_spectrum, normalise_rms, telemetry_frame


class TestNormaliseRms:
    def test_full_scale_maps_to_one(self):
        assert normalise_rms(32768.0) == 1.0

    def test_silence_maps_to_zero(self):
        assert normalise_rms(0.0) == 0.0

    def test_software_gain_is_undone(self):
        # A 3x gained signal reports the true (ungained) level.
        assert normalise_rms(3000.0, gain=3.0) == pytest.approx(1000.0 / 32768.0)

    def test_clamped_to_unit_range(self):
        assert normalise_rms(99_999_999.0) == 1.0
        assert normalise_rms(-5.0) == 0.0

    def test_zero_gain_does_not_explode(self):
        assert 0.0 <= normalise_rms(1000.0, gain=0.0) <= 1.0


class TestBandSpectrum:
    def test_silence_gives_all_zero_bands(self):
        frame = np.zeros(1280, dtype=np.int16)
        assert band_spectrum(frame) == [0.0] * 16

    def test_returns_requested_band_count(self):
        frame = np.random.default_rng(0).integers(-2000, 2000, 1280).astype(np.int16)
        assert len(band_spectrum(frame, bands=16)) == 16
        assert len(band_spectrum(frame, bands=8)) == 8

    def test_band_ordering_tracks_frequency(self):
        # A low tone's peak band must sit below a high tone's peak band,
        # and a tone leaves the far end of the spectrum quiet.
        t = np.arange(1280) / 16000.0
        low = (np.sin(2 * math.pi * 200 * t) * 16000).astype(np.int16)
        high = (np.sin(2 * math.pi * 4000 * t) * 16000).astype(np.int16)
        low_spec, high_spec = band_spectrum(low), band_spectrum(high)
        low_peak = low_spec.index(max(low_spec))
        high_peak = high_spec.index(max(high_spec))
        assert max(low_spec) > 0.05
        assert low_peak < high_peak
        assert max(low_spec[high_peak:]) < max(low_spec) / 2

    def test_all_values_in_unit_range(self):
        t = np.arange(1280) / 16000.0
        loud = (np.sin(2 * math.pi * 1000 * t) * 32767).astype(np.int16)
        assert all(0.0 <= v <= 1.0 for v in band_spectrum(loud))

    def test_garbage_input_fails_open(self):
        assert band_spectrum(None) == [0.0] * 16
        assert band_spectrum([]) == [0.0] * 16


class TestTelemetryFrame:
    def test_payload_shape(self):
        p = telemetry_frame(rms_norm=0.12345678, state="idle", wake_score=0.42,
                            vad_prob=0.9, voiced=True, spec=[0.1, 0.2])
        assert p["rms"] == pytest.approx(0.12346)
        assert p["state"] == "idle"
        assert p["wake"] == pytest.approx(0.42)
        assert p["vad"] == pytest.approx(0.9)
        assert p["voiced"] is True
        assert p["spec"] == [0.1, 0.2]

    def test_optional_fields_default_to_none(self):
        p = telemetry_frame(rms_norm=0.0, state="dictating")
        assert p["wake"] is None
        assert p["vad"] is None
        assert p["voiced"] is False
        assert p["spec"] == []


class TestApiPlumbing:
    def test_publish_is_noop_without_subscribers(self):
        # Must never raise and never queue when no console is watching.
        from jarvis import api_server

        assert api_server.has_audio_subscribers() is False
        api_server.publish_audio_telemetry({"rms": 0.1})  # no exception

    def test_ws_audio_endpoint_streams_published_frames(self):
        from fastapi.testclient import TestClient
        from jarvis import api_server

        # Context-managed client runs the lifespan startup, which records the
        # event loop used by the thread-safe broadcast path.
        with TestClient(api_server.app) as client:
            with client.websocket_connect("/ws/audio") as ws:
                assert api_server.has_audio_subscribers() is True
                api_server.publish_audio_telemetry({"rms": 0.5, "state": "idle"})
                msg = ws.receive_json()
                assert msg["rms"] == 0.5
                assert msg["state"] == "idle"
        assert api_server.has_audio_subscribers() is False
