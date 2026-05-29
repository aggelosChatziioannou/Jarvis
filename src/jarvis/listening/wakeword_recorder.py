"""Guided recorder for custom 'Hey Jarvis' wake-word training data.

Captures the user's own voice as 16 kHz mono WAVs in a labelled layout ready for
openWakeWord training. We record a CONTINUOUS segment per distance (the user
repeats "Hey Jarvis" a handful of times during the window) rather than per-take
clips, because the session is driven from a headless context where the user
cannot see a live terminal prompt — the cadence is coordinated over chat, and
the offline training step segments each window into individual utterances.

Layout (under base_dir, default ~/.local/share/jarvis/wakeword):
    positives/<label>/0000.wav, 0001.wav, ...     # label = distance, e.g. "1m"
    negatives/<label>/0000.wav, ...               # label = "noise", "speech", ...

Privacy: recordings stay local. Nothing leaves the machine unless the user
explicitly uploads it for training.
"""

from __future__ import annotations

import argparse
import os
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from ..debug import debug_log

SAMPLE_RATE = 16000          # openWakeWord requires 16 kHz mono
DEFAULT_SECONDS = 25.0


def default_base_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".local" / "share" / "jarvis" / "wakeword"


def save_segment(samples, *, label: str, base_dir, kind: str = "positive",
                 index: Optional[int] = None) -> Path:
    """Write a float32 [-1,1] mono array as a 16 kHz mono int16 WAV.

    Lands at ``<base_dir>/<positives|negatives>/<label>/<index:04d>.wav``. When
    ``index`` is None the next free index for that label is used (so repeated
    sessions append rather than overwrite).
    """
    sub = "positives" if kind == "positive" else "negatives"
    out_dir = Path(base_dir) / sub / label
    out_dir.mkdir(parents=True, exist_ok=True)
    if index is None:
        index = len(list(out_dir.glob("*.wav")))
    path = out_dir / f"{index:04d}.wav"
    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = np.clip(arr * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return path


def _resolve_input_device():
    """Resolve the persisted wake mic to a sounddevice index (fail-open None)."""
    try:
        from ..output import audio_devices
        from ..config import load_settings
        cfg = load_settings()
        return audio_devices.resolve_endpoint_to_sd_index(
            getattr(cfg, "audio_input_endpoint_id", "") or "",
            getattr(cfg, "audio_input_name", "") or "",
            kind="input",
        )
    except Exception as e:
        debug_log(f"wakeword_recorder: device resolve failed ({e!r})", "voice")
        return None


def record_segment(seconds: float = DEFAULT_SECONDS, *, device=None, sd=None) -> Optional[np.ndarray]:
    """Record ``seconds`` of 16 kHz mono audio. Returns float32 mono or None.

    ``device`` defaults to the persisted wake mic; ``sd`` is injectable for
    tests. Fail-open: any error returns None (logged), never raises.
    """
    if sd is None:
        try:
            import sounddevice as sd  # type: ignore
        except Exception as e:
            debug_log(f"wakeword_recorder: sounddevice unavailable ({e!r})", "voice")
            return None
    if device is None:
        device = _resolve_input_device()
    try:
        frames = int(seconds * SAMPLE_RATE)
        rec = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1,
                     dtype="float32", device=device)
        sd.wait()
        return np.asarray(rec, dtype=np.float32).reshape(-1)
    except Exception as e:
        debug_log(f"wakeword_recorder: record failed ({e!r})", "voice")
        return None


def _main() -> None:
    p = argparse.ArgumentParser(
        description="Record custom 'Hey Jarvis' wake-word training data")
    p.add_argument("--label", required=True,
                   help="distance label for positives (e.g. 0.3m, 1m, 2m, 3m) "
                        "or a negative label (noise, speech)")
    p.add_argument("--kind", choices=["positive", "negative"], default="positive")
    p.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    p.add_argument("--base-dir", default=None)
    p.add_argument("--countdown", type=int, default=3)
    args = p.parse_args()

    base = Path(args.base_dir) if args.base_dir else default_base_dir()
    print(f"🎙️  Recording {args.seconds:.0f}s for {args.kind}/{args.label}", flush=True)
    if args.kind == "positive":
        reps = max(8, int(args.seconds / 2))
        print(f"   Say 'Hey Jarvis' clearly ~{reps}× with a short pause between each.",
              flush=True)
    else:
        print("   Stay quiet / make normal room noise (do NOT say 'Hey Jarvis').",
              flush=True)
    for c in range(args.countdown, 0, -1):
        print(f"   starting in {c}...", flush=True)
        time.sleep(1.0)
    print("   🔴 GO", flush=True)

    samples = record_segment(args.seconds)
    if samples is None:
        print("   ⚠️  recording failed (no mic?) — check Audio I/O settings", flush=True)
        return
    path = save_segment(samples, label=args.label, kind=args.kind, base_dir=base)
    print(f"   ✅ saved {len(samples) / SAMPLE_RATE:.1f}s -> {path}", flush=True)


if __name__ == "__main__":
    _main()
