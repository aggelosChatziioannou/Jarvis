"""Tests for `jarvis.listening.audio_preproc.normalize` AGC helper.

PD200X is a dynamic mic with low inherent output — the AGC brings weak signals
up to a target RMS so VAD and Whisper see a consistent level, without ever
hard-clipping the peaks.
"""
from __future__ import annotations

import numpy as np
import pytest

from jarvis.listening.audio_preproc import normalize


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def test_silence_passes_through_unchanged():
    """Pure silence must not be amplified — that would just amplify noise floor."""
    silence = np.zeros(320, dtype=np.float32)
    out = normalize(silence, target_rms=0.1)
    assert out.shape == silence.shape
    assert np.array_equal(out, silence)


def test_near_silence_passes_through_unchanged():
    """RMS below the 1e-6 dead-zone is treated as silence."""
    near_silence = np.full(320, 1e-7, dtype=np.float32)
    out = normalize(near_silence, target_rms=0.1)
    assert np.array_equal(out, near_silence)


def test_low_signal_boosted_to_target_rms():
    """A weak signal (~0.01 RMS) should be boosted close to target_rms."""
    rng = np.random.default_rng(42)
    weak = (rng.standard_normal(1600).astype(np.float32) * 0.01)
    out = normalize(weak, target_rms=0.1, max_gain=20.0)
    # We expect the RMS to be roughly target_rms (within 15% — soft-clip / dead-zone tolerance)
    assert _rms(out) == pytest.approx(0.1, rel=0.15)


def test_max_gain_caps_amplification():
    """Extremely weak signals must not be amplified past max_gain to avoid noise blow-up."""
    tiny = np.full(320, 0.0001, dtype=np.float32)  # would need gain=1000 to hit 0.1
    out = normalize(tiny, target_rms=0.1, max_gain=10.0)
    # Gain capped at 10 → output RMS ~ 0.001, NOT 0.1
    assert _rms(out) == pytest.approx(0.001, rel=0.1)


def test_loud_signal_not_attenuated_beyond_target():
    """A signal already above target_rms is allowed to stay loud — AGC only boosts."""
    rng = np.random.default_rng(0)
    loud = (rng.standard_normal(1600).astype(np.float32) * 0.5)
    out = normalize(loud, target_rms=0.1, max_gain=10.0)
    # The function multiplies by min(target/rms, max_gain). When target/rms < 1 the gain is <1,
    # which would actually attenuate. The contract: gain is clamped to >= 1.0 (only boost).
    # If a future implementation allows attenuation, this test will catch the regression.
    assert _rms(out) >= _rms(loud) * 0.95  # allow tiny soft-clip rounding


def test_peaks_above_threshold_are_soft_clipped():
    """If boosting would push peaks past 0.95, soft-clip via tanh keeps |x| < 1.0."""
    # Construct a signal whose RMS is small but contains a tall spike.
    signal = np.zeros(320, dtype=np.float32)
    signal[100:110] = 0.6  # spike
    out = normalize(signal, target_rms=0.3, max_gain=20.0)
    # Boost is min(0.3/rms, 20) ≈ large → spike would go to ≥ 0.95 → soft-clip kicks in.
    assert float(np.max(np.abs(out))) < 1.0, "soft clip must prevent hard-clip at ±1.0"


def test_dtype_preserved_float32():
    """sounddevice frames are float32 — must not be silently upcast to float64."""
    rng = np.random.default_rng(0)
    weak = (rng.standard_normal(1600).astype(np.float32) * 0.01)
    out = normalize(weak, target_rms=0.1)
    assert out.dtype == np.float32


def test_multichannel_frame_handled():
    """sounddevice may deliver (frames, channels) arrays — single-channel slice should work."""
    rng = np.random.default_rng(0)
    weak = (rng.standard_normal((1600, 1)).astype(np.float32) * 0.01)
    out = normalize(weak.flatten(), target_rms=0.1)
    assert out.shape == (1600,)
    assert _rms(out) == pytest.approx(0.1, rel=0.15)
