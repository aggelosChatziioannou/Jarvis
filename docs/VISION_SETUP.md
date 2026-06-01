# Vision & Screen Interaction — Setup

How to enable and tune the Vision Engine (Jarvis seeing/reading/acting on your screen).
Spec: [src/jarvis/vision/vision.spec.md](../src/jarvis/vision/vision.spec.md).

## Enable it

Vision is **off by default**. In `config.json` (or the settings UI):

```json
{
  "vision_enabled": true,
  "vision_default_mode": "assist"
}
```

Pull the models once:

```
ollama pull qwen2.5vl:3b      # describe + grounding fallback (~3.2 GB)
```

Tesseract (text OCR + text-label locate) must be installed with the English and Greek
packs. On this machine it is at `C:\Program Files\Tesseract-OCR\tesseract.exe` (v5.5,
`eng`+`ell`). The engine finds it on PATH or in the standard install locations
automatically — no config needed.

## Which model and why

- **Tesseract** does all exact text work: reading the screen (`readScreen`) and locating
  **text-labelled** elements (`clickScreen` on buttons/links/menus). Pixel-accurate,
  bilingual (EN+EL), ~0.2 s, no extra VRAM.
- **qwen2.5vl:3b** does "what do you see" (`seeScreen`) and is the **grounding fallback**
  for icons / coloured buttons that have no readable text.
- **moondream was tested and rejected**: via Ollama it returns empty for every coordinate
  prompt (no grounding) and is prompt-fragile at describing. (The Phase-1 comparison
  report is generated locally by the vision verification script under `scripts/vision/`;
  it is not committed.)

## Verify Ollama is on the GPU

```
ollama ps
```

Each loaded model should show `100% GPU` (size_vram > 0). If a model shows CPU/partial,
update Ollama or check VRAM headroom (below).

## VRAM regime

`run_source.ps1` sets `OLLAMA_KEEP_ALIVE=-1`, which pins loaded models "Forever". With
both chat models pinned (`qwen3.5:9b-8k` ~8.6 GB + `qwen3.5:4b-4k` ~5.9 GB) there is not
enough room for qwen2.5vl:3b (~3.2 GB) on a 16 GB card.

- **Keep the 4B warm** — it is the intent-judge/router on every wake + query; a cold-load
  there can break wake detection. Never evict it.
- **Let the 9B chat model idle out**: the vision model loads on-demand with a short
  `vision_keep_alive` ("5m") so it self-evicts after a vision burst. To give it room,
  allow the 9B to be evictable — either drop the global pin (remove/relax
  `OLLAMA_KEEP_ALIVE=-1`) so the 9B idles out, or run a smaller chat model.
- After a vision burst the 9B reloads on the next reply (~3–5 s) — acceptable, since you
  are already looking at the screen.

## AUTO-mode app whitelist / blacklist

AUTO mode acts without asking, but only for whitelisted apps and never for blacklisted
ones. Values are **Windows process names**.

```json
{
  "vision_auto_whitelist": ["notepad.exe", "WindowsTerminal.exe", "explorer.exe", "spotify.exe"],
  "vision_auto_blacklist": ["chrome.exe", "msedge.exe", "firefox.exe", "1password.exe", "keepass.exe"]
}
```

In ASSIST mode (the default) every action is proposed and waits for your spoken
confirmation, regardless of app.

## Calibrate / troubleshoot monitor coordinates

Coordinates are physical pixels; the engine sets per-monitor-v2 DPI awareness so `mss`
(capture) and `pyautogui` (click) agree under display scaling. If clicks land off-target:

```
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\vision\verify_vision_model.py --click
```

Test F captures a known on-screen marker, converts via `monitor_map`, clicks it, and
checks the landing is within 20 px. Run it on each monitor and at 100% / 125% / 150%
scaling. If F fails, DPI awareness or the monitor offset is wrong — fix before relying on
clicks. Results are written to `docs/vision_test_report.md`.

## Safety summary

- ASSIST proposes; you confirm by voice (any language); `confirmScreenAction` then acts.
- Out-of-bounds coordinates, card/account numbers (typing), and AUTO on a blacklisted app
  are always refused.
- Screenshots are held in memory and never written to disk.
