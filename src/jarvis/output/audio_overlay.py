"""Background audio overlay — plays a WAV file in parallel with TTS.

Used by easter eggs ("daddy's home") where we want a piece of music
to play under the assistant's spoken greeting. Built on sounddevice so
it shares no state with pygame.mixer (which the TTS owns); the OS audio
mixer composes the two streams.

Threading model:
  - .play(wav, volume) returns immediately, audio runs in a background
    thread until end of file or .stop().
  - .stop() returns within ~50ms.
  - Calling .play() again replaces the current playback.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from ..debug import debug_log


class AudioOverlay:
    """Single-stream background WAV player using sounddevice."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stream: Optional[sd.OutputStream] = None

    def play(self, wav_path: str | Path, volume: float = 0.6, fade_in_sec: float = 0.3) -> None:
        """Start playback of `wav_path` in a background thread.

        Args:
            wav_path: Path to a WAV file.
            volume: 0.0 (mute) to 1.0 (full).
            fade_in_sec: Linear ramp at the start, hides any click.
        """
        wav_path = Path(wav_path)
        if not wav_path.exists():
            debug_log(f"audio overlay: file not found {wav_path}", "tune")
            return

        with self._lock:
            self._stop_locked()
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._play_loop,
                args=(wav_path, float(volume), float(fade_in_sec)),
                daemon=True,
                name="AudioOverlay",
            )
            self._thread.start()

    def stop(self, fade_out_sec: float = 0.5) -> None:
        """Stop playback. fade_out_sec applies if the player thread observes it."""
        with self._lock:
            self._stop.set()
            # Best-effort fade-out by lowering stream volume isn't supported
            # directly; let the player loop handle a graceful tail if running.
            time.sleep(min(0.05, max(0.0, fade_out_sec / 10)))

    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _stop_locked(self) -> None:
        """Internal: stop the current thread; caller already holds the lock."""
        if self._thread is not None and self._thread.is_alive():
            self._stop.set()
            try:
                if self._stream is not None:
                    self._stream.abort(ignore_errors=True)
            except Exception:
                pass
            self._thread.join(timeout=1.0)
            self._thread = None

    def _play_loop(self, wav_path: Path, volume: float, fade_in_sec: float) -> None:
        try:
            data, samplerate = sf.read(str(wav_path), dtype="float32", always_2d=True)
            data = data * float(np.clip(volume, 0.0, 1.0))
            # Apply linear fade-in to mask any startup click
            if fade_in_sec > 0:
                ramp_len = min(int(samplerate * fade_in_sec), data.shape[0])
                if ramp_len > 0:
                    ramp = np.linspace(0.0, 1.0, ramp_len, dtype=np.float32)
                    data[:ramp_len] *= ramp[:, None]
            channels = data.shape[1]

            # Chunked output so we can poll the stop event between blocks
            block = 4096
            idx = 0
            self._stream = sd.OutputStream(
                samplerate=samplerate, channels=channels, dtype="float32"
            )
            self._stream.start()
            while idx < data.shape[0] and not self._stop.is_set():
                end = min(idx + block, data.shape[0])
                self._stream.write(data[idx:end])
                idx = end
            # Drain whatever pygame buffered (TTS) doesn't matter — sounddevice
            # has its own output stream
            try:
                self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        except Exception as e:
            debug_log(f"audio overlay playback error: {e}", "tune")
            try:
                if self._stream is not None:
                    self._stream.close()
            except Exception:
                pass
            self._stream = None


_singleton: Optional[AudioOverlay] = None
_singleton_lock = threading.Lock()


def get_overlay() -> AudioOverlay:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = AudioOverlay()
        return _singleton
