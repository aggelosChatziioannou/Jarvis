# Custom "Hey Jarvis" Wake Word — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development (subagents available) or executing-plans. Strict TDD per task (failing test first). Steps use `- [ ]`.
> **Test runner:** `C:\Users\aggel\Jarvis-src\.venv\Scripts\python.exe -m pytest tests/<file> -v` from repo root. Import `from jarvis.x import ...`.
> **Conventions:** British English, NO em dashes in user-facing strings, emojis OK in CLI prints (NOT in .bat), `from ..debug import debug_log`. Data privacy first (recordings stay local). NEVER call `sd._terminate()/_initialize()` (kills the open Wispr mic stream).

**Goal:** Train the best "Hey Jarvis" detection the PD200X can support — a custom openWakeWord model from the user's own recordings + synthetic + augmentation — and tune the detection path so the user stops having to lean in / repeat.

**Architecture:** Phase 0 tunes the existing path (threshold + a new software wake-gain) and measures a baseline. Phase 1 adds an in-app guided recorder (I can drive it over the user's mic). Phase 2 (offline) trains a custom model from those recordings + synthetic Piper data + augmentation (Colab by default). Phase 3 integrates the model by config + an eval harness that scores detection rate per distance.

**Tech Stack:** sounddevice/PortAudio, openWakeWord, Piper (synthetic), numpy, soundfile, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-custom-wake-word-design.md`

---

## Phase 0 — Baseline tuning (free; the measurement baseline)

### Task 0.1: `wispr_wake_gain` config key
**Files:** Modify `src/jarvis/config.py`; Test `tests/test_config_models.py`
- [ ] Failing test: `wispr_wake_gain` loads with default `1.0` across dataclass + defaults + loader; round-trips a custom value (e.g. `3.0`).
- [ ] Implement the key end-to-end (mirror an existing float key, e.g. `voice_min_energy`). Run (pass). Commit `feat(wakeword): wispr_wake_gain config key`.

### Task 0.2: apply wake gain before the detector (NOT the transcript path)
**Files:** Modify `src/jarvis/listening/wispr_bridge.py` (`_process_wake`); Test `tests/test_wispr_bridge.py`
- [ ] Failing test: with `cfg.wispr_wake_gain = 4.0`, `_process_wake` feeds the wake model audio scaled ~4x (clipped to int16 range), while the VAD/dictation buffers are unaffected. (Inject a fake `wake_model` recording the frames it received; assert amplitude scaled + clipped.)
- [ ] Implement: read `self.wake_gain` in `__init__`; in `_process_wake`, `pcm = np.clip(audio_f32 * 32767.0 * self.wake_gain, -32768, 32767).astype(np.int16)`. Leave `_process_vad` untouched. Run (pass). Commit `feat(wakeword): software wake gain on the detection path only`.

### Task 0.3: lower the default + document tuning
**Files:** the user's config (runtime) + README note
- [ ] Set `wispr_wake_threshold` to `0.3` and `wispr_wake_gain` to a starting value (≈`3.0`) in the user's live config; note Windows mic-level/boost guidance. (Applied via the running daemon's config; restart to load.)
- [ ] Record the BASELINE: with the eval harness (Phase 3) or manual trials, note trigger reliability at 0.3/1/2/3 m BEFORE the custom model.

---

## Phase 1 — In-app guided recorder (the user's data)

### Task 1.1: WAV writer + data layout
**Files:** Create `src/jarvis/listening/wakeword_recorder.py`; Test `tests/test_wakeword_recorder.py`
- [ ] Failing test: `save_clip(samples_float32, kind="positive", label="1.0m", index=3, base_dir=tmp)` writes `tmp/positives/1.0m/0003.wav` as **16 kHz mono int16** (verify with `wave`), values scaled from float32 [-1,1].
- [ ] Implement `save_clip(...)` (soundfile or `wave`). Run (pass). Commit `feat(wakeword): recorder WAV writer + labelled data layout`.

### Task 1.2: capture one clip from the mic (mockable)
**Files:** Modify `wakeword_recorder.py`; Test `tests/test_wakeword_recorder.py`
- [ ] Failing test: `record_clip(seconds=1.5, device=None, sd=fake_sd)` returns a float32 mono array of `~1.5*16000` samples; resolves the mic via `audio_devices.resolve_endpoint_to_sd_index(..., kind="input")` when `device` is None; fails open (returns None + logs) when the mic is absent. (Inject a fake sounddevice that returns a known buffer from `sd.rec`.)
- [ ] Implement `record_clip(...)` using `sd.rec` + `sd.wait` at 16 kHz mono. Run (pass). Commit `feat(wakeword): single-clip mic capture (fail-open)`.

### Task 1.3: guided session (CLI entry I can drive)
**Files:** Modify `wakeword_recorder.py` (add `run_session(...)` + `__main__`); Test `tests/test_wakeword_recorder.py`
- [ ] Failing test: `plan_session(distances=["0.3m","1m","2m","3m"], takes=15, negatives=10)` yields the correct ordered list of prompts (positives per distance + negatives) and total count; `run_session` calls `record_clip` + `save_clip` once per planned prompt (drive with a fake recorder, assert files written per the plan).
- [ ] Implement `plan_session(...)` + `run_session(...)` (prints emoji-led prompts: "🎙️ Say 'Hey Jarvis' at 0.3 m (take 3/15)"; short countdown; record; save). Add `python -m jarvis.listening.wakeword_recorder` entry. Run (pass). Commit `feat(wakeword): guided recording session + CLI`.
- [ ] Manual: I run the CLI over the user's PD200X; the user speaks at each prompted distance; clips land under `~/.local/share/jarvis/wakeword/`.

---

## Phase 2 — Offline training (research-gated)

> Needs a short research pass (current openWakeWord training pipeline + Blackwell vs Colab). Produces a model artifact, not runtime code.

### Task 2.1: research + pin the pipeline
- [ ] Research (Context7 `openwakeword` + web): the current training entrypoint (Colab `automatic_model_training` notebook vs `openwakeword.train`), how to inject the user's recordings as positives, the augmentation knobs (RIR/reverb, noise, gain), and Blackwell (sm_120) local-training feasibility. Write findings to `docs/superpowers/research/2026-05-29-openwakeword-training.md`.

### Task 2.2: training assets + runbook
**Files:** Create `training/wakeword/README.md` (+ a notebook or script)
- [ ] A step-by-step runbook: upload `positives/` + `negatives/`, set the phrase to "hey jarvis", enable augmentation, train, download `hey_jarvis_custom.onnx`. Colab default; local-on-5070Ti appendix if research says it's viable.

---

## Phase 3 — Integration + evaluation

### Task 3.1: load a custom model path
**Files:** Modify `src/jarvis/listening/wispr_bridge.py` (model load) + `src/jarvis/config.py` (`wispr_wake_model` may be a NAME or a FILE PATH); Test `tests/test_wispr_bridge.py`
- [ ] Failing test: when `cfg.wispr_wake_model` is an existing `.onnx` path, the bridge loads openWakeWord with that custom model path; when it is a bare name or missing file, it falls open to the stock model (no crash). (Mock the openWakeWord `Model`.)
- [ ] Implement the path-vs-name resolution + fail-open. Run (pass). Commit `feat(wakeword): load a custom wake model by path with fail-open`.

### Task 3.2: detection-rate eval harness
**Files:** Create `src/jarvis/listening/wakeword_eval.py`; Test `tests/test_wakeword_eval.py`
- [ ] Failing test: `evaluate(clips_dir, model, threshold)` replays each labelled positive clip through the detector and returns detection rate per distance + a false-trigger count over negatives. (Fake detector returning scripted scores.)
- [ ] Implement `evaluate(...)` (reuse the bridge's frame-feeding logic; report a table). Run (pass). Commit `feat(wakeword): detection-rate eval harness (per-distance)`.
- [ ] Manual: run stock vs custom, before vs after tuning; record the numbers in the research doc.

---

## Self-review (vs spec)
- record + synthetic + augmentation → Phases 1, 2. Step-0 tuning → Phase 0. In-app recorder → Phase 1. Integration → Phase 3.1. Eval harness (per-distance) → Phase 3.2. Honest range note carried in the spec. Privacy: recordings local; only the user uploads to Colab by explicit action.
- Out of scope (per spec): far-field hardware, "only-me" verifier, dictation path changes.
