# Voice Pipeline — Speech‑to‑Text → Reply → Text‑to‑Speech

> **Audience:** developers / AI sessions onboarding to Jarvis. This is the end‑to‑end
> map of how audio comes *in* (STT) and goes *out* (TTS), which files own each stage,
> and which config knobs control it. For deep detail on a stage, follow the linked
> `*.spec.md` (specs live next to the code they describe). The user‑facing `README.md`
> stays product‑focused; this is the engineering view.

## 0. TL;DR flow

```
                ┌─────────────────────────── jarvis.daemon.main() ───────────────────────────┐
                │  builds: db · cfg · tts engine · VoiceListener(thread) · api_server(:38130) │
                └────────────────────────────────────────────────────────────────────────────┘

  🎤 mic ─► VoiceListener ─► [STT backend] ─► transcript ─► feed_transcript()
                                                                   │
                                                                   ▼
                                                         _dispatch_query()
                                                                   │
                                                  reply engine (Ollama LLM + tools/MCPs + planner)
                                                                   │  reply text
                                                                   ▼
                                                          tts.speak(text)  ─►  Piper ─► 🔊 speakers
                                                                   │
                          HUD state (listening → thinking → speaking → idle) pushed to React UI
                          via api_server  /ws/state  (FastAPI on 127.0.0.1:38130)
```

**Entry point:** `python -m jarvis.main` → `src/jarvis/main.py` → `src/jarvis/daemon.py:main()`.
The daemon is launched by the desktop app (`src/desktop_app/app.py`) as a subprocess, or
directly. `daemon.py:main()` constructs the TTS engine (`output/tts.py:create_tts_engine`)
and the `VoiceListener` thread (`listening/listener.py`), then runs the poll loop (also used
for reminders — see `reminders/reminders.spec.md`).

---

## 1. Speech‑to‑Text (audio IN)

`VoiceListener` (`src/jarvis/listening/listener.py`) owns STT and picks a backend from
`cfg.stt_backend`:

| `stt_backend` | Engine | Notes |
|---------------|--------|-------|
| `"wispr"` (current live setup) | **Wispr Flow** (external cloud STT app) via `WisprBridge` | Wake word + push‑to‑talk; transcript arrives through the clipboard. |
| `"whisper"` (legacy/local) | **faster‑whisper** (CUDA) or **MLX** (Apple) | Fully local; records audio and transcribes in‑process. |

Both backends end at the **same hand‑off**: a transcript string is passed to
`VoiceListener.feed_transcript(text)` → `_dispatch_query(text)` → reply engine.

### 1a. Wispr backend (`listening/wispr_bridge.py`) — the live path

Spec: `src/jarvis/listening/listening.spec.md`. Wired in `listener.py` as
`WisprBridge(..., on_transcription=self.feed_transcript)`.

Stages inside the bridge:

1. **Mic capture** — `sounddevice` input stream. The device is resolved from the persisted
   endpoint id / friendly name by `output/audio_devices.py`. That module deliberately prefers
   **DirectSound/MME over WASAPI** for *opening* streams (WASAPI is rate‑rigid and COM‑fragile
   in the daemon; DirectSound resamples and is robust). The PD200X mic opens at 16 kHz on
   DirectSound. See `match_name_to_sd_index` / `_playback_hostapi_score`.

2. **Wake word — openWakeWord** (`hey_jarvis`, runs on **CPU**, independent of the LLM/VRAM):
   - Model path is `cfg.wispr_wake_model`. For the custom far‑field model it is an **absolute
     path** to `…/.config/jarvis/wakeword/hey_jarvis.onnx` (a tiny DNN classifier; the heavy
     melspectrogram + embedding feature extractors are shared and downloaded once by
     `openwakeword.utils.download_models()`).
   - openWakeWord is **stateful**: its classifier window only advances on `predict()` and needs
     ~1.3 s of *continuous* frames before it scores a real wake. So the bridge **feeds EVERY
     frame** to the model (even silent ones) and **primes** it with ~1.5 s of silence at startup
     and on unmute (`_prime_wake_model`, `WAKE_PRIME_FRAMES`). Gating `predict()` on silence
     starves the window and tanks first‑frame recall — do not do it.
   - **Trigger** fires when a model score ≥ `cfg.wispr_wake_threshold` **and** the state is IDLE
     and not in cooldown. Two trigger‑only gates run *before* the decision (never on the model):
     the IDLE/cooldown/HOT_WINDOW check, and the **silence floor** `cfg.wispr_wake_rms_floor`
     (see Config below).
   - `cfg.wispr_wake_gain` amplifies the **wake‑only** copy of the audio (not the VAD/transcript
     audio) so a distant "Hey Jarvis" reaches openWakeWord's useful range.

