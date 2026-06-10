# STT Backend Hot-Switch (Flow ↔ Whisper large-v3) Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user flip `stt_backend` (Wispr Flow ↔ local Whisper large-v3-turbo) in the React console Settings and have the running daemon switch backends in-process — no full app/daemon restart — with automatic fallback to the previous backend if the new one fails to start.

**Architecture:** The `VoiceListener` thread currently dispatches ONCE on `self._stt_backend` in `run()` (whisper main loop @3943 inside `with stream:`; `_run_wispr_backend` @4472). We wrap that one-shot dispatch in a re-entrant dispatcher loop driven by a `threading.Event` (`_switch_event`). A new `request_stt_switch()` sets the pending backend + event; the active backend loop breaks at its top-of-loop guard, the dispatcher tears down the old STT runtime (release Whisper model → free VRAM, or stop Wispr bridge) and re-dispatches the new one. `control_bus`, `_porcupine`, the API server and all daemon closures stay bound to the SAME listener instance, so nothing dangles. The PATCH `/api/config` endpoint detects an `stt_backend` change and triggers the switch on a background thread. On a fast startup failure of the new backend, the dispatcher reverts to the prior backend and persists that revert so the UI reflects reality.

**Tech Stack:** Python (faster-whisper, threading), FastAPI (api_server), React/TS (Vite console).

---

## Chunk 1: Listener in-process hot-switch core

**File:** `src/jarvis/listening/listener.py`

### Task 1: Switch state in `__init__`
- [ ] In `__init__` (near line 404, after `self._wispr_bridge = None`) add:
  - `self._switch_event = threading.Event()` — set to ask the active backend loop to yield.
  - `self._pending_backend: Optional[str] = None` — target backend for a requested switch.
  - `self._switch_from: Optional[str] = None` — backend we switched away from (for fallback).
  - `self._consecutive_fast_failures = 0` — guards against fallback ping-pong.

### Task 2: Extract bridge creation into `_ensure_wispr_bridge()`
- [ ] Move the `WisprBridge(...)` instantiation (lines 695-719) into a new method `_ensure_wispr_bridge() -> bool` that (re)creates `self._wispr_bridge` if `None`, returns True on success / False on failure, and sets `self._stt_backend="whisper"` only when called from init context. In `__init__`, replace the inline block with `if self._stt_backend == "wispr": self._ensure_wispr_bridge()`.
- [ ] In `_run_wispr_backend` (line 4395) replace the early `if self._wispr_bridge is None: refuse` with `if not self._ensure_wispr_bridge(): <print hint>; return` so a whisper→wispr switch recreates a fresh bridge.

### Task 3: Re-entrant dispatcher `run()`
- [ ] Rename current `def run(self)` (line 3312) to `def _dispatch_once(self)`. No body changes except it remains a normal method (its early `return`s now return from the helper).
- [ ] Add a new `def run(self)` dispatcher: clears `_switch_event`; calls `_dispatch_once()` in try/except; on `_should_stop` exits; if `_switch_event` set + `_pending_backend`: teardown old runtime, set `_stt_backend = pending`, log "🔀 Switching STT backend → X", continue; if `_dispatch_once` crashed within ~8s (failed (re)start): teardown, revert to `_switch_from` (or the other backend), persist the revert, log "❌ … reverting to Y", continue (max 2 consecutive); else (clean stop/fatal) break. Final teardown after loop.
- [ ] Reset `_consecutive_fast_failures = 0` whenever a dispatch ran longer than the 8s "fast failure" window (a genuinely-started backend).

### Task 4: Backend loops honor the switch event
- [ ] Line 3943: `while not self._should_stop:` → `while not self._should_stop and not self._switch_event.is_set():` (whisper main loop; breaking exits `with stream:` → mic closed cleanly).
- [ ] Line 4472: `while not self._should_stop:` → `while not self._should_stop and not self._switch_event.is_set():` (wispr idle loop; existing post-loop `self._wispr_bridge.stop()` runs).

### Task 5: `_teardown_stt_runtime()` + `request_stt_switch()`
- [ ] Add `_teardown_stt_runtime(self, backend: str)`: if `"wispr"` → `self._wispr_bridge.stop()` then `self._wispr_bridge = None` (force fresh bridge next time); else → `self.model = None`, `self._whisper_backend = None`, `gc.collect()` + `torch.cuda.empty_cache()` (best-effort, to free VRAM). Never raises.
- [ ] Add `request_stt_switch(self, new_backend: str) -> bool`: lower/validate ∈ {whisper,wispr}; no-op if already that backend; else set `_pending_backend`, set `_switch_event`, return True. Safe to call from any thread.

