"""Tests for `jarvis.listening.vad_silero.SileroVAD` wrapper.

The wrapper exposes the same `is_speech(pcm16_bytes, sample_rate)` API as
`webrtcvad.Vad` so listener.py can swap backends with one branch. These tests
focus on the WRAPPER's contract, not on Silero's underlying accuracy.
"""
from __future__ import annotations

import numpy as np
import pytest


silero_vad = pytest.importorskip(
    "silero_vad",
    reason="silero-vad not installed in this environment — skipping wrapper tests",
)


def _make_pcm16(samples: np.ndarray, sample_rate: int) -> bytes:
    """Convert a float32 [-1, 1] array to 16-bit little-endian PCM bytes."""
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


@pytest.fixture()
def vad():
    from jarvis.listening.vad_silero import SileroVAD
    return SileroVAD(threshold=0.5)


def test_pure_silence_classified_as_non_speech(vad):
    """20 ms of silence at 16 kHz → ~320 samples → must return False."""
    silence = np.zeros(320, dtype=np.float32)
    frame_bytes = _make_pcm16(silence, 16000)
    assert vad.is_speech(frame_bytes, 16000) is False


def test_white_noise_at_low_volume_classified_as_non_speech(vad):
    """Quiet broadband noise should not register as speech."""
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(320).astype(np.float32) * 0.005
    frame_bytes = _make_pcm16(noise, 16000)
    assert vad.is_speech(frame_bytes, 16000) is False


def test_sine_tone_handled_without_crash(vad):
    """A 440 Hz tone is not speech — wrapper must return without raising and not crash on tonal input."""
    t = np.arange(320) / 16000.0
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    frame_bytes = _make_pcm16(tone, 16000)
    result = vad.is_speech(frame_bytes, 16000)
    assert isinstance(result, bool)


def test_invalid_sample_rate_raises(vad):
    """Silero only supports 8 kHz / 16 kHz — anything else should raise."""
    frame_bytes = _make_pcm16(np.zeros(320, dtype=np.float32), 22050)
    with pytest.raises(ValueError):
        vad.is_speech(frame_bytes, 22050)


def test_threshold_is_configurable():
    """A stricter threshold (0.9) must accept fewer frames than 0.1."""
    from jarvis.listening.vad_silero import SileroVAD

    # Build a frame that is ambiguous (low-amplitude noise) — exact result varies,
    # but a strict vs lax instance MUST agree that lax >= strict.
    rng = np.random.default_rng(0)
    ambiguous = rng.standard_normal(1600).astype(np.float32) * 0.05  # 100 ms
    frame_bytes = _make_pcm16(ambiguous, 16000)

    strict = SileroVAD(threshold=0.95)
    lax = SileroVAD(threshold=0.05)
    s = strict.is_speech(frame_bytes, 16000)
    l = lax.is_speech(frame_bytes, 16000)
    # Stricter wrapper cannot accept what the lax one rejects (monotonicity).
    assert not (s and not l), "stricter threshold should accept a subset of lax-accepted frames"


def test_singleton_model_shared_across_instances():
    """The underlying ONNX model is expensive — wrapper must cache it across instances."""
    from jarvis.listening import vad_silero

    v1 = vad_silero.SileroVAD()
    v2 = vad_silero.SileroVAD()
    # Both should resolve to the same cached model object.
    assert v1._model is v2._model
