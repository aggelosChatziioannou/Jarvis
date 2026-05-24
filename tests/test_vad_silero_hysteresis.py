"""Tests for SileroVAD hysteresis behaviour.

When a separate `neg_threshold` is provided and lower than `threshold`, the
gate uses the strict threshold to OPEN (frame outside speech) and the
permissive `neg_threshold` to STAY OPEN (frame inside speech). This catches
trailing quiet phonemes that a single threshold would clip.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _pcm(samples: np.ndarray, sample_rate: int = 16000) -> bytes:
    return (np.clip(samples, -1, 1) * 32767.0).astype(np.int16).tobytes()


def _build_mocked_vad(prob_sequence):
    """Create a SileroVAD whose underlying model returns `prob_sequence` probabilities."""
    from jarvis.listening import vad_silero

    fake_model = MagicMock()
    iter_probs = iter(prob_sequence)
    def model_call(tensor, sr):
        result = MagicMock()
        result.item.return_value = next(iter_probs)
        return result
    fake_model.side_effect = model_call
    fake_model.reset_states = MagicMock()

    with patch.object(vad_silero, "_load_model", return_value=fake_model), \
         patch.object(vad_silero, "_MODEL_SINGLETON", None):
        return vad_silero.SileroVAD(threshold=0.7, neg_threshold=0.4)


@pytest.fixture()
def vad_with_probs():
    """Factory that returns a SileroVAD with a controlled probability sequence."""
    def _make(prob_sequence):
        return _build_mocked_vad(prob_sequence)
    return _make


def test_single_threshold_when_neg_threshold_omitted():
    """No-hysteresis case: SileroVAD(threshold=0.5) behaves like the original."""
    from jarvis.listening.vad_silero import SileroVAD
    with patch("jarvis.listening.vad_silero._load_model"):
        v = SileroVAD(threshold=0.5)
    assert v.neg_threshold == 0.5


def test_neg_threshold_clamped_to_onset():
    """If user provides neg_threshold > threshold, it gets clamped down."""
    from jarvis.listening.vad_silero import SileroVAD
    with patch("jarvis.listening.vad_silero._load_model"):
        v = SileroVAD(threshold=0.5, neg_threshold=0.9)
    assert v.neg_threshold == 0.5


def test_hysteresis_opens_on_strict_threshold(vad_with_probs):
    """Frame at prob=0.5 should be rejected initially (below onset 0.7)."""
    vad = vad_with_probs([0.5])
    frame = _pcm(np.zeros(512, dtype=np.float32))
    assert vad.is_speech(frame, 16000) is False
    assert vad._inside_speech is False


def test_hysteresis_stays_open_on_permissive_threshold(vad_with_probs):
    """After opening at 0.8, a 0.5-prob frame stays speech (above offset 0.4)."""
    vad = vad_with_probs([0.8, 0.5])
    frame = _pcm(np.zeros(512, dtype=np.float32))
    # First frame: prob 0.8 ≥ onset 0.7 → opens
    assert vad.is_speech(frame, 16000) is True
    # Second frame: prob 0.5 < onset 0.7 BUT ≥ offset 0.4 → stays speech
    assert vad.is_speech(frame, 16000) is True


def test_hysteresis_closes_when_below_offset(vad_with_probs):
    """When prob drops below offset 0.4, gate closes."""
    vad = vad_with_probs([0.8, 0.5, 0.3])
    frame = _pcm(np.zeros(512, dtype=np.float32))
    assert vad.is_speech(frame, 16000) is True   # opens
    assert vad.is_speech(frame, 16000) is True   # stays open (0.5 ≥ 0.4)
    assert vad.is_speech(frame, 16000) is False  # closes (0.3 < 0.4)


def test_hysteresis_requires_strict_threshold_to_reopen(vad_with_probs):
    """Once closed, ambiguous prob below strict onset must NOT reopen."""
    vad = vad_with_probs([0.8, 0.3, 0.6])
    frame = _pcm(np.zeros(512, dtype=np.float32))
    assert vad.is_speech(frame, 16000) is True   # opens
    assert vad.is_speech(frame, 16000) is False  # closes
    # 0.6 ≥ offset 0.4 BUT < onset 0.7 → still closed (this is the whole point)
    assert vad.is_speech(frame, 16000) is False


def test_reset_clears_hysteresis_state(vad_with_probs):
    vad = vad_with_probs([0.8, 0.5])
    frame = _pcm(np.zeros(512, dtype=np.float32))
    assert vad.is_speech(frame, 16000) is True
    assert vad._inside_speech is True
    vad.reset()
    assert vad._inside_speech is False
