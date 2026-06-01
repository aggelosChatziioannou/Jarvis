# AGENTS.md — orientation for a new AI session

Read this first. It describes **what this fork of Jarvis actually is and how it
really runs**, so you don't trust stale assumptions. `README.md` is the public
upstream *product* README (open-source default build); it does **not** describe
this machine's live setup. For conventions and the spec registry, see
`CLAUDE.md`. For deep detail, follow the pointers in "Authoritative docs" below.

> ⚠️ This doc is ground-truth-but-not-volatile. Exact live model names can
> change — confirm with `ollama ps` and the live config
> (`~/.config/jarvis/config.json`, default path) when it matters.

## What Jarvis is

A local-first AI **voice assistant**: say "Jarvis" anywhere in a sentence → it
transcribes, decides if it's addressed, runs an agentic LLM loop (tools, memory,
web, vision, reminders), and speaks back. Persistent memory (diary + knowledge
graph), MCP tool integration, screen vision, and a desktop tray app + web UI.

## Models actually in play

One **chat model** does the heavy reasoning; small classification tasks ride the
same model (or a smaller one if configured). They share **one Ollama instance**
— not separate models per task.

| Role | Live (this machine) | Code default | Loaded |
|------|--------------------|--------------|--------|
| Chat / reply / intent-judge / tool-router / planner | `qwen3.5:9b-4k` (all four point at it) | chat `gemma4:e2b`; intent/router fall back to chat | Resident (Ollama, keep_alive) |
| Embeddings (memory vector search) | `nomic-embed-text` | same | Resident, small (~0.6 GB) |
| Vision (`seeScreen` etc.) | `qwen2.5vl:3b` | `qwen2.5vl:3b` | **On-demand**, self-evicts after `vision_keep_alive` (5m) |
| TTS | **Piper** (CPU, 0 VRAM) | Piper | CPU; Chatterbox is optional/heavy |
| Wake word | **openWakeWord** custom `hey_jarvis.onnx` (CPU) | openWakeWord | CPU |

Live VRAM at rest ≈ 9–10 GB / 16 (qwen3.5:9b + nomic-embed); ~+3 GB briefly with
vision. The authoritative per-call map is **`docs/llm_contexts.md`** (17 contexts).

Gotchas:
- `gemma4:e2b`/`e4b` are the code defaults but are **not published Ollama tags**
  (gemma2/gemma3 exist). This machine overrides everything to `qwen3.5:9b-4k`
  (built from `Modelfile.chat`). A clean install pulling the default may need a
  real tag.
- The intent judge runs the **9b** here (not the small `gemma4` default), so
  per-utterance routing is slower but there's only one model in VRAM.

## Speech-to-text: TWO backends (`stt_backend`)

- `wispr` (**live here**): **Wispr Flow cloud** does STT via a push-to-talk
  bridge (`src/jarvis/listening/wispr_bridge.py`: openWakeWord + Silero VAD +
  hotkey + clipboard capture, with closed-loop mic-state sync). **Local Whisper
  is NOT loaded in this mode** — startup logs branch on `config.uses_local_whisper`.
- `whisper` (open-source default): local **faster-whisper** (`large-v3-turbo`)
  transcribes; wake is transcript/text-based (or optional Porcupine).

Dictation (hold-to-dictate) reuses the listener's Whisper model and is OFF by
default here (`dictation_enabled=false`).

## UI: THREE surfaces

1. **React app** (`ui/`, Vite/TS) — the canonical UI. `vite build` → `ui/dist`
   → served by the daemon's **FastAPI on `127.0.0.1:38130`**.
   - `GET /` = Home (boot screen + the orb card)
   - `GET /panel` = Control Console (Live Logs, Audio I/O, Wake Word, Voice/TTS,
     Language Model, Services/MCP, API Keys, Easter Eggs)
2. **PySide desktop shell** (`src/desktop_app/`) — the OS app: tray, startup,
   single-instance, updater. Embeds the React app in two frameless QWebEngineView
   windows: **WebFloatingHUD** (the always-on-top orb, loads `/`) and
   **JarvisConsoleWindow** (loads `/panel`). `jarvis` core has no knowledge of it.
3. **Flask memory viewer** (`src/desktop_app/memory_viewer.py`, port **5050**) —
   a separate web app for the diary / knowledge-graph / meals explorer, in its
   own window.

