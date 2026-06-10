# Training a custom "Hey Jarvis" openWakeWord model locally (Windows, RTX 5070 Ti / Blackwell sm_120)

Research date: 2026-05-29. Privacy-first goal: no Colab, no cloud, the user's own voice never leaves the machine.

---

## TL;DR — key decisions

1. **There IS a local-runnable path.** Training is done by `openwakeword/openwakeword/train.py` (a real script/module, not just the Colab notebook). The notebook is only a thin wrapper that calls `train.py` in three phases: `--generate_clips`, `--augment_clips`, `--train_model`. We drive `train.py` directly. Sources: [train.py](https://github.com/dscripka/openWakeWord/blob/main/openwakeword/train.py), [automatic_model_training.ipynb](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb).

2. **The classifier is PyTorch, not TensorFlow.** `train.py` defines `class Model(nn.Module)`, picks `torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')`, trains with `optim.Adam`, and exports with `torch.onnx.export`. TensorFlow (`tensorflow-cpu==2.8.1` + `onnx_tf`) is used **only** to convert the ONNX model into a `.tflite` file. **We do not need a `.tflite`**, so we skip the entire TensorFlow/onnx_tf branch — which is exactly the part that is a 2022-era dependency nightmare. This is the single most important decision in this whole exercise.

3. **The model jarvis loads is ONNX-only.** `openwakeword.Model(wakeword_models=[...], inference_framework="onnx")` needs our `hey_jarvis.onnx` plus two preprocessor models (`melspectrogram.onnx`, `embedding_model.onnx`) that the package auto-downloads on first use. So ONNX is the right and sufficient target.

4. **Blackwell (sm_120) is fine for the parts that touch the GPU.** The classifier head is tiny (a few dense layers over precomputed embeddings) — it trains in well under a minute even on CPU, so GPU support is a non-issue for the classifier. The GPU genuinely helps only Piper synthesis and feature extraction, both of which use PyTorch / ONNX Runtime. The machine already runs Chatterbox TTS on CUDA, which means a Blackwell-capable torch (≥2.7 built with CUDA 12.8, i.e. `cu128`) is already installed. **PyTorch with `cu128` officially supports sm_120 in stable releases** (ptrblck, PyTorch maintainer: "All of our binaries built with CUDA 12.8 support Blackwell architectures"). Source: [PyTorch forums sm_120 thread](https://discuss.pytorch.org/t/nvidia-geforce-rtx-5070-ti-with-cuda-capability-sm-120/221509).

5. **The 2022-era pins (`torch==1.13.1`, `tensorflow-cpu==2.8.1`, `onnx_tf==1.10.0`) DO NOT need to be honoured if we go ONNX-only.** Those pins exist for the tflite conversion path and break on Python 3.12 and modern torch. On **Python 3.11** with a **modern torch ≥2.7+cu128**, the generate/augment/train/export-to-ONNX path works, but a few `torchaudio ≥2.1` API removals (`torchaudio.load/info/list_audio_backends`) need small soundfile-based shims. The community trainer [lgpearson1771/openwakeword-trainer](https://github.com/lgpearson1771/openwakeword-trainer) ships exactly these patches and is the best reference for making modern torch work.

6. **Native Windows has one hard blocker: `piper-phonemize` ships Linux-only wheels.** Piper synthesis (positive clip generation) effectively requires **WSL2 Ubuntu** (which gives transparent CUDA passthrough to the 5070 Ti). The cleanest privacy-preserving plan is: do Piper generation + augmentation + training **inside WSL2**, everything stays on the local disk. Pure-native-Windows is possible only if you pre-generate positives another way (e.g. our own recordings only, or build piper-phonemize from source — not recommended).

**Recommended route:** WSL2 Ubuntu + the `lgpearson1771/openwakeword-trainer` patched pipeline (or hand-driven `train.py`), ONNX-only output, GPU via cu128 torch, our 55-60 real utterances mixed in as extra positives after splitting. Rough cost: ~17-20 GB data download, ~13-20k synthetic positives, total wall-clock 1-4 h (mostly synthesis + augmentation; classifier training is minutes).

---

## 1. The current custom-training pipeline

openWakeWord (repo [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord)) provides automated training. There are three "front doors", all calling the same `train.py`:

- `notebooks/automatic_model_training.ipynb` — the Colab/automation notebook (OFF the table for us, but its cells show the exact commands).
- `notebooks/training_models.ipynb` — the educational, more-customisable notebook.
- **`openwakeword/openwakeword/train.py`** — the actual script. **This is the local-runnable path.** There is no separately published `openwakeword.train` console entry point; you invoke the file directly.

### The exact ordered phases (verbatim from the notebook)

```bash
# Phase 1: synthesise positive + adversarial-negative clips with Piper TTS
python openwakeword/openwakeword/train.py --training_config my_model.yaml --generate_clips

# Phase 2: augment clips (RIR + background noise) and extract mel/embedding features → .npy
python openwakeword/openwakeword/train.py --training_config my_model.yaml --augment_clips

# Phase 3: train the DNN classifier and export to ONNX (+ tflite if TF is present)
python openwakeword/openwakeword/train.py --training_config my_model.yaml --train_model
```

What each phase does (from `train.py` source):
- `--generate_clips`: `generate_adversarial_texts()` + `generate_samples()` → writes 16 kHz mono `.wav` into the positive/negative output dirs.
- `--augment_clips`: `augment_clips()` applies RIR + background noise; `compute_features_from_generator()` writes memory-mapped `.npy` feature arrays (mel → Google speech embedding).
- `--train_model`: `auto_train()` runs three training sub-sequences with progressive LR decay and negative-example weighting; then `export_model()` runs `torch.onnx.export(...)`; `convert_onnx_to_tflite()` optionally produces tflite via `onnx_tf.backend.prepare()` + `tf.lite.TFLiteConverter` (skippable).

Output: `<output_dir>/<model_name>.onnx` (and `.tflite` if TF available). On recent code the ONNX is emitted as a small graph plus external weights (`model_name.onnx` ~14 KB + `model_name.onnx.data` ~200 KB) — keep both files together.

### Status / known breakage
The stock notebook is fragile in 2025-26 ([issue #296](https://github.com/dscripka/openWakeWord/issues/296)):
- `ModuleNotFoundError: No module named 'piper'` / `generate_samples() missing 1 required positional argument: 'model'` (piper-sample-generator v2 API change — pass `model=...`).
- `ValueError: Error! Clip does not have the correct sample rate!` in augmentation (Piper now emits 22050 Hz; needs resample to 16 kHz).
- `FileNotFoundError: positive_features_test.npy` (a downstream symptom of the above).
- `torchaudio` backend functions deprecated/removed ≥2.1, broken by ~2.9/2.10.

All of these are fixed by the patched community trainer (Section 2).

---

## 2. Local training dependencies + Blackwell compatibility

### Framework split (the crucial point)
| Stage | Framework | Touches GPU? | Blackwell concern? |
|-------|-----------|--------------|--------------------|
| Piper synthesis (positives/negatives) | PyTorch | Yes (optional) | Needs cu128 torch for GPU; CPU works, slower |
| Feature extraction (mel + embedding) | ONNX Runtime over bundled `.onnx` | CPU by default (`AudioFeatures(device='cpu')`); GPU optional | None — CPU is fine |
| Classifier training | **PyTorch** (`nn.Module`, Adam) | Yes if available, else CPU | Tiny model → CPU fine, no concern |
| ONNX export | **PyTorch** (`torch.onnx.export`) | CPU | None |
| tflite export (OPTIONAL — SKIP) | TensorFlow-CPU + onnx_tf | CPU only | The dependency nightmare; skip it |

### Stock pinned install list (from the notebook — for reference, NOT what we'll use as-is)
```bash
pip install mutagen==1.47.0 torchinfo==1.8.0 torchmetrics==1.2.0 \
            speechbrain==0.5.14 audiomentations==0.33.0 torch-audiomentations==0.11.0 \
            acoustics==0.2.6 tensorflow-cpu==2.8.1 tensorflow_probability==0.16.0 \
            onnx_tf==1.10.0 pronouncing==0.2.0 datasets==2.14.6 \
            deep-phonemizer==0.0.19 piper-phonemize webrtcvad
# plus the historic torch==1.13.1 the pipeline was authored against
```
These pins assume Python 3.11 (the ceiling for `tflite-runtime` prebuilt wheels and several others). They break on 3.12+. `tensorflow-cpu==2.8.1` + `tensorflow_probability==0.16.0` + `onnx_tf==1.10.0` is the known-good trio **only if you insist on tflite output**.

### What we actually install (ONNX-only, modern torch, Python 3.11)
```bash
# Keep the Blackwell-capable torch already on the machine (cu128). If installing fresh:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install openwakeword onnx onnxruntime \
            mutagen torchinfo torchmetrics speechbrain audiomentations \
            torch-audiomentations acoustics pronouncing datasets webrtcvad
# piper-sample-generator + piper-phonemize (Linux/WSL2 wheels) for synthesis
# NO tensorflow-cpu / tensorflow_probability / onnx_tf  → tflite branch skipped
```

### Blackwell / sm_120 verdict
- **PyTorch:** stable wheels built with **CUDA 12.8 (`cu128`) support sm_120**. Use `torch ≥2.7+cu128` (the machine likely already has this since Chatterbox runs on CUDA). The classic error "RTX 5070 Ti with CUDA capability sm_120 is not compatible … supports sm_50…sm_90" appears only with an old/CPU torch or a `cu121`/`cu124` wheel. Fix = reinstall from the `cu128` index. Sources: [PyTorch forums](https://discuss.pytorch.org/t/nvidia-geforce-rtx-5070-ti-with-cuda-capability-sm-120/221509), [pytorch/pytorch#164342](https://github.com/pytorch/pytorch/issues/164342).
- **TensorFlow:** even if you wanted tflite, the pinned `tensorflow-cpu==2.8.1` is **CPU-only by design** — it never touches the GPU, so Blackwell is irrelevant to it. TF-GPU on Blackwell is its own minefield; avoid entirely. Since the classifier head is tiny, CPU-only TF for the optional conversion costs seconds.
- **Bottom line:** the only thing that benefits from the 5070 Ti is Piper synthesis (and optional ONNX-Runtime-GPU feature extraction). Everything else is trivially CPU-fast. If GPU synthesis ever misbehaves on sm_120, set `CUDA_VISIBLE_DEVICES=` to force CPU Piper — it just runs slower.

---

## 3. Synthetic positive generation — piper-sample-generator

Two relevant repos: [rhasspy/piper-sample-generator](https://github.com/rhasspy/piper-sample-generator) (current, what `train.py` clones) and the older [dscripka/piper-sample-generator](https://github.com/dscripka/piper-sample-generator). Use the rhasspy one.

### Install + model
```bash
git clone https://github.com/rhasspy/piper-sample-generator
mkdir -p piper-sample-generator/models
wget -O piper-sample-generator/models/en_US-libritts_r-medium.pt \
  'https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt'
pip install -r piper-sample-generator/requirements.txt   # pulls piper-phonemize (Linux/WSL2 wheels)
```

### Generate many "hey jarvis" clips
```bash
python3 -m piper_sample_generator 'hey jarvis.' \
  --model piper-sample-generator/models/en_US-libritts_r-medium.pt \
  --max-samples 1000 --batch-size 100 \
  --output-dir hey_jarvis/
```
- Uses PyTorch; **GPU greatly speeds it up** (~100 samples/s on a 2080 Ti at batch 100 — the 5070 Ti will be much faster). cu128 torch covers Blackwell.
- The libritts_r model produces many distinct synthetic speakers/accents → diverse positives.
- Output WAVs are at the model's native rate (22050 Hz with the v2 model) and **must be resampled to 16 kHz mono** before augmentation (this is the cause of the "incorrect sample rate" bug; the patched trainer auto-resamples).

When run via `train.py --generate_clips`, this step is invoked for you from `n_samples` / `n_samples_val` in the YAML; you normally don't call the generator by hand.

---

## 4. Incorporating OUR OWN recordings as additional positives

### Format the pipeline expects
- **16 kHz, mono, 16-bit PCM WAV**, one utterance per file, roughly **1-2 s** each (the pipeline computes `total_length` from the median positive duration; clips are padded/cropped, min ~32000 samples ≈ 2 s). Our captures are already 16 kHz mono — good.

### Where they go
The stock `train.py` synthesises positives into the positive output dir, then `--augment_clips` augments **whatever WAVs are in that directory**. So the integration pattern (confirmed by community usage, e.g. ~3000 synthetic + ~100 real in [discussion #45](https://github.com/dscripka/openWakeWord/discussions/45)) is:
1. Run `--generate_clips` to create the synthetic positives.
2. **Copy our split 16 kHz real-positive clips into the same positive train (and a few into the positive val) directory** before running `--augment_clips`. They then get the same RIR/noise augmentation and feature extraction as the synthetic ones, so each real utterance becomes many augmented training examples.
3. The CoreWorxLab fork formalises this with a `record_samples.py` and weights user recordings **3× importance**; we can replicate that by duplicating our real clips or by oversampling them in the positive dir. Source: [CoreWorxLab/openwakeword-training](https://github.com/CoreWorxLab/openwakeword-training).

> Note: there is **no dedicated YAML key** for "real positives directory" in the stock config — you inject them by placing files into the positive output dir between phases 1 and 2. (Confirmed: `custom_model.yml` documents synthetic generation + negatives, not a real-positives path.)

### Splitting our 35 s segments into individual utterances
Each `~/.local/share/jarvis/wakeword/positives/<distance>/0000.wav` holds ~13 utterances. Split on silence with **pydub** (simplest) or **librosa** (dynamic threshold). pydub example:

```python
from pydub import AudioSegment
from pydub.silence import split_on_silence
from pathlib import Path

src = Path.home() / ".local/share/jarvis/wakeword/positives"
out = Path.home() / ".local/share/jarvis/wakeword/positives_split"
out.mkdir(parents=True, exist_ok=True)

idx = 0
for wav in src.rglob("*.wav"):
    audio = AudioSegment.from_wav(wav).set_frame_rate(16000).set_channels(1)
    chunks = split_on_silence(
        audio,
        min_silence_len=300,      # ms of silence between utterances — tune
        silence_thresh=audio.dBFS - 16,  # relative threshold — tune per distance
        keep_silence=150,         # leave a little head/tail
    )
    for c in chunks:
        # pad/normalise length to ~1.5 s if very short
        c.export(out / f"{idx:05d}.wav", format="wav")
        idx += 1
print("wrote", idx, "clips")
```
- Tune `min_silence_len` / `silence_thresh` per distance folder (the 3 m files are quieter — lower the relative threshold). librosa's `librosa.effects.split(y, top_db=...)` is an alternative that auto-calibrates the threshold (default `top_db=60`; raise for noisier far-field clips).
- 55-60 segments × ~13 = **~715-780 raw real positives** — plenty as a real-voice supplement to the synthetic set. After augmentation (`augmentation_rounds`) these multiply further.
- Sanity-check a handful by ear; drop any chunk that clipped two utterances together or cut one in half.

Sources: [pydub split_on_silence](https://www.codespeedy.com/split-audio-files-using-silence-detection-in-python/), [librosa.effects.split](https://librosa.org/doc/main/generated/librosa.effects.split.html).

---

## 5. Augmentation + negative/background datasets

### Augmentation (in `--augment_clips`)
- **RIR / reverberation:** convolve clips with Room Impulse Responses to simulate far-field. Configured via `rir_paths`.
- **Background noise mixing:** mix speech/noise/music at realistic SNRs (the pre-trained models targeted ~5-10 dB). Configured via `background_paths`.
- **Gain / other:** handled by `audiomentations` / `torch-audiomentations`.
- `augmentation_rounds` = how many augmented copies per source clip; `augmentation_batch_size` = batch size for the augmentation pass.

### Datasets the pipeline downloads
| Purpose | Dataset | Source / id | Approx size |
|---------|---------|-------------|-------------|
| RIR (reverb) | MIT environmental impulse responses | HF `davidscripka/MIT_environmental_impulse_responses` | small (tens of MB) |
| Background noise/music | AudioSet (one shard) | HF `agkphysics/AudioSet`, e.g. `bal_train09.tar` | a few GB per shard |
| Background music | Free Music Archive (small) | HF `rudraml/fma` | ~a few GB |
| Negative features (precomputed) | ACAV100M features ~2000 h | `openwakeword_features_ACAV100M_2000_hrs_16bit.npy` | several GB |
| FP validation features (~11 h) | `validation_set_features.npy` | HF (dscripka) | ~hundreds of MB |

Total realistically **~17-20 GB** (CoreWorxLab cites ~17 GB via its `setup-data.sh`). Sources: [automatic_model_training.ipynb](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb), [CoreWorxLab](https://github.com/CoreWorxLab/openwakeword-training).

### Smaller alternatives
- Use a **single AudioSet shard** (one `bal_train*.tar`) instead of many — adequate for a personal model.
- The **precomputed ACAV100M + validation `.npy` feature files are the heavy/critical negatives**; you can't easily shrink these without hurting false-accept performance, but they download once and are reused across all future models.
- For RIR, the MIT set is already small; no need to substitute.

---

## 6. Output model format + how jarvis loads it

### Format
Target **ONNX** (`hey_jarvis.onnx`, possibly with a sibling `hey_jarvis.onnx.data` weights file on recent code — keep them together). **Do not bother with `.tflite`** for jarvis. tflite only matters for the Wyoming/Home-Assistant path and microcontrollers; jarvis uses `inference_framework="onnx"`.

### Loading in the `openwakeword` package (exact)
```python
import openwakeword
from openwakeword.model import Model

# One-time (or first-run): fetch the bundled preprocessor models.
openwakeword.utils.download_models()   # melspectrogram.onnx + embedding_model.onnx

model = Model(
    wakeword_models=["C:/path/to/hey_jarvis.onnx"],
    inference_framework="onnx",
)
# inference
prediction = model.predict(audio_frame_int16)   # dict keyed by model name → score
```
- `AudioFeatures` (used internally) loads `resources/models/melspectrogram.onnx` and `resources/models/embedding_model.onnx` from the installed package dir, auto-downloading them via `download_models()` if absent. Our trained `hey_jarvis.onnx` is the **classifier head only**; it relies on those two preprocessors at runtime — so they must exist (they will, after the package's first download or after running training, which uses them too).
- The key under which scores appear is the model filename stem (`hey_jarvis`). The Wyoming wrapper auto-strips version suffixes (e.g. `hey_jarvis_v2.onnx` → id `hey_jarvis`); the raw `openwakeword` package keys by the path/stem you pass.

This matches exactly how jarvis already calls it (`Model(wakeword_models=[<model_path>], inference_framework="onnx")`), so **no app-side change is needed** beyond pointing at the new `.onnx`. Sources: [openWakeWord utils.py](https://github.com/dscripka/openWakeWord/blob/main/openwakeword/utils.py), [Wyoming custom-model loading](https://context7.com/rhasspy/wyoming-openwakeword/llms.txt).

---

## 7. Concrete LOCAL runbook (Windows + WSL2 + RTX 5070 Ti + our recordings)

> Privacy note: every step runs on the local machine (WSL2 is local). Our voice WAVs never leave the disk. Only impersonal background/RIR/feature datasets are downloaded from Hugging Face.

### Why WSL2
`piper-phonemize` (needed for Piper synthesis) ships **Linux-only wheels**; native Windows has no prebuilt wheel. WSL2 Ubuntu gives transparent CUDA passthrough to the 5070 Ti, so the GPU still accelerates Piper. The trained `.onnx` is just a file we copy back to the Windows side for jarvis to load. (If you truly want zero WSL, you'd have to skip Piper and train on our real positives only — viable but a weaker model.)

### Step 0 — prep (Windows)
- Split our recordings into per-utterance 16 kHz mono clips using the pydub/librosa script in Section 4. Output to a folder, e.g. `C:\Users\aggel\wakeword\real_positives\`. (~700-780 clips; minutes.)
- `wsl --install -d Ubuntu` if not already present; verify GPU inside WSL: `wsl` then `nvidia-smi` (should list the 5070 Ti).

### Step 1 — environment (inside WSL2 Ubuntu, Python 3.11)
```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv ffmpeg git wget
python3.11 -m venv ~/.oww-venv && source ~/.oww-venv/bin/activate
pip install --upgrade pip
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128   # Blackwell sm_120
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
Recommended: use the patched pipeline to avoid the torchaudio/piper/speechbrain breakage:
```bash
git clone https://github.com/lgpearson1771/openwakeword-trainer
cd openwakeword-trainer
pip install -r requirements.txt        # applies/auto-installs the compat patches
python train_wakeword.py --list-steps  # confirm the 13 steps
```
(Or, to hand-drive the stock repo: `git clone https://github.com/dscripka/openWakeWord`, `pip install -e .`, plus the install list from Section 2, and apply the torchaudio shims yourself.)

### Step 2 — config
Create/edit a YAML (copy `examples/custom_model.yml` or the trainer's `configs/*.yaml`). Minimal keys:
```yaml
model_name: "hey_jarvis"
target_phrase: ["hey jarvis"]
n_samples: 20000          # 20k+ recommended; can start at ~5-10k for a quick first pass
n_samples_val: 2000
custom_negative_phrases: ["hey", "jarvis", "hey gemini", "hey google", "okay"]  # near-misses
output_dir: "./hey_jarvis_model"
rir_paths: ["./mit_rirs"]
background_paths: ["./audioset_16k", "./fma"]
false_positive_validation_data_path: "./validation_set_features.npy"
feature_data_files: { "ACAV100M_sample": "./openwakeword_features_ACAV100M_2000_hrs_16bit.npy" }
augmentation_rounds: 1
augmentation_batch_size: 16
steps: 10000
layer_size: 32
```
Each key is documented in [`examples/custom_model.yml`](https://github.com/dscripka/openWakeWord/blob/main/examples/custom_model.yml).

### Step 3 — download datasets (Section 5)
Run the trainer's `download` step (`python train_wakeword.py --from download` or its `setup-data.sh`), or fetch the HF datasets listed in Section 5 manually into the paths referenced by the YAML. **~17-20 GB, one-time** (reused for future words). Time: depends on bandwidth (tens of minutes to a couple of hours).

### Step 4 — generate synthetic positives
```bash
python openwakeword/openwakeword/train.py --training_config hey_jarvis.yaml --generate_clips
# (the patched trainer runs this as its `generate` step)
```
GPU-accelerated Piper; minutes for thousands of clips on the 5070 Ti.

### Step 5 — inject OUR real positives (the privacy win)
Copy the split real clips from Step 0 into the positive **train** dir created by Step 4 (e.g. `./hey_jarvis_model/positive_train/`), and a small slice into the positive **val** dir. Optionally duplicate them 2-3× to mimic CoreWorxLab's 3× weighting. (See Section 4.)

### Step 6 — augment + extract features
```bash
python openwakeword/openwakeword/train.py --training_config hey_jarvis.yaml --augment_clips
```
Applies RIR + background noise to synthetic **and** our real clips, writes `.npy` features. This is the slowest CPU-bound step (can be 10s of minutes to ~an hour depending on `n_samples` × `augmentation_rounds`).

### Step 7 — train + export ONNX
```bash
python openwakeword/openwakeword/train.py --training_config hey_jarvis.yaml --train_model
```
Tiny DNN over precomputed embeddings → trains in **minutes** (GPU or CPU). Produces `./hey_jarvis_model/hey_jarvis.onnx` (+ `.onnx.data` on recent code). The tflite conversion may emit a TF warning/skip if TF isn't installed — that's fine, we don't need it.

### Step 8 — verify + deploy to jarvis
```bash
python - <<'PY'
import openwakeword; from openwakeword.model import Model
m = Model(wakeword_models=["./hey_jarvis_model/hey_jarvis.onnx"], inference_framework="onnx")
print("loaded:", list(m.models.keys()))
PY
```
Then copy `hey_jarvis.onnx` (and `.onnx.data` if present) to the Windows side and point jarvis's wakeword model path at it. No code change — jarvis already uses `Model(wakeword_models=[path], inference_framework="onnx")`. Test live at 0.3/1/2/3 m; if far-field recall is low, increase `augmentation_rounds`, add more real far-field positives, or raise `n_samples`.

### Caveats checklist
- ❗ **Python 3.11 only** (3.12 breaks piper-phonemize / tflite-runtime wheels). Make the WSL venv 3.11.
- ❗ **Use the `cu128` torch index** for Blackwell; verify `torch.cuda.is_available()` before trusting GPU synthesis. CPU fallback works but is slower.
- ❗ **Skip TensorFlow/onnx_tf** — don't install them; the tflite step is optional and is the main source of dependency hell.
- ❗ **Resample Piper output to 16 kHz** before augmentation (the patched trainer does this; the stock notebook bug is exactly this).
- ❗ **Keep `hey_jarvis.onnx` + `hey_jarvis.onnx.data` together** if the export produces external weights.
- ❗ The **preprocessor models** (`melspectrogram.onnx`, `embedding_model.onnx`) must be present at inference — run `openwakeword.utils.download_models()` once on the jarvis machine.
- ℹ️ **Disk:** ~17-20 GB datasets (one-time) + a few GB of generated/augmented clips/features. **Time:** ~1-4 h end-to-end first run (download + synth + augment dominate; training itself is minutes).
- ℹ️ If you want to avoid WSL entirely and accept a weaker model, you can train on **our real positives only** (skip Piper) on native Windows — but synthetic diversity materially improves robustness, so WSL+Piper is recommended.

---

## Sources

- openWakeWord repo / README: https://github.com/dscripka/openWakeWord
- Automatic training notebook (commands, pins, datasets): https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb
- `train.py` (PyTorch classifier, phases, ONNX export): https://github.com/dscripka/openWakeWord/blob/main/openwakeword/train.py
- `utils.py` (model loading, preprocessor auto-download): https://github.com/dscripka/openWakeWord/blob/main/openwakeword/utils.py
- Documented config keys: https://github.com/dscripka/openWakeWord/blob/main/examples/custom_model.yml
- Notebook breakage / fixes (issue #296): https://github.com/dscripka/openWakeWord/issues/296
- Real-positives + synthetic experience (discussion #45): https://github.com/dscripka/openWakeWord/discussions/45
- piper-sample-generator (rhasspy, current): https://github.com/rhasspy/piper-sample-generator
- piper-sample-generator (dscripka, older README): https://github.com/dscripka/piper-sample-generator
- Modern patched local trainer (torchaudio 2.10+/piper/speechbrain patches, ONNX, WSL2): https://github.com/lgpearson1771/openwakeword-trainer
- Local trainer with real-voice recording + 3× weighting (Docker/CUDA): https://github.com/CoreWorxLab/openwakeword-training
- Cross-platform trainer w/ Streamlit UI (Win one-liner, but WSL for piper): https://github.com/IT-BAER/hawake-wakeword
- PyTorch sm_120 / Blackwell support (cu128): https://discuss.pytorch.org/t/nvidia-geforce-rtx-5070-ti-with-cuda-capability-sm-120/221509
- PyTorch sm_120 tracking issue: https://github.com/pytorch/pytorch/issues/164342
- Wyoming custom-model loading (Context7): https://context7.com/rhasspy/wyoming-openwakeword/llms.txt
- Splitting audio on silence (pydub): https://www.codespeedy.com/split-audio-files-using-silence-detection-in-python/
- librosa.effects.split: https://librosa.org/doc/main/generated/librosa.effects.split.html
