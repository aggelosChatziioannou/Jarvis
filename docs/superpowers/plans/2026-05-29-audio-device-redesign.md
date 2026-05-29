# Audio Device Redesign Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Strict TDD per task (failing test first). Steps use `- [ ]`.
> **Test runner:** `C:\Users\aggel\Jarvis-src\.venv\Scripts\python.exe -m pytest tests/<file> -v` (from repo root). Import `from jarvis.x import ...`. UI build: `npx --no-install vite build` from `ui/` (skips the tsc gate; pre-existing WIP TS errors exist). pycaw + comtypes already installed.
> **Conventions:** British English, NO em dashes in user-facing strings, emojis OK in CLI prints, `from ..debug import debug_log`. Data privacy first (pycaw = local Core Audio, no network). NEVER call `sd._terminate()/_initialize()` (kills the open Wispr mic stream).
> **Pre-existing failures:** ~16 unrelated tests fail in this tree (UI/enrichment/intent-judge/migration). Only ensure YOUR new tests pass and add no NEW failures.

**Goal:** Replace "(Follow Windows default)" with explicit, remembered, hot-plug-adaptive audio device selection (input + output) driven by Windows Core Audio (pycaw), persisted by stable endpoint id.

**Architecture:** pycaw Core Audio is the live source of truth for the device list (render/capture, endpoint id + name + state); selection persists by endpoint id and resolves to a sounddevice index per use (fail-open on absent device); an `IMMNotificationClient` pushes live add/remove/default-change events to the React UI and triggers reconnect.

**Spec:** `docs/superpowers/specs/2026-05-29-audio-device-redesign-design.md`.

---

## PHASE 1 - Core Audio device service + persistence

### Task 1: list_devices() with endpoint ids + render/capture split
**Files:** Modify `src/jarvis/output/audio_devices.py`; Test `tests/test_audio_devices.py`
- [ ] Failing test: mock pycaw `AudioUtilities.GetAllDevices()` returning render+capture endpoints with `.id`, `.FriendlyName`, `.state`; assert `list_devices()` returns `{"inputs":[...],"outputs":[...]}` where each item is `{"id","name","is_default","available"}`, only Active endpoints, render->outputs, capture->inputs. Assert it fails open to a sounddevice-derived list (no ids) when pycaw import raises.

```python
def test_list_devices_splits_render_capture_with_ids(monkeypatch):
    # build fake pycaw devices (see existing tests for the AudioDeviceState pattern)
    ...
    out = audio_devices.list_devices()
    ids = {d["id"] for d in out["outputs"]}
    assert "{0.0.0...}.{spk}" in ids
    assert all({"id","name","is_default","available"} <= set(d) for d in out["outputs"])
```
- [ ] Run (fail). Implement: read render vs capture via the Core Audio enumerator (EDataFlow eRender/eCapture) or by classifying GetAllDevices entries; determine default via `AudioUtilities.GetSpeakers()/GetMicrophone()` ids; `available = state == Active`. READ the current `_active_friendly_names`/`list_real_devices` to reuse. Keep `list_real_devices` as a thin back-compat shim or update callers. Run (pass). Commit `feat(audio): list_devices with endpoint ids + render/capture split`.

### Task 2: resolve_endpoint_to_sd_index()
**Files:** Modify `audio_devices.py`; Test `tests/test_audio_devices.py`
- [ ] Failing test: given a fake sounddevice list + a pycaw endpoint (id+name), `resolve_endpoint_to_sd_index(endpoint_id, name, kind="output")` returns the matching sd index (match by name, truncation-tolerant, WASAPI-preferred), and `None` when the device is absent. Name-only fallback when id unknown.
- [ ] Run (fail). Implement (reuse `match_name_to_sd_index`; add id->name lookup via `list_devices()`). Run (pass). Commit `feat(audio): resolve persisted endpoint id to sounddevice index`.

### Task 3: config keys + migration
**Files:** Modify `src/jarvis/config.py`; Test `tests/test_config_models.py`, `tests/test_migration_*` pattern
- [ ] Failing test: defaults load for `audio_output_endpoint_id`(""), `audio_output_name`(""), `audio_input_endpoint_id`(""), `audio_input_name`("") across dataclass+defaults+loader. A migration copies a legacy non-empty `tts_output_device`/`wispr_mic_device` (name) into `audio_output_name`/`audio_input_name` (id left blank -> name fallback resolves it).
- [ ] Run (fail). Implement the 4 keys (mirror an existing string key end-to-end) + a config-version migration that forwards the old name values. Run (pass). Commit `feat(audio): persist selected input/output by endpoint id (+ migrate old keys)`.

## PHASE 2 - Wire output + input; remove follow-default

