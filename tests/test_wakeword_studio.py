"""Behaviour tests for the Wake-word Recording Studio (wakeword-training/studio).

The studio guides the user through a structured recording programme and emits
trainer-ready clips + a manifest. These tests cover the pure, deterministic
parts: audio QC, session-plan generation/resume, manifest round-trip and the
export that feeds the existing openWakeWord injector
(``positives_split/<bucket>/*.wav``, 16 kHz mono 16-bit, >= 1.0 s).

The interactive CLI (mic capture, keyboard flow) is exercised separately via
``record_studio.py --simulate`` which synthesises audio instead of recording.
"""

import json
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

# The studio lives outside src/ (it is a training utility, not app runtime).
_STUDIO_PARENT = Path(__file__).resolve().parents[1] / "wakeword-training"
if str(_STUDIO_PARENT) not in sys.path:
    sys.path.insert(0, str(_STUDIO_PARENT))

from studio import qc  # noqa: E402
from studio.manifest import (  # noqa: E402
    append_row,
    completed_prompt_ids,
    export_positives_for_trainer,
    load_rows,
)
from studio.session_plan import (  # noqa: E402
    PlanConfig,
    build_plan,
    load_reading_script,
    remaining_items,
)

SR = 16000


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _speechlike(duration_s: float = 2.0, level: float = 0.2) -> np.ndarray:
    """Silence + a modulated burst + silence — passes the 'actually spoke' gate."""
    n = int(duration_s * SR)
    a = np.zeros(n, dtype=np.float32)
    s, e = int(0.4 * SR), int(min(duration_s - 0.4, 1.4) * SR)
    t = np.arange(e - s) / SR
    burst = level * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    a[s:e] = burst.astype(np.float32)
    a += np.random.default_rng(0).normal(0, 1e-4, n).astype(np.float32)
    return a


# ---------------------------------------------------------------------------
# QC
# ---------------------------------------------------------------------------

class TestQC:
    def test_good_clip_passes(self):
        report = qc.analyse(_speechlike(), SR, rms_floor_dbfs=-50.0)
        assert report.ok, report.problems
        assert report.peak < 0.99
        assert report.rms_dbfs > -50.0

    def test_clipping_detected(self):
        a = _speechlike()
        a[int(0.5 * SR):int(0.6 * SR)] = 1.0  # hard-clipped run
        report = qc.analyse(a, SR, rms_floor_dbfs=-50.0)
        assert not report.ok
        assert any("clip" in p for p in report.problems)

    def test_too_quiet_detected(self):
        a = _speechlike(level=0.001)  # ~ -60 dBFS burst
        report = qc.analyse(a, SR, rms_floor_dbfs=-45.0)
        assert not report.ok
        assert any("quiet" in p for p in report.problems)

    def test_no_speech_detected(self):
        a = np.random.default_rng(1).normal(0, 0.002, 2 * SR).astype(np.float32)
        report = qc.analyse(a, SR, rms_floor_dbfs=-80.0)
        assert not report.ok
        assert any("speech" in p for p in report.problems)

    def test_trim_pad_pads_short_clips_to_one_second(self, tmp_path):
        a = _speechlike(0.6)
        out = qc.trim_pad(a, SR)
        assert len(out) >= SR

    def test_trim_pad_trims_long_silence_edges(self):
        n = int(4.0 * SR)
        a = np.zeros(n, dtype=np.float32)
        s, e = int(1.8 * SR), int(2.6 * SR)
        t = np.arange(e - s) / SR
        a[s:e] = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
        out = qc.trim_pad(a, SR)
        assert len(out) < int(2.5 * SR)  # edges gone, ~0.8s voice + pads
        assert len(out) >= SR

    def test_save_wav_writes_trainer_format(self, tmp_path):
        p = tmp_path / "x.wav"
        qc.save_wav(_speechlike(), SR, p)
        with wave.open(str(p)) as w:
            assert w.getframerate() == SR
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getnframes() >= SR


# ---------------------------------------------------------------------------
# Reading script asset
# ---------------------------------------------------------------------------

class TestReadingScript:
    def test_shipped_script_is_valid(self):
        lines = load_reading_script()
        ids = [l["id"] for l in lines]
        assert len(ids) == len(set(ids)), "duplicate line ids"
        assert len(lines) >= 45
        langs = {l["lang"] for l in lines}
        assert langs == {"el", "en"}
        traps = [l for l in lines if l["kind"] == "trap"]
        assert len(traps) >= 10
        # Traps must never contain the actual wake phrase.
        for t in traps:
            assert "hey jarvis" not in t["text"].lower()
        # Every line is non-empty, single-line text.
        for l in lines:
            assert l["text"].strip() and "\n" not in l["text"]


