"""Audio preprocessing for the listener pipeline.

Currently provides only `normalize`, a soft-AGC that boosts weak microphone
signals (dynamic mics like the MAONO PD200X have low inherent output) to a
consistent target RMS so VAD and Whisper see a uniform level. Soft-clip via
tanh prevents hard-clipping at ±1.0 when boosting amplifies natural peaks.

Designed to run on every audio frame in the sounddevice callback (~20 ms
each) so it must stay branch-light and allocation-light: ~10 µs/frame.
"""
from __future__ import annotations

import numpy as np


_SILENCE_RMS_DEAD_ZONE = 1e-6
"""Below this RMS, the frame is treated as silence and passed through unchanged.

Amplifying silence just amplifies the noise floor and would cause the VAD to
chatter on background hum. The dead-zone protects against that.
"""


def normalize(
    frame: np.ndarray,
    target_rms: float = 0.1,
    max_gain: float = 10.0,
) -> np.ndarray:
    """Boost a single mono audio frame toward `target_rms`, never attenuating.

    The gain is clamped to `[1.0, max_gain]`:
    - Gains below 1.0 are clipped to 1.0 so loud speech is never attenuated
      (AGC's job here is to rescue weak signals, not to compress dynamics).
    - Gains above `max_gain` are clipped so very low-noise inputs don't get
      amplified into an explosion of noise.

    When applying the gain would push any sample past ±0.95, a soft-clip via
    `tanh` is applied to bend the peaks back inside ±1.0 without the harsh
    artefacts of hard clipping.
    """
    if frame is None or frame.size == 0:
        return frame

    rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
    if rms < _SILENCE_RMS_DEAD_ZONE:
        return frame

    gain = target_rms / rms
    if gain < 1.0:
        return frame  # signal already at or above target — leave it alone
    if gain > max_gain:
        gain = max_gain

    out = (frame * gain).astype(np.float32, copy=False)
    if float(np.max(np.abs(out))) > 0.95:
        # tanh(x/2)*2 ≈ x near zero, asymptotes to ±2; multiplying preserves loudness
        # of small signals while compressing peaks. After this transform, |out| < ~1.96
        # is possible, so a final hard limit at ±0.99 catches the rare extreme case.
        out = np.tanh(out * 0.5).astype(np.float32, copy=False) * np.float32(2.0)
        np.clip(out, -0.99, 0.99, out=out)
    return out


def normalize_segment(
    audio: np.ndarray,
    target_rms: float = 0.1,
    peak_limit: float = 0.707,
) -> np.ndarray:
    """RMS-based gain normalisation for an already-VAD-gated speech segment.

    This is fundamentally different from `normalize()` above — that one runs
    on every audio frame in the sounddevice callback (continuous AGC), which
    we found regresses Whisper accuracy because it amplifies the noise floor
    during silence frames and interferes with Whisper's internal mel-
    spectrogram normalisation.

    This function operates on a complete *segment* of speech that Silero VAD
    has already identified as containing voice. Bringing the segment to a
    consistent ~-20 dBFS RMS gives Whisper an input in the amplitude range
    its training distribution expects — particularly important for low-
    output dynamic microphones (e.g. MAONO PD200X) where raw segments tend
    to sit 15-25 dB below the typical Whisper training distribution.

    Args:
        audio: float32 mono audio segment, normalised to [-1, 1].
        target_rms: Desired RMS after normalisation. 0.1 ≈ -20 dBFS.
        peak_limit: Hard limit applied after gain. 0.707 ≈ -3 dBFS — leaves
            generous headroom so any sample staying near the peak doesn't
            clip the encoder's input expectations.

    Returns:
        Normalised float32 array of the same shape. Pure silence (RMS below
        the 1e-6 dead zone) is returned untouched.
    """
    if audio is None or audio.size == 0:
        return audio
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    if rms < 1e-6:
        return audio
    gain = target_rms / rms
    # Unlike continuous AGC, here we allow gains < 1 (attenuation) so loud
    # segments are brought down toward target_rms too — the goal is a
    # consistent input level, not just rescuing quiet speech.
    out = (audio * gain).astype(np.float32, copy=False)
    np.clip(out, -peak_limit, peak_limit, out=out)
    return out
