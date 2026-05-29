"""Behaviour tests for the wake-word training recorder.

Covers the WAV writer (format + labelled layout + auto-index) and the mic
capture (mono float32 shape, args propagated, fail-open). sounddevice is faked
so this runs headlessly.
"""

import wave

import numpy as np

from jarvis.listening import wakeword_recorder as rec


def test_save_segment_writes_16k_mono_wav(tmp_path):
    samples = (np.sin(np.linspace(0, 20, 8000)) * 0.5).astype(np.float32)
    path = rec.save_segment(samples, label="1m", base_dir=tmp_path,
                            kind="positive", index=0)
    assert path == tmp_path / "positives" / "1m" / "0000.wav"
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 8000


def test_save_segment_auto_increments_index(tmp_path):
    s = np.zeros(1600, dtype=np.float32)
    p0 = rec.save_segment(s, label="2m", base_dir=tmp_path)
    p1 = rec.save_segment(s, label="2m", base_dir=tmp_path)
    assert p0.name == "0000.wav"
    assert p1.name == "0001.wav"


def test_negative_kind_goes_to_negatives(tmp_path):
    s = np.zeros(1600, dtype=np.float32)
    p = rec.save_segment(s, label="noise", base_dir=tmp_path, kind="negative")
    assert p == tmp_path / "negatives" / "noise" / "0000.wav"


class _FakeSD:
    def __init__(self, buf):
        self._buf = buf
        self.rec_args = None

    def rec(self, frames, **kwargs):
        self.rec_args = (frames, kwargs)
        return self._buf[:frames].reshape(-1, 1)

    def wait(self):
        pass


def test_record_segment_returns_mono_float32():
    buf = np.ones(16000, dtype=np.float32) * 0.2
    fake = _FakeSD(buf)
    out = rec.record_segment(0.5, device=7, sd=fake)
    assert out is not None
    assert out.dtype == np.float32
    assert out.ndim == 1
    assert len(out) == int(0.5 * 16000)
    # samplerate + device propagated to sd.rec
    assert fake.rec_args[1]["samplerate"] == 16000
    assert fake.rec_args[1]["device"] == 7


def test_record_segment_fails_open_on_error():
    class _Boom:
        def rec(self, *a, **k):
            raise OSError("device busy")

        def wait(self):
            pass

    assert rec.record_segment(0.5, device=0, sd=_Boom()) is None