### Task 4: TTS output resolves persisted endpoint id (no follow-default)
**Files:** Modify `src/jarvis/output/tts.py`; Test `tests/test_tts_live_output_device.py`
- [ ] Failing test: with `cfg.audio_output_endpoint_id` set, the play path resolves via `resolve_endpoint_to_sd_index(id, name, kind="output")`; when the device is absent it returns None and playback fails open (no exception) and logs "output device disconnected"; there is NO follow-Windows-default branch (assert `get_default_output_name` is not consulted when an endpoint id is configured).
- [ ] Run (fail). Implement: replace `_resolve_output_device_live`'s follow-mode with endpoint-id resolution; remove the `get_default_output_name()` follow branch. Preserve the WASAPI-exclusive-only-for-default guard. Run (pass) + run `tests/test_piper_tts.py`, `tests/test_tts_state_transition.py`. Commit `feat(audio): TTS output uses persisted endpoint id, drops follow-default`.

### Task 5: Wispr input resolves persisted endpoint id
**Files:** Modify `src/jarvis/listening/wispr_bridge.py` + `listener.py`; Test `tests/test_wispr_bridge.py`
- [ ] Failing test: the bridge resolves its mic from `cfg.audio_input_endpoint_id` via `resolve_endpoint_to_sd_index(..., kind="input")`; absent device -> bridge does not crash (logs + waits). 
- [ ] Run (fail). Implement: bridge reads the resolved input index (replacing `wispr_mic_device`); guard `start()`/stream-open against an absent device. Run (pass). Commit `feat(audio): Wispr wake mic uses persisted endpoint id`.

### Task 6: api_server device endpoints
**Files:** Modify `src/jarvis/api_server.py`; Test `tests/test_api_server_startup.py`
- [ ] Failing test: `GET /api/audio/devices` returns `{inputs,outputs}` each with `{id,name,is_default,available}` from `list_devices()`; `POST /api/config` persists `audio_*_endpoint_id`/`name`; fails open to empty shape.
- [ ] Run (fail). Implement (delegate to `audio_devices.list_devices`). Run (pass). Commit `feat(audio): /api/audio/devices returns endpoint-id device list`.

## PHASE 3 - Live notifications + reconnect

### Task 7: device watcher (IMMNotificationClient)
**Files:** Create `src/jarvis/output/device_watcher.py`; Test `tests/test_device_watcher.py`
- [ ] Failing test: `DeviceWatcher(on_change).start()` registers a pycaw `MMNotificationClient` (mock `AudioUtilities.GetDeviceEnumerator().RegisterEndpointNotificationCallback`); simulating a callback (`on_device_added`/`removed`/`state_changed`/`default_changed`) invokes `on_change`. `stop()` unregisters. Fail-open if pycaw unavailable (start() returns False, no raise).
- [ ] Run (fail). Implement per the pycaw notification example (own COM thread; NEVER touch PortAudio). Debounce rapid events. Run (pass). Commit `feat(audio): Core Audio device-change watcher`.

### Task 8: wire watcher -> WS push + reconnect
**Files:** Modify `src/jarvis/daemon.py` (start the watcher) + `api_server.py` (broadcast helper) + `listener.py`/`wispr_bridge.py` (reconnect hook); Test `tests/test_api_server_startup.py`
- [ ] Failing test: a watcher `on_change` callback calls `api_server.publish_state(...)` or a new `publish_event("devices_changed")` that broadcasts on the WS; and triggers the bridge to re-resolve its input (reconnect when the selected device reappears).
- [ ] Run (fail). Implement: daemon constructs `DeviceWatcher(on_change=...)`; on change -> broadcast `devices_changed` + call the bridge's reconnect. TTS already re-resolves per play (no hook needed). Run (pass). Commit `feat(audio): live device-change -> UI refresh + mic reconnect`.

## PHASE 4 - UI

### Task 9: AudioIOTab by endpoint id, no default option, live refresh
**Files:** Modify `ui/src/components/panel/tabs/AudioIOTab.tsx` + `ui/src/lib/api.ts`; build with vite
- [ ] Update `AudioDevices` type + `audioDevices()` to carry `{id,name,is_default,available}`. The two themed `<DeviceSelect>`s bind to `audio_input_endpoint_id`/`audio_output_endpoint_id` (value = id, label = name; show "(disconnected)" when `available===false`). **Remove** the "(System Default)"/"(Follow Windows default)" option entirely. Subscribe to the `devices_changed` WS event (via `openStateStream` or a new stream) to re-fetch the list live.
- [ ] `npx --no-install vite build` succeeds. Commit `feat(ui): audio device pickers by endpoint id, live refresh, no default option`.

## Self-review (vs spec)
- Spec: explicit+remembered by endpoint id -> Tasks 1-6,9. Remove follow-default -> Task 4,9. Adaptive live -> Tasks 7-8,9. First-run seed-from-OS-default-once -> add to Task 3 (seed on empty config). Reconnect-on-reappear -> Task 5,8 (mic) + Task 4 (TTS per-play). UI in/out split + disconnected state -> Task 9.
- Brownfield note: several steps say "read real code + adapt" (pycaw enumerator API, the bridge stream-open site, the api_server WS broadcast). Tests are behaviour-concrete; the executor reads the real code and adapts call sites.