Ports: FastAPI/UI **38130**, control bus **38127**, memory viewer **5050**.

## How it launches + dev env

- Production launch: **`Start-Jarvis.vbs`** → `scripts/kill-jarvis.ps1` (kill any
  running instance) → `.venv\Scripts\pythonw.exe -m desktop_app`. The Desktop
  `Jarvis.lnk` (made by `Install-DesktopShortcut.ps1`) points at this VBS.
  Running it **picks up source changes** (plain Python, no build step).
- Dev run: `run_source.ps1` (adds Blackwell GPU env tweaks).
- **Environment: `.venv` + system Python 3.11** (NOT the micromamba path that
  `CLAUDE.md` mentions). Tests:
  `\.venv\Scripts\python.exe -m pytest tests/ -q`. There is a known set of
  pre-existing failures (GUI/desktop + platform tests) unrelated to core logic.
- Packaging: `jarvis_desktop.spec` (PyInstaller) — **load-bearing**, referenced
  by CI (`.github/workflows/`) and the `scripts/build_installer*`/`test_bundled_app*`
  scripts. Don't move it or the root launchers without updating those.

## Repository map (top level)

```
src/jarvis/        Core assistant (backend). Subpackages: listening/ (STT, wake,
                   wispr_bridge), reply/ (engine, planner, prompts), memory/
                   (graph + diary + summariser), tools/ (builtin + external MCP),
                   vision/, reminders/, output/ (tts, audio_devices), utils/.
                   api_server.py = FastAPI (:38130). Has *.spec.md next to code.
src/desktop_app/   PySide tray shell + the QWebEngineView windows + memory_viewer.
ui/                React/Vite/TS front-end (built to ui/dist, served by the daemon).
mcps/              Local MCP server impls (gitignored — contains .env with keys).
tests/             Unit + integration (pytest). evals/ = separate LLM-accuracy evals.
docs/              voice-pipeline.md, llm_contexts.md, VISION_SETUP.md, img/,
                   superpowers/ (dated plans/specs/research — dev history).
scripts/           build / launch wrappers / eval runners / training / diagnostics.
assets/ data/      audio cues + GeoLite, trained intent classifier, etc.
installer/ examples/  installer assets; examples/config.json sample.
wakeword-training/ Local-only (gitignored) "Hey Jarvis" openWakeWord training scratch.
```

Root also holds: `Start-Jarvis.vbs`, `run_source.ps1`, `Install-DesktopShortcut.ps1`,
`jarvis_desktop.spec`, `Modelfile.chat`/`Modelfile.judge` (Ollama custom-model build
inputs), `requirements.txt` (+ `requirements_no_chatterbox.txt` lean variant),
`CLAUDE.md`, `README.md` (upstream product), `EVALS.md`, `JARVIS_CHANGES.md`.

## Authoritative docs (trust order)

1. **`docs/voice-pipeline.md`** — the real STT/wake/TTS pipeline (dual backends).
2. **`docs/llm_contexts.md`** — every LLM call (model, gating, limits, flow). Kept
   in sync per `CLAUDE.md`; update it in the same PR as any LLM-context change.
3. **`*.spec.md`** next to code — behavioural contracts. Registry table is in
   `CLAUDE.md`. Search for these before changing related code.
4. `CLAUDE.md` — project conventions (privacy-first, emoji CLI output, `debug_log`,
   no hardcoded language patterns, TDD, British English, conventional commits,
   default branch `develop`).
5. `docs/VISION_SETUP.md` — vision/Tesseract setup.
6. `JARVIS_CHANGES.md` — **fork history, not current config** (model names in old
   entries are point-in-time).

## "Don't be fooled" (current as of 2026-06)

- The **hot-window** wake-word-free follow-up is **present in code but OFF by
  default** (`wispr_hot_window_sec=0`). Code referencing it is current, not dead.
- The **evaluator is deprecated** — replaced by the planner (`reply/evaluator.spec.md`).
  Any "evaluator runs each turn" wording is stale.
- `README.md` says "100% local / offline / no cloud" — true for the `whisper`
  backend, **but this machine runs `wispr` (cloud STT)**.
- A large uncommitted "remove hot-window" refactor may sit in a local `git stash`;
  HEAD still HAS the hot window. Don't assume it's gone.