## Chunk 2: Daemon + API wiring

**Files:** `src/jarvis/daemon.py`, `src/jarvis/api_server.py`

### Task 6: daemon entry points
- [ ] Add `request_stt_switch(new_backend: str) -> bool` in daemon.py: resolves `get_active_listener()` and calls `listener.request_stt_switch(new_backend)`; returns False if no active listener.
- [ ] Add `_persist_stt_backend(backend: str)` helper (used by the listener's fallback-revert) writing `stt_backend` via `config_safety.safe_write_config` to the active config path. (Listener calls `from .. import daemon; daemon._persist_stt_backend(...)` inside the revert branch.)

### Task 7: PATCH /api/config triggers the switch
- [ ] In `patch_config` (api_server.py line 314): capture `old_backend = current.get("stt_backend")` BEFORE `current.update(updates)`. After the successful write, if `"stt_backend"` in `updates` and `new != old` and `new ∈ {whisper,wispr}`: `publish_log("info", "🔀 STT backend change requested → X")` and fire `daemon.request_stt_switch(new)` on a short-lived `threading.Thread` (so the HTTP response returns immediately). Wrap in try/except → on failure `publish_log("error", …)`. Response schema unchanged.

## Chunk 3: Console UI polish

**Files:** `ui/src/console/lib/settingsSchema.ts`, `ui/src/console/sections/SettingsPage.tsx`

### Task 8: Friendly option labels
- [ ] Add optional `optionLabels?: Record<string,string>` to `SettingsField`. On the `stt_backend` field set `optionLabels: { wispr: 'Wispr Flow (cloud)', whisper: 'Whisper large-v3 (local)' }`.
- [ ] In `SettingsPage` `Field` select rendering (line 56) render `field.optionLabels?.[o] ?? o` as the option text (value stays the raw key).

### Task 9: Switching toast
- [ ] In `save()` capture whether `'stt_backend' in diff` before clearing; if so set a transient message "Switching STT backend… (watch Live Logs)"; the actual success/failure already streams to Live Logs via `publish_log`. Otherwise keep the generic "Saved" indicator. (Replace the static line 128.)

## Chunk 4: Tests + verification

**Files:** `tests/test_listener_stt_switch.py`, `tests/test_api_stt_switch_trigger.py`

### Task 10: Listener switch unit tests
- [ ] `request_stt_switch("wispr")` on a whisper listener sets `_switch_event` and `_pending_backend == "wispr"`; returns True. Invalid backend → False, event not set. Same-backend → False (no-op).
- [ ] `_teardown_stt_runtime("whisper")` nulls `self.model`; `_teardown_stt_runtime("wispr")` calls `bridge.stop()` and nulls `_wispr_bridge`. Neither raises (mock bridge).
- [ ] Construct via the existing `_make_listener()` pattern (real `__init__`, MagicMock deps).

### Task 11: API trigger unit test
- [ ] With a temp config (`JARVIS_CONFIG_PATH`) holding `stt_backend: "wispr"`, monkeypatch `jarvis.daemon.request_stt_switch` to record calls; `patch_config(ConfigPatch(updates={"stt_backend":"whisper"}))` writes the file AND invokes `request_stt_switch("whisper")` (allow brief join for the background thread). A patch that does NOT change `stt_backend` does not invoke it.

### Task 12: Verify
- [ ] `python -m pytest tests/test_listener_stt_switch.py tests/test_api_stt_switch_trigger.py tests/test_listener_dispatch_and_dictation.py -q` → green.
- [ ] `cd ui && npm run build` (tsc -b + vite build) → no type/build errors.
- [ ] `python -c "import ast,sys; [ast.parse(open(f,encoding='utf-8').read()) for f in ['src/jarvis/listening/listener.py','src/jarvis/daemon.py','src/jarvis/api_server.py']]"` → parses clean.

## Out of scope / notes
- No change to Whisper model choice — `whisper_model` default is already `large-v3-turbo`.
- Wispr Flow remains fully intact; this only makes the existing `stt_backend` selector apply live.
- Mid-utterance: the switch is honored at the top of the backend loop, so an in-progress transcription completes before the swap (no mid-transcription interruption).
