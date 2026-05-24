"""Generate procedural audio cue previews for Jarvis.

Run this script to regenerate all WAV files in this folder.
Each sound is synthesized from scratch using numpy — no external assets needed.
"""

from __future__ import annotations
import io
import struct
import numpy as np
from pathlib import Path

SAMPLE_RATE = 44100

def _save_wav(samples: np.ndarray, path: Path) -> None:
    """Save float64 [-1,1] mono samples as 16-bit PCM WAV."""
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    num_samples = pcm.size
    num_channels = 1
    bits_per_sample = 16
    byte_rate = SAMPLE_RATE * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align

    buf = io.BytesIO()
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))
    buf.write(struct.pack('<H', 1))          # PCM
    buf.write(struct.pack('<H', num_channels))
    buf.write(struct.pack('<I', SAMPLE_RATE))
    buf.write(struct.pack('<I', byte_rate))
    buf.write(struct.pack('<H', block_align))
    buf.write(struct.pack('<H', bits_per_sample))
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm.tobytes())
    path.write_bytes(buf.getvalue())


def _fade_in_out(t: np.ndarray, fade_ms: float = 15) -> np.ndarray:
    """Apply short fade-in/out to avoid clicks."""
    n = t.size
    fade_samples = int(SAMPLE_RATE * fade_ms / 1000)
    env = np.ones(n, dtype=np.float64)
    if fade_samples > 0:
        env[:fade_samples] *= np.linspace(0, 1, fade_samples)
        env[-fade_samples:] *= np.linspace(1, 0, fade_samples)
    return env


def _tone(freq: float, duration_s: float, amp: float = 0.5) -> np.ndarray:
    """Pure sine tone."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    s = amp * np.sin(2 * np.pi * freq * t)
    return s * _fade_in_out(t)


def _chord(freqs: tuple[float, ...], duration_s: float, amp: float = 0.4) -> np.ndarray:
    """Sum of sines — a chord."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    s = np.zeros(n, dtype=np.float64)
    for f in freqs:
        s += np.sin(2 * np.pi * f * t)
    s = (s / len(freqs)) * amp
    return s * _fade_in_out(t)


def _arpeggio(freqs: tuple[float, ...], note_dur_s: float, amp: float = 0.4) -> np.ndarray:
    """Arpeggio: each note plays in sequence."""
    note_n = int(SAMPLE_RATE * note_dur_s)
    total_n = note_n * len(freqs)
    s = np.zeros(total_n, dtype=np.float64)
    t_note = np.arange(note_n, dtype=np.float64) / SAMPLE_RATE
    env = _fade_in_out(t_note, fade_ms=8)
    for i, f in enumerate(freqs):
        note = amp * np.sin(2 * np.pi * f * t_note) * env
        s[i * note_n:(i + 1) * note_n] += note
    return s


def _bloop_up(freq1: float, freq2: float, duration_s: float, amp: float = 0.4) -> np.ndarray:
    """Frequency sweep from freq1 to freq2 — a 'bloop'."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    freqs = np.linspace(freq1, freq2, n)
    phase = np.cumsum(2 * np.pi * freqs / SAMPLE_RATE)
    s = amp * np.sin(phase)
    return s * _fade_in_out(t, fade_ms=10)


def _filtered_beeps(freq: float, count: int, bpm: float = 480, amp: float = 0.3) -> np.ndarray:
    """Short data-style blips."""
    note_dur = 60.0 / bpm
    note_n = int(SAMPLE_RATE * note_dur)
    gap_n = int(SAMPLE_RATE * 0.02)
    total_n = count * (note_n + gap_n)
    s = np.zeros(total_n, dtype=np.float64)
    t_note = np.arange(note_n, dtype=np.float64) / SAMPLE_RATE
    env = _fade_in_out(t_note, fade_ms=5)
    for i in range(count):
        note = amp * np.sin(2 * np.pi * freq * t_note) * env
        start = i * (note_n + gap_n)
        s[start:start + note_n] += note
    return s


def _soft_bell(freq: float, duration_s: float = 0.6, amp: float = 0.35) -> np.ndarray:
    """Bell-like tone with exponential decay (rich harmonics)."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Exponential decay envelope
    decay = np.exp(-t * 6)
    # Fundamental + harmonics for bell timbre
    s = (0.60 * np.sin(2 * np.pi * freq * t)
         + 0.25 * np.sin(2 * np.pi * freq * 2 * t)
         + 0.10 * np.sin(2 * np.pi * freq * 3 * t)
         + 0.05 * np.sin(2 * np.pi * freq * 4.2 * t))
    s = s * decay * amp
    return s * _fade_in_out(t, fade_ms=5)


