# Vision & Screen Interaction Engine — Specification

## Overview

Lets Jarvis **see** the screen (describe / read / locate) and, with safety guards,
**act** on it (click / type / scroll). A modular `vision/` package holds the engine;
thin built-in Tools (`src/jarvis/tools/builtin/vision/`) expose it to the assistant and
return **raw data only**. The unified system prompt (`src/jarvis/system_prompt.py`) does
all formatting and personality. The vision package never prompts the LLM for prose and
never drives TTS.

## Design principles

1. **Raw data, not prose.** Every tool returns a compact dict; the reply engine's LLM
   loop formats the spoken answer. (Mirrors `web_search`, `log_meal`.)
2. **Right tool for each job.** Tesseract for exact bilingual text (read + text-label
   locate); a vision model only for scene description and non-text grounding.
3. **No hardcoded language patterns.** Element matching tokenises with `\w+` + fuzzy
   ratio; confirmation intent is judged by the LLM, never by "yes"/"no" string matching.
4. **Privacy first.** Screenshots are held in memory as PIL images and **never written to
   disk**. Tool results carry only coordinates + short text, never base64 images.
5. **Safety is hardcoded.** No voice command can bypass bounds checks, sensitive-input
   refusal, or the AUTO blacklist.

## Model strategy (validated in Phase-1 on RTX 5070 Ti)

- **moondream was rejected**: via Ollama `/api/chat` it returns *empty* for every
  coordinate/point/bbox/"click X" prompt (zero grounding) and its describe path is
  prompt-fragile. It cannot power locate/click.
- **Tesseract 5.5** (eng+ell) — exact bilingual OCR and `image_to_data` word-boxes for
  locating **text-labelled** elements. Pixel-accurate, ~0.2s, zero extra VRAM. Misses
  white-on-coloured button text and icons.
- **qwen2.5vl:3b** — describe ("what do you see") and **grounding fallback** for
  icons / coloured buttons. Emits `{"bbox_2d":[...]}`, `{"x":,"y":}`, or prose; the
  parser is JSON-aware. Accuracy on the 3b model is modest (tens-to-~120px), so it is the
  *fallback*, not the primary, locate path.

## Architecture

```
vision/
├── monitor_map.py    DPI awareness + monitor geometry + relative→absolute conversion
├── capture.py        mss multi-monitor capture -> in-memory PIL images
├── model_client.py   qwen2.5vl via jarvis.llm.call_vision_model; coordinate parsing
├── analyzer.py       read_text (Tesseract) + locate_text_label (word-boxes) + facade
├── interaction.py    pyautogui click/type/scroll/move (no safety logic)
├── safety.py         modes, bounds, foreground-app gate, sensitive-input, pending buffer
└── vision_engine.py  facade orchestrating all of the above
```

### Coordinate model (the #1 Windows correctness issue)

A vision/OCR result is relative to the captured monitor image. `pyautogui` needs absolute
virtual-desktop pixels. The conversion is `abs = monitor.left + rel` — but only valid once
capture (`mss`, physical px) and clicking (`pyautogui`) share one coordinate space.
`ensure_dpi_awareness()` sets **per-monitor-v2 DPI awareness** before any capture/click so
both see physical pixels under display scaling (125%/150%). Handles negative offsets
(monitors left/above primary). `pyautogui.FAILSAFE` stays on (corner = abort).

### Locate fallback chain (`VisionEngine.locate`)

1. `analyzer.locate_text_label` — Tesseract word-boxes (text labels). `method="ocr"`.
2. `model_client.locate` — qwen2.5vl grounding (icons / coloured buttons). `method="vision"`.
3. neither → `{"found": false}`.

Result coordinates are converted to **absolute** desktop pixels.

### Observe failure is honest, not silent (`VisionEngine.observe`)

`describe` returns `None` when the vision model does not respond (timeout / still
loading / transient error). `observe` then returns an explicit
`{"status": "unavailable", "reason": "no_response", "description": null, "message": …}`
payload **instead of an empty description**. An empty string would let the reply LLM
confabulate "the screen is blank"; the explicit status + `seeScreen`'s tool-description
rule make the LLM tell the user the vision system is temporarily slow/unavailable and
ask them to retry, never guessing screen contents. Capture itself succeeding or failing
is independent — a black/blank capture is still a valid description request.

## Safety modes (`safety.py`)