3. **STT** — on wake, Wispr Flow (the external app) transcribes the speech and types the result;
   the bridge reads that transcript from the **clipboard** (`wispr_clipboard_wait_sec`) and calls
   `on_transcription` → `feed_transcript`.

4. **Endpointing / barge‑in** — Silero VAD (`vad_backend`) detects speech start/end for the
   push‑to‑talk window, and detects a **stop / barge‑in** ("stop", "σταμάτα", …) to interrupt TTS.

5. **Suspends** — wake detection is paused two *independent* ways that must not share a flag:
   `_speak_paused` (transient, auto‑lifted ~0.8 s after JARVIS finishes speaking, to kill echo) and
   `_user_muted` (HUD/control‑bus MUTE, cleared only by UNMUTE/TRIGGER). After either gap the model
   window is re‑primed.

**State machine (bridge):** `IDLE → DICTATING (after wake) → [transcript] → processing → speaking → IDLE`.

### 1b. Whisper backend (local) — legacy/fallback

`listener.py` records audio and transcribes with faster‑whisper (CUDA) or MLX. Relevant config:
`whisper_model` (e.g. `large-v3-turbo`), `whisper_compute_type` (`int8_float16`), `whisper_beam_size`
(1 = greedy, avoids the hallucination feedback loop on silence), `whisper_allowed_languages`
(`["el","en"]`), `whisper_min_confidence`, `whisper_filter_hallucinations`,
`whisper_language_validation`. Hallucination/no‑speech handling lives in `is_whisper_hallucination`.

---

## 2. Reply (the "brain", between STT and TTS)

`feed_transcript` → `_dispatch_query` runs the reply engine (`src/jarvis/reply/`).
Specs: `reply/reply.spec.md`, `reply/planner.spec.md`, `tools/builtin/tool_search.spec.md`.

- A local **Ollama** LLM (`cfg.ollama_chat_model`, e.g. `qwen3.5:9b-4k`) generates the reply,
  with **tool use** (built‑in tools + external **MCP servers**) and a **planner** that decomposes
  queries / direct‑executes tool steps for small models.
- The unified system prompt (`src/jarvis/system_prompt.py`) owns formatting + personality. **Tools
  return raw data**; the LLM loop formats it. Reply language is intentionally clamped to English.
- Every LLM call in the app (model, gating, timeout, caps, prompt source, data‑flow) is catalogued
  in **`docs/llm_contexts.md`** — keep it current when changing any LLM context.
- **MCP servers** are configured in `config.json → mcp_servers` (each launched with the venv python).
  They live in `mcps/` (gitignored — they carry `.env` secrets). Runtime: `tools/external/mcp_runtime.spec.md`.

---

## 3. Text‑to‑Speech (audio OUT)

The reply text is spoken via `VoiceListener.tts` (built by `output/tts.py:create_tts_engine`).

- Engine: **Piper** (local, `cfg.tts_engine = "piper"`). `tts.speak(text)` synthesises int16 PCM and
  plays it with `_play_int16_array` → a `sounddevice.OutputStream(channels=1, dtype='int16')`,
  resampling to the device's native rate. The **output device** is resolved live by
  `output/audio_devices.py` (again DirectSound‑preferred); `cfg.audio_output_endpoint_id` / `_name`
  persist the chosen endpoint.
- `cfg.tts_piper_length_scale` controls speech rate. (A Chatterbox voice‑clone path also exists,
  gated by `tts_engine`.)
- A short "thinking" tune (`output/tune_player.py`) can play while the reply generates; it is stopped
  the instant playback of the real reply starts.

