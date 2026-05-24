"""Silero VAD wrapper with the same surface as `webrtcvad.Vad`.

Silero is a small neural VAD (ONNX) that benchmarks ~4× fewer errors than
WebRTC at the same false-positive rate. The wrapper hides the model-loading
and tensor-conversion details so `listener.py` can swap backends behind one
config flag without touching the audio loop.

The ONNX model is loaded once per process and cached (it's only a couple of
megabytes but the load itself takes hundreds of ms, which we don't want on
every frame). All `SileroVAD` instances share the same underlying model.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


_SUPPORTED_SAMPLE_RATES = (8000, 16000)
_MODEL_SINGLETON = None  # populated lazily; shared across SileroVAD instances


def _load_model():
    """Load the Silero ONNX model once and cache it."""
    global _MODEL_SINGLETON
    if _MODEL_SINGLETON is not None:
        return _MODEL_SINGLETON

    try:
        # silero-vad ≥ 5.x exposes `load_silero_vad()` (ONNX by default).
        from silero_vad import load_silero_vad  # type: ignore

        _MODEL_SINGLETON = load_silero_vad(onnx=True)
    except Exception as e:
        raise RuntimeError(
            f"Could not load Silero VAD model: {e}. "
            "Install with: pip install silero-vad"
        ) from e

    return _MODEL_SINGLETON


class SileroVAD:
    """`is_speech(pcm16_bytes, sample_rate) -> bool` — drop-in for webrtcvad.Vad.

    Args:
        threshold: Silero outputs a [0, 1] speech probability per frame.
            Onset threshold — when the gate is CLOSED, we need a probability
            >= `threshold` to open it. Stricter (higher) reduces false
            triggers from breathing / fan hum.
        neg_threshold: Offset threshold — when the gate is OPEN, we keep it
            open as long as the probability stays >= `neg_threshold`. By
            making this LOWER than `threshold`, we form a hysteresis loop
            that catches trailing quiet phonemes (Greek codas like /ς/, /φ/)
            that a single threshold would clip. Setting `neg_threshold` ==
            `threshold` collapses to no-hysteresis behaviour. Must be
            ≤ `threshold`.
    """

    # Silero expects exact chunk sizes: 256 (8 kHz) or 512 (16 kHz) samples.
    # When the caller hands us a different size, we trim or zero-pad to fit.
    _CHUNK_SAMPLES = {8000: 256, 16000: 512}

    def __init__(
        self,
        threshold: float = 0.5,
        neg_threshold: Optional[float] = None,
    ) -> None:
        self.threshold = float(threshold)
        # If neg_threshold not provided, fall back to no-hysteresis (same as
        # threshold). Tests instantiate SileroVAD with just `threshold=...`
        # and expect the original single-threshold behaviour to keep working.
        nt = float(neg_threshold) if neg_threshold is not None else float(threshold)
        if nt > self.threshold:
            nt = self.threshold
        self.neg_threshold = nt
        # Hysteresis state — tracks whether we're currently "inside" a
        # detected speech region. Frames inside the region use the looser
        # neg_threshold; frames outside use the stricter threshold.
        self._inside_speech = False
        self._model = _load_model()
        try:
            self._model.reset_states()
        except AttributeError:
            pass  # Older silero-vad builds don't expose reset_states.

    def is_speech(self, pcm16_bytes: bytes, sample_rate: int) -> bool:
        if sample_rate not in _SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"Silero VAD supports {_SUPPORTED_SAMPLE_RATES} Hz, got {sample_rate}"
            )

        # Decode int16 PCM → float32 in [-1, 1].
        samples = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        chunk_size = self._CHUNK_SAMPLES[sample_rate]

        if samples.size < chunk_size:
            padded = np.zeros(chunk_size, dtype=np.float32)
            padded[: samples.size] = samples
            samples = padded
        elif samples.size > chunk_size:
            samples = samples[:chunk_size]

        # Silero's ONNX runner takes a torch tensor.
        try:
            import torch
        except ImportError as e:  # pragma: no cover - silero-vad pulls torch in
            raise RuntimeError("torch is required for Silero VAD") from e

        with torch.no_grad():
            tensor = torch.from_numpy(samples).unsqueeze(0)  # [1, chunk_size]
            prob = float(self._model(tensor, sample_rate).item())

        # Hysteresis decision: choose threshold based on current state.
        active_threshold = self.neg_threshold if self._inside_speech else self.threshold
        is_speech_now = prob >= active_threshold
        self._last_probability = prob  # exposed for diagnostic logging
        self._inside_speech = is_speech_now
        return is_speech_now

    @property
    def last_probability(self) -> float:
        """Most recent raw Silero probability (set by the last `is_speech` call).

        Useful for diagnostic logging — lets callers see *why* the VAD made
        the decision it did, without exposing internal state through a more
        invasive interface.
        """
        return getattr(self, "_last_probability", 0.0)

    def reset(self) -> None:
        """Reset the model's internal LSTM state between distinct utterances."""
        # Also reset the hysteresis state — a fresh utterance starts outside
        # speech and must clear the stricter onset threshold to enter.
        self._inside_speech = False
        try:
            self._model.reset_states()
        except AttributeError:
            pass
