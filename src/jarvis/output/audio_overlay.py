"""Background audio overlay — plays a WAV file in parallel with TTS.

Used by easter eggs ("daddy's home") where we want a piece of music
to play under the assistant's spoken greeting. Built on sounddevice so
it shares no state with pygame.mixer (which the TTS owns); the OS audio
mixer composes the two streams.

Threading model:
  - .play(wav, volume) returns immediately, audio runs in a background
    thread until end of file or .stop().
  - .stop() returns within ~50 ms for hard stops, or after fade_out_sec
    for graceful fade-outs.
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
    """Single-stream background WAV player using sounddevice.

    Supports:
      - Per-chunk dynamic volume (duck / unduck while playing)
      - Smooth fade-in, fade-out, and cross-fades
      - Graceful stop with configurable fade length
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stream: Optional[sd.OutputStream] = None

        # Dynamic volume state (mutable from any thread, read in _play_loop)
        self._samplerate: int = 0
        self._base_volume: float = 1.0
        self._current_volume: float = 1.0
        self._target_volume: float = 1.0
        self._volume_ramp_start: float = 1.0
        self._volume_ramp_end_sample: int = 0
        self._volume_ramp_sample: int = 0
        self._fade_out: bool = False

    def play(self, wav_path: str | Path, volume: float = 0.6, fade_in_sec: float = 0.3) -> None:
        """Start playback of `wav_path` in a background thread.

        Args:
            wav_path: Path to a WAV file.
            volume: Base volume, 0.0 (mute) to 1.0 (full).
            fade_in_sec: Linear ramp at the start, hides any startup click.
        """
        wav_path = Path(wav_path)
        if not wav_path.exists():
            debug_log(f"audio overlay: file not found {wav_path}", "tune")
            return

        with self._lock:
            self._stop_locked()
            self._stop.clear()
            self._fade_out = False
            self._thread = threading.Thread(
                target=self._play_loop,
                args=(wav_path, float(volume), float(fade_in_sec)),
                daemon=True,
                name="AudioOverlay",
            )
            self._thread.start()

    def duck(self, ratio: float = 0.5, fade_sec: float = 0.3) -> None:
        """Lower volume to ``base * ratio`` over ``fade_sec``.

        Args:
            ratio: 0.0 (mute) to 1.0 (no change).
            fade_sec: Duration of the fade-down.
        """
        with self._lock:
            if self._samplerate <= 0 or not self.is_playing():
                return
            self._target_volume = self._base_volume * float(np.clip(ratio, 0.0, 1.0))
            self._volume_ramp_start = self._current_volume
            self._volume_ramp_end_sample = max(1, int(self._samplerate * fade_sec))
            self._volume_ramp_sample = 0

    def unduck(self, fade_sec: float = 1.5) -> None:
        """Restore volume to base over ``fade_sec``."""
        with self._lock:
            if self._samplerate <= 0 or not self.is_playing():
                return
            self._target_volume = self._base_volume
            self._volume_ramp_start = self._current_volume
            self._volume_ramp_end_sample = max(1, int(self._samplerate * fade_sec))
            self._volume_ramp_sample = 0

    def stop(self, fade_out_sec: float = 0.5) -> None:
        """Stop playback.

        If ``fade_out_sec > 0`` and audio is still playing, a graceful
        fade-out is performed before the stream closes.
        """
        with self._lock:
            if fade_out_sec > 0 and self._samplerate > 0 and self.is_playing():
                self._target_volume = 0.0
                self._volume_ramp_start = self._current_volume
                self._volume_ramp_end_sample = max(1, int(self._samplerate * fade_out_sec))
                self._volume_ramp_sample = 0
                self._fade_out = True
            else:
                self._stop.set()

    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _stop_locked(self) -> None:
        """Internal: hard-stop the current thread; caller already holds the lock."""
        if self._thread is not None and self._thread.is_alive():
            self._stop.set()
            try:
                if self._stream is not None:
                    self._stream.abort(ignore_errors=True)
            except Exception:
                pass
            self._thread.join(timeout=1.0)
            self._thread = None

    def _apply_volume(self, chunk: np.ndarray) -> np.ndarray:
        """Apply dynamic volume to a chunk, handling ramps.  Returns modified chunk."""
        chunk_len = chunk.shape[0]

        if (
            self._volume_ramp_end_sample > 0
            and self._volume_ramp_sample < self._volume_ramp_end_sample
        ):
            # We are inside a volume transition — compute per-sample ramp
            ramp_samples = min(chunk_len, self._volume_ramp_end_sample - self._volume_ramp_sample)
            t_start = self._volume_ramp_sample / self._volume_ramp_end_sample
            t_end = (self._volume_ramp_sample + ramp_samples) / self._volume_ramp_end_sample
            vol_start = self._volume_ramp_start + t_start * (
                self._target_volume - self._volume_ramp_start
            )
            vol_end = self._volume_ramp_start + t_end * (
                self._target_volume - self._volume_ramp_start
            )

            if ramp_samples < chunk_len:
                # Ramp only covers part of the chunk; rest is at target
                ramp = np.linspace(vol_start, vol_end, ramp_samples, dtype=np.float32)
                chunk[:ramp_samples] *= ramp[:, None]
                chunk[ramp_samples:] *= self._target_volume
            else:
                ramp = np.linspace(vol_start, vol_end, chunk_len, dtype=np.float32)
                chunk *= ramp[:, None]

            self._volume_ramp_sample += ramp_samples
            if self._volume_ramp_sample >= self._volume_ramp_end_sample:
                self._current_volume = self._target_volume
            else:
                self._current_volume = vol_end
        else:
            chunk *= self._target_volume
            self._current_volume = self._target_volume

        return chunk

    def _play_loop(self, wav_path: Path, volume: float, fade_in_sec: float) -> None:
        try:
            data, samplerate = sf.read(str(wav_path), dtype="float32", always_2d=True)
            total_samples = data.shape[0]
            channels = data.shape[1]
            self._samplerate = int(samplerate)

            # Initialise volume state
            self._base_volume = float(np.clip(volume, 0.0, 1.0))
            self._target_volume = self._base_volume
            self._current_volume = 0.0 if fade_in_sec > 0 else self._base_volume
            self._volume_ramp_start = self._current_volume
            self._volume_ramp_end_sample = (
                max(1, int(samplerate * fade_in_sec)) if fade_in_sec > 0 else 0
            )
            self._volume_ramp_sample = 0
            self._fade_out = False

            # Chunked output so we can poll the stop event between blocks
            block = 4096
            idx = 0
            self._stream = sd.OutputStream(
                samplerate=samplerate, channels=channels, dtype="float32"
            )
            self._stream.start()

            while idx < total_samples:
                # Hard stop (no fade-out) → exit immediately
                if self._stop.is_set() and not self._fade_out:
                    break

                end = min(idx + block, total_samples)
                chunk = data[idx:end].copy()
                chunk = self._apply_volume(chunk)
                self._stream.write(chunk)
                idx = end

                # Fade-out completed and we're silent → can stop early
                if self._fade_out and self._current_volume <= 0.001:
                    break

            # Drain
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
        finally:
            self._fade_out = False
            self._samplerate = 0


_singleton: Optional[AudioOverlay] = None
_singleton_lock = threading.Lock()


def get_overlay() -> AudioOverlay:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = AudioOverlay()
        return _singleton
