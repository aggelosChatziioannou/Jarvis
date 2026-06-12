# Wake-word training

Two halves live here:

- **`studio/` — committed.** The guided Recording Studio: resumable,
  QC-at-capture recording sessions that produce trainer-ready wake-word data
  (real positives across distances/noise, known-text negatives, phonetic-trap
  hard negatives, room-ambience beds). Generic over the wake phrase — see
  `studio/studio.spec.md`. Run it with the project venv:

  ```
  .venv\Scripts\python.exe wakeword-training\studio\record_studio.py
  ```

- **Everything else — local-only, gitignored.** One-off scripts + config from
  the custom **"Hey Jarvis"** openWakeWord training session that produced the
  shipped `hey_jarvis.onnx`. These are **WSL-path hardcoded**
  (`~/openwakeword-trainer`, `/mnt/c/...`) and are NOT part of the app or the
  test suite. Kept locally for reproducibility.

The shipped model lives at `~/.config/jarvis/wakeword/hey_jarvis.onnx` and is
referenced by config `wispr_wake_model`. Recordings land under
`~/.local/share/jarvis/wakeword/studio_sessions/` — never in the repo.

## Pipeline order

1. `_split_wakeword.py` — energy-segment per-distance "Hey Jarvis" recordings
   into individual utterance clips (`~/.local/share/jarvis/wakeword/positives_split/`).
2. `_inject_real_positives.py` — inject the user's real far-field clips into the
   trainer's `positive_train/` before augmentation.
3. `_fetch_rirs.py` — fetch MIT RIR impulse responses (room reverb) for
   augmentation (works around `datasets` `trust_remote_code` removal).
4. `_hey_jarvis.yaml` — **the openWakeWord training config** (target phrase,
   negatives, n_samples, RIR/background paths, hyperparams). The single source
   of truth that produced the shipped model. Train via the openWakeWord trainer
   using this config.
5. Post-train evaluation:
   - `_recall_check.py` — recall / false-activation check over held-out real
     clips. (Its `PRIME_SEC` silence-priming method is mirrored, by name, in
     shipped code: `src/jarvis/listening/wispr_bridge.py` `_prime_wake_model`.)
   - `_clip_eval.py` — overfitting check (`predict_clip` on saved arrays).
   - `_direct_eval.py` — direct ONNX classifier eval on saved feature `.npy`.

## How wake detection actually works in the app

The live wake path is **openWakeWord** (this custom `hey_jarvis.onnx`) running on
CPU inside `WisprBridge` (`src/jarvis/listening/wispr_bridge.py`), fed every
80 ms frame, with a consecutive-frame debounce + threshold gate. See
`src/jarvis/listening/listening.spec.md` and `docs/voice-pipeline.md`.
