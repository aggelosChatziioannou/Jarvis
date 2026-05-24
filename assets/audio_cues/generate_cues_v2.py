"""Generate SMOOTH, WARM procedural audio cues for Jarvis — v2.

Design goals:
- Lower fundamentals (warmth, not aggression)
- Slow attack (no sharp edges)
- Rich harmonics (FM synthesis, Karplus-Strong strings)
- Bell/chime character instead of bloops
- Subtle, organic, "premium" feel
"""

from __future__ import annotations
import io
import struct
import numpy as np
from pathlib import Path

SAMPLE_RATE = 44100


def _save_wav(samples: np.ndarray, path: Path) -> None:
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
    buf.write(struct.pack('<H', 1))
    buf.write(struct.pack('<H', num_channels))
    buf.write(struct.pack('<I', SAMPLE_RATE))
    buf.write(struct.pack('<I', byte_rate))
    buf.write(struct.pack('<H', block_align))
    buf.write(struct.pack('<H', bits_per_sample))
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm.tobytes())
    path.write_bytes(buf.getvalue())


def _env_adsr(n: int, attack_ms: float, decay_ms: float, sustain: float, release_ms: float) -> np.ndarray:
    """ADSR envelope with smooth curves."""
    attack_n = int(SAMPLE_RATE * attack_ms / 1000)
    decay_n = int(SAMPLE_RATE * decay_ms / 1000)
    release_n = int(SAMPLE_RATE * release_ms / 1000)
    sustain_n = max(0, n - attack_n - decay_n - release_n)

    env = np.zeros(n, dtype=np.float64)
    i = 0
    if attack_n > 0:
        a = min(attack_n, n)
        env[i:i+a] = np.linspace(0, 1, a) ** 2  # quadratic = smoother
        i += a
    if decay_n > 0 and i < n:
        d = min(decay_n, n - i)
        env[i:i+d] = 1.0 - (1.0 - sustain) * np.linspace(0, 1, d) ** 2
        i += d
    if sustain_n > 0 and i < n:
        s = min(sustain_n, n - i)
        env[i:i+s] = sustain
        i += s
    if release_n > 0 and i < n:
        r = min(release_n, n - i)
        env[i:i+r] = sustain * (1.0 - np.linspace(0, 1, r) ** 2)
    return env


def _fm_bell(freq: float, duration_s: float = 2.0, amp: float = 0.5,
             ratio: float = 3.5, index: float = 2.0) -> np.ndarray:
    """FM synthesis bell — rich harmonics, exponential decay.

    Classic bell timbre: carrier + modulator with high index.
    ratio=3.5 gives inharmonic overtones (like real bells).
    """
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE

    # Exponential decay (bells ring for a while)
    decay = np.exp(-t * 3.5)

    # FM: sin(ωc·t + β·sin(ωm·t))
    mod = index * np.sin(2 * np.pi * freq * ratio * t)
    s = amp * np.sin(2 * np.pi * freq * t + mod) * decay

    # Add a gentle overtone for shimmer
    mod2 = (index * 0.5) * np.sin(2 * np.pi * freq * ratio * 1.618 * t)
    overtone = amp * 0.25 * np.sin(2 * np.pi * freq * 2.0 * t + mod2) * decay

    return (s + overtone) * _env_adsr(n, attack_ms=15, decay_ms=80, sustain=0.0, release_ms=duration_s * 1000 - 95)


def _karplus_strong(freq: float, duration_s: float = 1.5, amp: float = 0.4) -> np.ndarray:
    """Plucked string synthesis — warm, organic, guitar/harp-like.

    Uses Karplus-Strong algorithm: noise burst through comb filter.
    """
    n = int(SAMPLE_RATE * duration_s)
    delay = int(SAMPLE_RATE / freq)
    if delay < 2:
        delay = 2

    # Initial noise burst
    buf = np.random.uniform(-1, 1, delay)
    out = np.zeros(n, dtype=np.float64)

    # Lowpass coefficient for damping (0.4-0.6 = warm, not too bright)
    alpha = 0.52

    for i in range(n):
        out[i] = buf[i % delay]
        # Average with previous = lowpass filter
        buf[i % delay] = alpha * 0.5 * (buf[i % delay] + buf[(i - 1) % delay])

    # Shape envelope: fast attack, long decay
    env = _env_adsr(n, attack_ms=3, decay_ms=200, sustain=0.0, release_ms=duration_s * 1000 - 203)
    return amp * out * env


