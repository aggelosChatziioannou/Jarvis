"""Per-clip audio quality control — pure numpy, no audio-device dependencies.

Every clip the studio saves must be trainer-ready (16 kHz mono 16-bit, >= 1 s)
and must actually contain speech at a usable level. Catching a bad take the
second it happens (and re-prompting) is the whole point of a *guided* session:
a silent or clipped clip discovered at training time is a wasted recording trip.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_WIN_S = 0.03           # analysis window (matches _split_wakeword.py)
_CLIP_LEVEL = 0.985     # |sample| at/above this counts as clipped
_CLIP_FRACTION = 0.001  # sustained clipping, not a single stray sample
_SPEECH_RATIO = 3.0     # voiced env must rise this far above the floor
_DEAD_PEAK = 0.005      # below this peak there is no signal at all
_PAD_S = 0.15           # context kept around trimmed speech
_MIN_S = 1.0            # openWakeWord trainer expects >= 1.0 s clips
_TRIM_FLOOR_RATIO = 4.0  # voiced threshold above the LOW-percentile floor
_TRIM_FAIL_OPEN_S = 1.5  # trimming a longer take below this keeps the original


@dataclass
class QCReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    peak: float = 0.0
    rms_dbfs: float = -120.0
    duration_s: float = 0.0


def _envelope(audio: np.ndarray, sr: int) -> np.ndarray:
    win = max(1, int(_WIN_S * sr))
    n = len(audio) - win
    if n <= 0:
        return np.array([float(np.sqrt(np.mean(audio**2) + 1e-12))])
    return np.array([
        float(np.sqrt(np.mean(audio[i:i + win] ** 2) + 1e-12))
        for i in range(0, n, win)
    ])


def analyse(audio: np.ndarray, sr: int, *, rms_floor_dbfs: float = -45.0) -> QCReport:
    """Gate a freshly-recorded clip: clipping, level, and did-you-actually-speak.

    ``rms_floor_dbfs`` is condition-dependent (a 4.5 m clip is legitimately much
    quieter than a 0.3 m one) so the caller passes the floor per distance.
    Level is measured over the ACTIVE windows only (top half by energy), so
    leading/trailing silence does not drag a good take below the floor.
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    report = QCReport(ok=True, duration_s=len(audio) / float(sr))
    if not len(audio):
        return QCReport(ok=False, problems=["empty recording"])

    report.peak = float(np.max(np.abs(audio)))
    if report.peak < _DEAD_PEAK:
        # Distinct from "too quiet": there is NOTHING here (muted mic, wrong
        # device, spoke after the window). The CLI must never auto-keep these.
        report.problems.append("no signal (check the microphone / speak during the window)")
        report.ok = False
        return report

    clipped = float(np.mean(np.abs(audio) >= _CLIP_LEVEL))
    if clipped >= _CLIP_FRACTION:
        report.problems.append(f"clipping: {clipped * 100:.1f}% of samples at full scale")

    env = _envelope(audio, sr)
    floor = float(np.median(env))
    env_max = float(np.max(env))
    if env_max < _SPEECH_RATIO * max(floor, 1e-6):
        report.problems.append("no speech detected (energy never rises above the floor)")

    active = env[env >= max(floor, 1e-6)]
    active_rms = float(np.sqrt(np.mean(active**2))) if len(active) else 0.0
    report.rms_dbfs = 20.0 * float(np.log10(max(active_rms, 1e-9)))
    if report.rms_dbfs < rms_floor_dbfs:
        report.problems.append(
            f"too quiet: {report.rms_dbfs:.1f} dBFS (floor {rms_floor_dbfs:.1f})"
        )

    report.ok = not report.problems
    return report


def trim_pad(audio: np.ndarray, sr: int, *, pad_s: float = _PAD_S,
             min_s: float = _MIN_S) -> np.ndarray:
    """Trim long silent edges, keep a little context, pad (centred) to >= min_s.

    The voiced threshold rises from the clip's LOW-percentile floor, NOT the
    median: when speech (or background music) fills the take, the median IS
    the speech level and a median-based threshold sits above the voice —
    live session v2 lost ~70% of 17 reads exactly this way. As a second belt,
    trimming FAILS OPEN: if it would leave under 1.5 s from a meaningfully
    longer take, the original is kept (untrimmed edges cost the trainer
    nothing; destroyed speech costs a re-recording trip).
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    win = max(1, int(_WIN_S * sr))
    env = _envelope(audio, sr)
    floor = float(np.percentile(env, 10))
    thr = max(_TRIM_FLOOR_RATIO * floor, 0.002)
    voiced = np.flatnonzero(env > thr)
    if len(voiced):
        start = max(0, int(voiced[0]) * win - int(pad_s * sr))
        end = min(len(audio), (int(voiced[-1]) + 1) * win + int(pad_s * sr))
        if (end - start) >= int(_TRIM_FAIL_OPEN_S * sr) or len(audio) < int(2.0 * sr):
            audio = audio[start:end]

    min_len = int(min_s * sr)
    if len(audio) < min_len:
        deficit = min_len - len(audio)
        audio = np.concatenate([
            np.zeros(deficit // 2, np.float32),
            audio,
            np.zeros(deficit - deficit // 2, np.float32),
        ])
    return audio


def save_wav(audio: np.ndarray, sr: int, path: Path) -> None:
    """Write trainer-format WAV: 16-bit PCM mono at the given rate."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.asarray(audio, np.float32) * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