| Mode | Behaviour |
|------|-----------|
| **OBSERVE** | describe/read/locate only; never acts |
| **ASSIST** (default) | click/type/scroll stash a pending action and return `requires_confirmation`; executed only via `confirmScreenAction` after the user assents |
| **AUTO** | executes immediately, but only when the foreground app is whitelisted and not blacklisted |

Hardcoded guards (never bypassable): out-of-bounds coordinates → refused; Luhn-valid card
/ long account numbers → refused for `type`; AUTO on a blacklisted app → refused.

### Confirmation flow (two voice turns, no new state machinery)

- **Turn 1**: `clickScreen("Submit")` → locate → bounds-check → stash a single-slot
  pending action (TTL `vision_pending_ttl_sec`, default 120s) → return
  `requires_confirmation`. The LLM asks the user to confirm; reply ends; hot window opens.
- **Turn 2**: user assents (any language) → the LLM (which sees the Turn-1 proposal via
  dialogue-memory tool-carryover) calls `confirmScreenAction` → re-locate the target on a
  fresh screenshot → re-validate bounds → execute. Aborts gracefully if the target moved
  (`target_vanished`) or the buffer expired (`no_pending_action`).

## VRAM

`OLLAMA_KEEP_ALIVE=-1` (set in `run_source.ps1`) pins loaded models "Forever". The 4B
intent-judge/router **must stay warm** (cold-load breaks wake detection). The vision model
is loaded on-demand with a short `keep_alive` (`vision_keep_alive`, default "5m") so it
self-evicts after a vision burst. See `VISION_SETUP.md` for the residency regime and how to
let the 9B chat model become evictable so qwen2.5vl:3b fits.

## Configuration (`config.py`)

| Key | Default | Meaning |
|-----|---------|---------|
| `vision_enabled` | `false` | master switch; tools are dormant until true |
| `vision_model` | `qwen2.5vl:3b` | Ollama vision model for describe + grounding |
| `vision_default_mode` | `assist` | `observe` / `assist` / `auto` |
| `vision_auto_whitelist` | notepad, terminal, explorer, spotify | AUTO-allowed process names (Windows) |
| `vision_auto_blacklist` | browsers, password managers | never auto-actioned |
| `vision_pending_ttl_sec` | `120` | confirmation window |
| `vision_keep_alive` | `5m` | vision model Ollama keep_alive |
| `vision_max_width` | `1280` | cap longest side of the image **sent to the vision model** (`null` = off). OCR/`readScreen` keeps full resolution (Tesseract is a separate path). Downscaling a 2560-wide screen (~2616 prompt tokens) to 1280 roughly quarters the tokens → faster eval, less VRAM, fewer cold-load timeouts. `model_client` scales grounding coordinates back to the original. |
| `vision_timeout_sec` | `20.0` | per-call vision model timeout. Headroom for the **cold** first call (model load + image eval under VRAM contention) so a slow first `seeScreen` doesn't fail. |

## Tools (raw-data, in `tools/builtin/vision/`)

`seeScreen(monitor?)`, `readScreen(monitor?)`, `locateOnScreen(target)`,
`clickScreen(target)`, `typeOnScreen(text)`, `scrollScreen(direction, amount?)`,
`confirmScreenAction()`. Single-property where possible (planner fast-path friendly). All
gate on `vision_enabled` and run synchronously in the reply engine (like every other tool;
the thinking tune covers the latency).

## Privacy

Screenshots never touch disk; held in memory and released after inference. Carried-over
tool results contain only coordinates + short descriptions (the carryover layer truncates
to 1200 chars and scrubs secrets). Sensitive input (cards/account numbers) is refused.

## Testing

`tests/vision/` — behaviour tests with injected collaborators (no display/model needed):
coordinate conversion incl. negative-offset + DPI, capture regions, OCR + bilingual locate,
safety modes/bounds/foreground/sensitive/pending, model_client parsing (point + bbox),
engine orchestration + fallback chain + confirm flow, and the 7 tools. Standalone Phase-1
verification (incl. Test-F DPI click round-trip within 20px on scaled monitors) lives in
`scripts/vision/verify_vision_model.py`; results in `docs/vision_test_report.md`.

## Limitations

- qwen2.5vl:3b grounding is imprecise; icon/coloured-button clicks may miss. Text-labelled
  targets (Tesseract) are accurate.
- Post-action verification (screenshot delta) is not yet implemented (planned).
- AUTO foreground-app detection is Windows-only (win32gui + psutil).
- No accessibility-tree introspection; locating relies on OCR + the vision model.
