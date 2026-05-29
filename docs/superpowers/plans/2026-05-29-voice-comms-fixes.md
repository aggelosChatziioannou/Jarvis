# Voice Communication Fixes Implementation Plan

> **STATUS: ✅ COMPLETED 2026-05-29.** All Phase A + Phase B tasks shipped with TDD (~60 new tests). Verified: 899 passed across 43 touched test files, 0 new regressions (17 remaining failures are pre-existing WIP, see JARVIS_CHANGES.md 2026-05-29 entry). Reply language kept English per user choice. Changes live in the working tree; desktop icon runs from source so a restart applies them.

> **For agentic workers:** Use TDD per task (failing test first). Test runner:
> `C:\Users\aggel\Jarvis-src\.venv\Scripts\python.exe -m pytest tests/<file> -v`
> Import convention: `from jarvis.x import ...` (conftest puts src on sys.path).

**Goal:** Fix all audit findings for the live Wispr-Flow voice path EXCEPT Jarvis's reply language (stays permanently English by user choice).

**Architecture:** Live STT = `WisprBridge` (openWakeWord + Silero VAD + Ctrl+Win+Space drive of Wispr Flow desktop app, transcript via clipboard). Thinking -> answer -> TTS is backend-agnostic and shared.

**Constraints:** Data privacy first. British English, no em dashes in user-facing strings. Emojis + indentation in CLI output. `debug_log` at important flow points. Do NOT touch the forced-English clamp in engine.py.

---

## File-ownership streams (parallel only across disjoint files)

| Stream | Owns | Agent |
|--------|------|-------|
| R (Reply core) | `src/jarvis/llm.py`, `src/jarvis/reply/engine.py`, `src/jarvis/config.py` | Phase A |
| W (Wispr bridge) | `src/jarvis/listening/wispr_bridge.py` | Phase A |
| L (Listening/orchestration) | `src/jarvis/listening/listener.py` | Phase A |
| Me (orchestrator) | `docs/llm_contexts.md`, spec files, integration + full-suite runs | all phases |

---

## Phase A — isolated, file-disjoint fixes (parallel subagents)

### Stream R (llm.py + engine.py + config.py)
- R1: `chat_with_messages` accepts optional `num_predict` + `temperature`; main synthesis turn passes config-driven cap. New config: `llm_chat_max_tokens` (default 512), `llm_chat_temperature` (default unset). Bounds runaway generation latency.
- R2: malformed-output fallback small-model detection includes `gemma4` (use `detect_model_size`), so the default model gets the right hint branch.
- R3: memory-injection window — widen constant (2 -> configurable, default 4) + `debug_log` when recalled memory is dropped due to the window.
- R4 (config only): lower `wispr_min_dictation_sec` default 2.0 -> 1.0; add `wispr_barge_in_interrupt` (bool, default True) for Stream W5.

### Stream W (wispr_bridge.py)
- W1: safer `_erase_autotyped_text` — configurable max-backspace cap; skip when transcript length exceeds cap; never erase on empty.
- W3: `_jarvis_speaking` guarded by a lock; atomic read in `_dispatch_transcription`.
- W4: `on_dictation_end` callback gains a `captured: bool` argument; `_post_dictation_worker` passes whether a clipboard transcript was captured. **Contract:** `on_dictation_end(captured: bool)`.
- W5: barge-in — in `_process_vad` HOT_WINDOW branch, when `_jarvis_speaking` and a VAD speech-onset fires, call `on_stop()` immediately (gated by `getattr(cfg, "wispr_barge_in_interrupt", True)`) so TTS is interrupted on speech onset, not after the cloud+clipboard round-trip.

### Stream L (listener.py)
- L1 (H2): `_dispatch_query` forwards `self._last_fused_tools` / `self._last_fused_plan` to `run_reply_engine` (verify exact kwarg names by reading engine.py), then clears them. Removes the redundant router+planner re-run.
- L2: `_on_wispr_dictation_end(self, captured: bool = True)` — when `captured is False`, stop the thinking tune and reset face to IDLE (fixes stuck tune/face on clipboard timeout).
- L3: when `captured is False`, `debug_log` + optional brief notice so a failed dictation is not silent.

---

## Phase B — cross-cutting architectural (sequential, orchestrator-led, after Phase A integrates)
- X1: cancel-token end-to-end — `run_reply_engine` polls `cancel_event` at turn boundaries / before tool dispatch / before TTS; listener passes `self._llm_cancel_event` and runs the engine cancellably. Real STOP + barge-in at the reasoning level.
- X2: streaming TTS — sentence-by-sentence synthesis (engine yields sentences -> `tts.speak` per sentence). Config: `tts_streaming_enabled`. Biggest perceived-latency win.
- X3: thread-safety for listener manual-trigger flags (`_manual_trigger_active`, `_manual_finalize_requested`, `_muted`).

## Orchestrator tasks
- D1: reconcile `docs/llm_contexts.md` drift (chat timeout 45 -> 180, intent-judge timeout, beam_size, compute_type).
- S1: spec updates (dictation.spec.md / reply.spec.md) for new behaviours.
- Integration: run full `pytest` suite between phases; run evals after prompt/decode-affecting changes.
