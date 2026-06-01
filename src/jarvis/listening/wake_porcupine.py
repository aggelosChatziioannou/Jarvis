"""Porcupine-backed wake word detector — always-on, low-latency, low-CPU.

Picovoice Porcupine listens for a single wake word ("jarvis") continuously
in a dedicated thread. When it fires, we mark `_wake_timestamp` exactly
the same way the Whisper backend's transcript-based detector does, so the rest
of the listener pipeline (intent judge → reply engine) is unchanged. (The live
Wispr backend detects wake with openWakeWord, not this path.)

Why bother:
  - Detection latency drops from ~500ms (Whisper segment) to ~30ms (Porcupine frame).
  - Zero false negatives on the literal word "jarvis" — no fuzzy-match guessing.
  - CPU-only, so no VRAM contention with Whisper/Chatterbox/Ollama models.

Setup:
  1. Free Picovoice account at https://console.picovoice.ai/
  2. Copy your AccessKey from the dashboard
  3. Add to mcps/.env:  PICOVOICE_ACCESS_KEY=...
  4. pip install pvporcupine sounddevice  (sounddevice already required)
  5. Set "porcupine_enabled": true in config.json
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from ..debug import debug_log


class PorcupineWakeDetector:
    """Wake-word listener that runs Porcupine on the default microphone.

    Calls `on_wake()` on a worker thread whenever the wake word is detected.
    Callers should make `on_wake()` thread-safe (it typically just sets a
    timestamp on the parent listener).
    """

    def __init__(
        self,
        access_key: str,
        on_wake: Callable[[float], None],
        keyword: str = "jarvis",
        sensitivity: float = 0.6,
        device: Optional[int | str] = None,
    ) -> None:
        self._access_key = access_key
        self._on_wake = on_wake
        self._keyword = keyword
        self._sensitivity = max(0.0, min(1.0, sensitivity))
        self._device = device
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._porcupine = None
        self._stream: Optional[sd.InputStream] = None

    def start(self) -> bool:
        """Initialize Porcupine + audio stream. Return True on success."""
        try:
            import pvporcupine
        except ImportError:
            debug_log("pvporcupine not installed — Porcupine wake disabled", "wake")
            return False
        try:
            self._porcupine = pvporcupine.create(
                access_key=self._access_key,
                keywords=[self._keyword],
                sensitivities=[self._sensitivity],
            )
        except Exception as e:
            debug_log(f"Porcupine init failed: {e}", "wake")
            return False

        try:
            self._stream = sd.InputStream(
                samplerate=self._porcupine.sample_rate,
                blocksize=self._porcupine.frame_length,
                channels=1,
                dtype="int16",
                device=self._device,
            )
            self._stream.start()
        except Exception as e:
            debug_log(f"Porcupine audio stream failed: {e}", "wake")
            self._porcupine.delete()
            self._porcupine = None
            return False

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="PorcupineWake"
        )
        self._thread.start()
        debug_log(
            f"Porcupine listening for '{self._keyword}' (sensitivity={self._sensitivity})",
            "wake",
        )
        return True

    def _loop(self) -> None:
        assert self._porcupine is not None
        assert self._stream is not None
        frame_length = self._porcupine.frame_length
        last_trigger_ts = 0.0
        debounce_sec = 1.0  # ignore retriggers within 1 s

        while not self._stop.is_set():
            try:
                data, overflowed = self._stream.read(frame_length)
                if overflowed:
                    debug_log("Porcupine audio overflow", "wake")
                pcm = np.frombuffer(data, dtype=np.int16).flatten()
                if len(pcm) != frame_length:
                    continue
                result = self._porcupine.process(pcm.tolist())
                if result >= 0:
                    now = time.time()
                    if now - last_trigger_ts > debounce_sec:
                        last_trigger_ts = now
                        debug_log(
                            f"Porcupine wake detected at {now:.3f}", "wake"
                        )
                        try:
                            self._on_wake(now)
                        except Exception as e:
                            debug_log(f"Porcupine on_wake callback error: {e}", "wake")
            except Exception as e:
                debug_log(f"Porcupine loop error: {e}", "wake")
                time.sleep(0.1)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                debug_log(f"Porcupine stream close error: {e}", "wake")
            self._stream = None
        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None
        debug_log("Porcupine wake detector stopped", "wake")


def create_porcupine_from_config(cfg, on_wake: Callable[[float], None]) -> Optional[PorcupineWakeDetector]:
    """Construct + start a PorcupineWakeDetector from Jarvis config + .env.

    Returns the detector on success, or None if disabled / setup incomplete.
    """
    if not getattr(cfg, "porcupine_enabled", False):
        return None
    access_key = os.environ.get("PICOVOICE_ACCESS_KEY", "").strip()
    if not access_key:
        # Try loading from mcps/.env (same file MCPs use)
        from pathlib import Path
        env_path = Path("C:/Users/aggel/Jarvis/mcps/.env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.strip().startswith("PICOVOICE_ACCESS_KEY"):
                    _, _, val = line.partition("=")
                    access_key = val.strip().strip('"').strip("'")
                    break
    if not access_key:
        debug_log("Porcupine enabled but PICOVOICE_ACCESS_KEY not set", "wake")
        return None

    sensitivity = float(getattr(cfg, "porcupine_sensitivity", 0.6))
    detector = PorcupineWakeDetector(
        access_key=access_key,
        on_wake=on_wake,
        keyword="jarvis",
        sensitivity=sensitivity,
    )
    if detector.start():
        return detector
    return None