def _soft_pad(freqs: tuple[float, ...], duration_s: float = 3.0, amp: float = 0.3) -> np.ndarray:
    """Warm pad with slow attack — no sharp edges at all."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE

    # Very slow LFO for movement
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.3 * t)

    s = np.zeros(n, dtype=np.float64)
    for i, f in enumerate(freqs):
        detune = 1.0 + (i - len(freqs)/2) * 0.003
        phase = np.cumsum(2 * np.pi * f * detune / SAMPLE_RATE * np.ones(n))
        # Add a little vibrato
        vibrato = np.sin(2 * np.pi * 4 * t) * 2.0
        phase += vibrato
        s += np.sin(phase)

    s = (s / len(freqs)) * amp * lfo
    # Very slow fade in/out
    env = _env_adsr(n, attack_ms=600, decay_ms=100, sustain=0.7, release_ms=800)
    return s * env


def _water_drop(freq: float, duration_s: float = 1.2, amp: float = 0.4) -> np.ndarray:
    """Water droplet / crystal ping — very smooth, pure.

    Sine with frequency glide (drops slightly) + exponential decay.
    """
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE

    # Frequency glides down slightly (like a water drop)
    freq_glide = freq * (1.0 - 0.08 * (1.0 - np.exp(-t * 8)))
    phase = np.cumsum(2 * np.pi * freq_glide / SAMPLE_RATE)

    # Exponential decay
    decay = np.exp(-t * 4)

    # Add a gentle 2nd harmonic for body
    s = amp * (0.75 * np.sin(phase) + 0.25 * np.sin(phase * 2)) * decay
    return s * _env_adsr(n, attack_ms=5, decay_ms=50, sustain=0.0, release_ms=duration_s * 1000 - 55)


def _soft_thud(freq: float, duration_s: float = 0.4, amp: float = 0.3) -> np.ndarray:
    """Soft muted thud — low, gentle, no harshness."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE

    # Sine burst + noise burst mixed
    decay = np.exp(-t * 10)
    sine = np.sin(2 * np.pi * freq * t) * decay
    noise = np.random.uniform(-1, 1, n) * decay * 0.3

    s = amp * (sine + noise)
    return s * _env_adsr(n, attack_ms=2, decay_ms=30, sustain=0.0, release_ms=duration_s * 1000 - 32)


def _gentle_swell(freq: float, duration_s: float = 2.5, amp: float = 0.25) -> np.ndarray:
    """Very gentle pad swell — almost subliminal."""
    n = int(SAMPLE_RATE * duration_s)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE

    phase = np.cumsum(2 * np.pi * freq / SAMPLE_RATE * np.ones(n))
    # Add slow vibrato
    vibrato = np.sin(2 * np.pi * 2.5 * t) * 1.5
    s = amp * np.sin(phase + vibrato)

    # Super slow attack and release
    env = _env_adsr(n, attack_ms=1200, decay_ms=200, sustain=0.5, release_ms=800)
    return s * env


# ─────────────────────────────────────────────────────────────────────────────
# Sound designs — v2 (warm & smooth)
# ─────────────────────────────────────────────────────────────────────────────

def make_wake_ack(path: Path) -> None:
    """Warm crystal bell — 'I heard you, gently'

    Usage: After wake word accepted. Soft, inviting, not startling.
    """
    # Water-drop style at a pleasant mid-low frequency
    s = _water_drop(523.25, duration_s=0.9, amp=0.35)  # C5
    _save_wav(s, path)


def make_searching(path: Path) -> None:
    """Soft plucked harp strings — 'Working on it...'

    Usage: Before slow tool execution. Organic, not digital.
    """
    # Two plucked notes: A3 then E4 (perfect 5th — very consonant)
    note1 = _karplus_strong(220.0, duration_s=1.0, amp=0.25)   # A3
    note2 = _karplus_strong(329.63, duration_s=1.0, amp=0.20)  # E4

    # Overlap them with slight delay
    total_n = int(SAMPLE_RATE * 2.0)
    s = np.zeros(total_n, dtype=np.float64)
    n1 = note1.size
    n2 = note2.size
    s[:n1] += note1
    delay = int(SAMPLE_RATE * 0.25)  # 250ms between notes
    s[delay:delay + n2] += note2
    _save_wav(s, path)