def _subtle_swell(freq: float, duration_s: float = 0.4, amp: float = 0.25) -> np.ndarray:
    """Very gentle upward swell."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Slow attack, quick release
    attack = np.linspace(0, 1, n) ** 2
    release = np.exp(-(t - t[-1] * 0.5) * 8)
    release[:n // 2] = 1.0
    env = attack * release
    s = amp * np.sin(2 * np.pi * freq * t) * env
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Sound designs
# ─────────────────────────────────────────────────────────────────────────────

def make_wake_ack(path: Path) -> None:
    """Friendly ascending major third — 'I heard you!'

    Usage: Right after wake word is detected and accepted by intent judge.
           Plays BEFORE the thinking tune starts.
    """
    s = _bloop_up(440, 554, 0.15, amp=0.35)  # A4 → C#5 (major third up)
    _save_wav(s, path)


def make_searching(path: Path) -> None:
    """Soft data-processing blips — 'Working on it...'

    Usage: When a slow tool is about to run (webSearch, MCP call, screenshot).
           Plays INSTEAD of generic silence during tool execution.
    """
    s = _filtered_beeps(880, count=4, bpm=400, amp=0.22)
    _save_wav(s, path)


def make_tool_success(path: Path) -> None:
    """Positive major arpeggio — 'Done!'

    Usage: When a tool returns successfully (non-error result).
           Very brief — doesn't interrupt flow.
    """
    s = _arpeggio((523.25, 659.25, 783.99), note_dur_s=0.06, amp=0.30)  # C5-E5-G5
    _save_wav(s, path)


def make_tool_fail(path: Path) -> None:
    """Lower, descending minor tone — 'Hmm, that didn't work'

    Usage: When a tool fails, times out, or returns an error.
           Informative but NOT alarming (no buzzer/screech).
    """
    s = _bloop_up(330, 311, 0.18, amp=0.25)  # E4 → D#4 (descending minor)
    _save_wav(s, path)


def make_hot_window_open(path: Path) -> None:
    """Very subtle upward swell — 'I'm still listening...'

    Usage: When hot window activates after TTS finishes.
           Nearly subliminal; just enough to signal 'ready for follow-up'.
    """
    s = _subtle_swell(660, duration_s=0.35, amp=0.15)
    _save_wav(s, path)


def make_listening(path: Path) -> None:
    """Soft bell — 'Go on, I'm listening'

    Usage: When user starts speaking during hot window (follow-up detected).
           Very brief, polite acknowledgment.
    """
    s = _soft_bell(880, duration_s=0.25, amp=0.20)  # A5, short
    _save_wav(s, path)


def make_stop_ack(path: Path) -> None:
    """Quick descending tone — 'OK, stopping'

    Usage: When user says 'stop' / 'quiet' / 'shush' and TTS is interrupted.
           Confirms the stop was received.
    """
    s = _bloop_up(523, 440, 0.10, amp=0.25)  # C5 → A4 (down)
    _save_wav(s, path)


def make_wake_reject(path: Path) -> None:
    """Gentle neutral tone — 'I heard something but not for me'

    Usage: When wake word is detected but intent judge rejects (false positive).
           Lets user know they were heard but no action taken.
    """
    s = _tone(440, 0.08, amp=0.12)
    _save_wav(s, path)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

SOUNDS = {
    "wake_ack.wav": make_wake_ack,
    "searching.wav": make_searching,
    "tool_success.wav": make_tool_success,
    "tool_fail.wav": make_tool_fail,
    "hot_window_open.wav": make_hot_window_open,
    "listening.wav": make_listening,
    "stop_ack.wav": make_stop_ack,
    "wake_reject.wav": make_wake_reject,
}


if __name__ == "__main__":
    out_dir = Path(__file__).parent
    for filename, maker in SOUNDS.items():
        path = out_dir / filename
        maker(path)
        size_kb = path.stat().st_size / 1024
        print(f"  Generated {filename} ({size_kb:.1f} KB)")
    print(f"\nAll {len(SOUNDS)} cues generated in: {out_dir}")
