"""Tests for `normalize_segment` — post-VAD per-segment gain normalisation.

Different from `normalize` (continuous AGC): runs once per VAD-gated segment,
does not amplify pure silence, allows attenuation of loud input.
"""
from __future__ import annotations

import numpy as np
import pytest

from jarvis.listening.audio_preproc import normalize_segment


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def test_silence_passes_through_unchanged():
    silence = np.zeros(16000, dtype=np.float32)
    out = normalize_segment(silence, target_rms=0.1)
    assert np.array_equal(out, silence)


def test_quiet_signal_brought_up_to_target_rms():
    """Weak input (typical PD200X output) brought up to ~target RMS."""
    rng = np.random.default_rng(42)
    quiet = (rng.standard_normal(16000).astype(np.float32) * 0.01)  # ~ -40 dBFS
    out = normalize_segment(quiet, target_rms=0.1)
    assert _rms(out) == pytest.approx(0.1, rel=0.1)


def test_loud_signal_attenuated_toward_target():
    """Unlike continuous AGC, segment normalisation ALSO attenuates loud input.

    Goal is a consistent feature distribution for Whisper's encoder, not just
    boosting quiet audio.
    """
    rng = np.random.default_rng(0)
    loud = (rng.standard_normal(16000).astype(np.float32) * 0.4)
    out = normalize_segment(loud, target_rms=0.1)
    # Should be brought down from 0.4 RMS toward 0.1.
    assert _rms(out) == pytest.approx(0.1, rel=0.1)


def test_peaks_hard_limited_below_minus_3dbfs():
    """No sample should exceed the peak_limit (0.707 ≈ -3 dBFS default)."""
    signal = np.zeros(16000, dtype=np.float32)
    signal[8000:8500] = 0.95  # spike near full scale
    out = normalize_segment(signal, target_rms=0.5, peak_limit=0.707)
    assert float(np.max(np.abs(out))) <= 0.707 + 1e-6


def test_dtype_stays_float32():
    rng = np.random.default_rng(0)
    quiet = (rng.standard_normal(1600).astype(np.float32) * 0.01)
    out = normalize_segment(quiet, target_rms=0.1)
    assert out.dtype == np.float32


def test_empty_returns_unchanged():
    empty = np.zeros(0, dtype=np.float32)
    out = normalize_segment(empty)
    assert out.size == 0


def test_does_not_mutate_input():
    rng = np.random.default_rng(0)
    quiet = (rng.standard_normal(1600).astype(np.float32) * 0.01)
    backup = quiet.copy()
    _ = normalize_segment(quiet, target_rms=0.1)
    assert np.array_equal(quiet, backup), "input array must not be mutated in place"