# ---------------------------------------------------------------------------
# Session plan
# ---------------------------------------------------------------------------

class TestSessionPlan:
    def test_full_plan_counts_follow_config(self):
        cfg = PlanConfig()
        plan = build_plan(cfg)
        positives = [i for i in plan if i.label == "positive"]
        expected_clean = len(cfg.distances) * sum(cfg.clean_styles.values())
        expected_noisy = sum(
            len(cfg.noisy_distances) * reps for reps in cfg.noisy_positive_reps.values()
        )
        assert len(positives) == expected_clean + expected_noisy

    def test_prompt_ids_unique_and_stable(self):
        plan1 = build_plan(PlanConfig())
        plan2 = build_plan(PlanConfig())
        ids1 = [i.prompt_id for i in plan1]
        assert len(ids1) == len(set(ids1)), "prompt ids must be unique"
        assert ids1 == [i.prompt_id for i in plan2], "plan must be deterministic"

    def test_every_positive_says_the_wake_phrase(self):
        for item in build_plan(PlanConfig()):
            if item.label == "positive":
                assert "hey jarvis" in item.say_text.lower()

    def test_clean_reading_pass_covers_every_script_line_once(self):
        plan = build_plan(PlanConfig())
        clean_reads = [
            i for i in plan if i.label in ("negative", "trap") and i.noise == "quiet"
        ]
        script_ids = {l["id"] for l in load_reading_script() if l["kind"] == "read"}
        covered = {i.script_line_id for i in clean_reads if i.label == "negative"}
        assert covered == script_ids

    def test_beds_present_for_each_noise_condition(self):
        plan = build_plan(PlanConfig())
        beds = {i.noise for i in plan if i.label == "bed"}
        assert "quiet" in beds
        assert any(n.startswith("music") for n in beds)

    def test_remaining_items_skips_completed_prompts(self):
        plan = build_plan(PlanConfig())
        done = {plan[0].prompt_id, plan[2].prompt_id}
        remaining = remaining_items(plan, done)
        rem_ids = {i.prompt_id for i in remaining}
        assert plan[0].prompt_id not in rem_ids
        assert plan[2].prompt_id not in rem_ids
        assert len(remaining) == len(plan) - 2


# ---------------------------------------------------------------------------
# Manifest + export
# ---------------------------------------------------------------------------

def _row(prompt_id: str, label: str, *, file: str, distance: str = "1m",
         noise: str = "quiet", text: str = "hey jarvis") -> dict:
    return {
        "prompt_id": prompt_id, "take": 1, "file": file, "label": label,
        "text": text, "lang": "en", "phase": "p1", "distance": distance,
        "noise": noise, "style": "normal", "samplerate": SR,
        "duration_s": 2.0, "rms_dbfs": -25.0, "peak": 0.4, "ts": "2026-06-12T12:00:00",
    }


class TestManifest:
    def test_roundtrip_preserves_greek_text(self, tmp_path):
        m = tmp_path / "manifest.jsonl"
        append_row(m, _row("s_el_001", "negative", file="a.wav",
                           text="Τι ώρα είναι τώρα;"))
        rows = load_rows(m)
        assert rows[0]["text"] == "Τι ώρα είναι τώρα;"

    def test_completed_counts_each_prompt_once_across_takes(self, tmp_path):
        m = tmp_path / "manifest.jsonl"
        append_row(m, _row("p1_x", "positive", file="a.wav"))
        append_row(m, {**_row("p1_x", "positive", file="b.wav"), "take": 2})
        append_row(m, _row("p1_y", "positive", file="c.wav"))
        assert completed_prompt_ids(load_rows(m)) == {"p1_x", "p1_y"}

    def test_export_buckets_positives_by_distance_and_noise(self, tmp_path):
        session = tmp_path / "session"
        clips = session / "clips"
        clips.mkdir(parents=True)
        m = session / "manifest.jsonl"
        for name, dist, noise, label in [
            ("a.wav", "1m", "quiet", "positive"),
            ("b.wav", "3m", "music_med", "positive"),
            ("c.wav", "1m", "quiet", "negative"),
        ]:
            qc.save_wav(_speechlike(), SR, clips / name)
            append_row(m, _row(f"p_{name}", label, file=f"clips/{name}",
                               distance=dist, noise=noise))
        out = tmp_path / "positives_split"
        n = export_positives_for_trainer(session, out)
        assert n == 2
        assert (out / "1m_quiet").is_dir()
        assert (out / "3m_music_med").is_dir()
        exported = list(out.rglob("*.wav"))
        assert len(exported) == 2  # negatives never exported as positives
        with wave.open(str(exported[0])) as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SR, 1, 2)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