def make_tool_success(path: Path) -> None:
    """Gentle wind chime — 'All good'

    Usage: Tool success. 3 soft bells in major triad.
    """
    # C major arpeggio but with bell timbre and spacing
    c = _fm_bell(523.25, duration_s=1.5, amp=0.22, ratio=3.5, index=1.8)
    e = _fm_bell(659.25, duration_s=1.5, amp=0.18, ratio=3.5, index=1.8)
    g = _fm_bell(783.99, duration_s=1.5, amp=0.15, ratio=3.5, index=1.8)

    total_n = int(SAMPLE_RATE * 2.5)
    s = np.zeros(total_n, dtype=np.float64)
    s[:c.size] += c
    d2 = int(SAMPLE_RATE * 0.18)
    s[d2:d2 + e.size] += e
    d3 = int(SAMPLE_RATE * 0.36)
    s[d3:d3 + g.size] += g
    _save_wav(s, path)


def make_tool_fail(path: Path) -> None:
    """Soft muted string — 'Hmm, not quite'

    Usage: Tool failure. Lower, descending feel, but gentle.
    """
    # Single low plucked string, slightly detuned for "uncertainty"
    s = _karplus_strong(164.81, duration_s=1.2, amp=0.25)  # E3
    _save_wav(s, path)


def make_hot_window_open(path: Path) -> None:
    """Barely-there pad swell — 'Still here...'

    Usage: Hot window opens. Subliminal, doesn't compete with ambience.
    """
    s = _gentle_swell(349.23, duration_s=2.5, amp=0.15)  # F4
    _save_wav(s, path)


def make_listening(path: Path) -> None:
    """Single soft chime — 'Go on...'

    Usage: Follow-up detected. Very brief, polite.
    """
    s = _fm_bell(659.25, duration_s=1.0, amp=0.18, ratio=3.2, index=1.5)  # E5 bell
    _save_wav(s, path)


def make_stop_ack(path: Path) -> None:
    """Soft thud — 'OK, done'

    Usage: Stop command. Quick but not harsh.
    """
    s = _soft_thud(150.0, duration_s=0.35, amp=0.25)
    _save_wav(s, path)


def make_wake_reject(path: Path) -> None:
    """Very gentle ping — 'Noted, but ignored'

    Usage: False positive. So subtle you barely notice.
    """
    s = _water_drop(440.0, duration_s=0.6, amp=0.12)
    _save_wav(s, path)


# ─────────────────────────────────────────────────────────────────────────────
# Bonus: thinking tune variant (more ambient, less "ahh choir")
# ─────────────────────────────────────────────────────────────────────────────

def make_thinking_ambient(path: Path) -> None:
    """Alternative thinking tune — ambient drone instead of choir pad.

    Usage: Could replace or alternate with the default thinking tune.
    """
    # D minor 7 chord — warm, contemplative
    freqs = (146.83, 220.0, 293.66, 349.23)  # D3, A3, D4, F4
    s = _soft_pad(freqs, duration_s=4.0, amp=0.18)
    _save_wav(s, path)


SOUNDS = {
    "wake_ack.wav": make_wake_ack,
    "searching.wav": make_searching,
    "tool_success.wav": make_tool_success,
    "tool_fail.wav": make_tool_fail,
    "hot_window_open.wav": make_hot_window_open,
    "listening.wav": make_listening,
    "stop_ack.wav": make_stop_ack,
    "wake_reject.wav": make_wake_reject,
    # Bonus
    "thinking_ambient.wav": make_thinking_ambient,
}


if __name__ == "__main__":
    out_dir = Path(__file__).parent
    for filename, maker in SOUNDS.items():
        path = out_dir / filename
        maker(path)
        size_kb = path.stat().st_size / 1024
        print(f"  Generated {filename} ({size_kb:.1f} KB)")
    print(f"\nAll {len(SOUNDS)} cues generated in: {out_dir}")