---

## 4. The HUD (state surface)

`VoiceListener` starts a FastAPI server in‑process (`src/jarvis/api_server.py`) on
**127.0.0.1:38130** (control bus on **38127**). It serves the **React UI** in `ui/` and a
`/ws/state` WebSocket. The Qt windows in `src/desktop_app/` (`face_widget.py`, `hud_window.py`)
host that web view in a `QWebEngineView`.

State vocabulary the UI renders: **listening → thinking/processing → speaking → idle**. The TTS
layer maps internal states to the UI vocab (e.g. `synthesizing → thinking`) and pushes them via
`api_server.publish_state`. (Historical gotcha: GSAP/`requestAnimationFrame` is throttled in an
unfocused QWebEngine window, so `StatusLabel` sets its text synchronously, not inside a GSAP
callback.)

---

## 5. Wake / audio config quick reference (`config.json`)

| Key | Default | Meaning |
|-----|---------|---------|
| `stt_backend` | `whisper` | `wispr` (Wispr Flow bridge) or `whisper` (local). |
| `wispr_wake_model` | `hey_jarvis_v0.1` | openWakeWord model **name** or an **absolute path** to a custom `.onnx`. |
| `wispr_wake_threshold` | `0.1` | Min model score (0–1) to trigger a wake. |
| `wispr_wake_gain` | `1.0` | Software gain on the **wake‑only** audio copy (boosts distant speech). |
| `wispr_wake_rms_floor` | **`0.0` (off)** | Ungained int16 RMS below which a frame is treated as silence and the **trigger** is skipped (the model is still fed). **0 = off.** A non‑zero floor must stay **below** far‑field RMS (~100–200 on a PD200X at 2–3 m) or it silently drops distant wakes — that exact regression (a floor of 200 gated ~half of measured 3 m utterances) is why the default is 0; the recall‑tuned model already rejects silence (a silent frame scores ≈ 0.0007). Wired through `config.py` (dataclass + loader + constructor); the bridge fallback constant is `DEFAULT_WAKE_RMS_FLOOR` in `wispr_bridge.py`. |
| `wispr_silence_ms` | `800` | Silero‑VAD trailing silence to release push‑to‑talk. |
| `audio_input_endpoint_id` / `_name` | — | Persisted mic (resolved by `output/audio_devices.py`). |
| `audio_output_endpoint_id` / `_name` | — | Persisted speaker/headset for TTS. |

Each wake config value follows the same wiring pattern in `src/jarvis/config.py`: a `Settings`
dataclass field, a `get_default_config()` default, a loader read (`merged.get(...)` with a
try/except fallback), and a `Settings(...)` constructor argument. `wispr_wake_gain` and
`wispr_wake_rms_floor` are the reference examples.

---

## 6. Key files

| Path | Role |
|------|------|
| `src/jarvis/main.py` → `daemon.py` | Entry; builds tts + `VoiceListener`; runs the loop. |
| `src/jarvis/listening/listener.py` | STT orchestration; backend selector; `feed_transcript` → reply → tts. |
| `src/jarvis/listening/wispr_bridge.py` | Wake (openWakeWord) + Wispr Flow STT + VAD + state machine. |
| `src/jarvis/output/tts.py` | Piper TTS; PCM playback via sounddevice. |
| `src/jarvis/output/audio_devices.py` | Mic/speaker resolution; DirectSound‑preferred host‑API scoring. |
| `src/jarvis/reply/` | LLM reply engine, tools, planner. |
| `src/jarvis/api_server.py` + `ui/` | FastAPI :38130 + React HUD; `/ws/state`. |
| `src/jarvis/system_prompt.py` | Unified system prompt (formatting + personality). |
| `docs/llm_contexts.md` | Catalogue of every LLM call in the app. |

**Specs to read for detail:** `listening/listening.spec.md`, `dictation/dictation.spec.md`,
`reply/reply.spec.md`, `reply/planner.spec.md`, `tools/external/mcp_runtime.spec.md`,
`reminders/reminders.spec.md`, and the desktop specs under `src/desktop_app/`.
