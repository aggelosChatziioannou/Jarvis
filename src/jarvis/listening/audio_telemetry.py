"""Pure helpers for live audio telemetry (console Audio I/O page).

The listener backends publish a small JSON frame (~12 Hz) describing what
Jarvis actually hears: input level, wake-word score, voice activity and a
coarse spectrum. These helpers are pure (no I/O, no state) so the maths is
unit-testable without audio hardware.
"""

from __future__ import annotations

from typing import List, Optional

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is a hard dep in practice
    np = None  # type: ignore


def normalise_rms(rms: float, full_scale: float = 32768.0, gain: float = 1.0) -> float:
    """Map a raw RMS value to 0..1 of full scale, undoing any software gain.

    ``gain`` is the software amplification applied before RMS was computed
    (e.g. the wake-path gain); dividing it out reports the true input level.
    """
    if full_scale <= 0:
        return 0.0
    g = gain if gain > 0 else 1.0
    value = (rms / g) / full_scale
    return max(0.0, min(1.0, value))


def band_spectrum(frame, bands: int = 16, full_scale: float = 32768.0) -> List[float]:
    """Coarse log-spaced magnitude spectrum of one audio frame, each 0..1.

    Cheap enough to run per 80 ms frame; only called when a console client
    is subscribed. Returns all-zeros on any failure (telemetry must never
    break the audio path).
    """
    if np is None:
        return [0.0] * bands
    try:
        samples = np.asarray(frame, dtype=np.float32).flatten()
        if samples.size < 2:
            return [0.0] * bands
        mags = np.abs(np.fft.rfft(samples / full_scale))
        # Log-spaced band edges over the positive-frequency bins (skip DC).
        n = mags.size
        edges = np.unique(
            np.geomspace(1, n - 1, bands + 1).astype(int)
        )
        out: List[float] = []
        for i in range(len(edges) - 1):
            lo, hi = edges[i], max(edges[i] + 1, edges[i + 1])
            # Normalise by frame length so the value is amplitude-like.
            band = float(np.max(mags[lo:hi])) / (samples.size / 4)
            out.append(max(0.0, min(1.0, band)))
        while len(out) < bands:
            out.append(0.0)
        return out[:bands]
    except Exception:
        return [0.0] * bands


def telemetry_frame(
    *,
    rms_norm: float,
    state: str,
    wake_score: Optional[float] = None,
    vad_prob: Optional[float] = None,
    voiced: bool = False,
    spec: Optional[List[float]] = None,
) -> dict:
    """Assemble the wire payload for ``/ws/audio``. Keys are stable API."""
    return {
        "rms": round(float(rms_norm), 5),
        "state": state,
        "wake": round(float(wake_score), 4) if wake_score is not None else None,
        "vad": round(float(vad_prob), 4) if vad_prob is not None else None,
        "voiced": bool(voiced),
        "spec": [round(float(v), 4) for v in (spec or [])],
    }
