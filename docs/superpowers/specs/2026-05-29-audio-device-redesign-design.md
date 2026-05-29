# Audio Device Redesign Design

**Date:** 2026-05-29
**Status:** Draft (approach approved by user; awaiting spec review)
**Goal:** Replace the unstable "(Follow Windows default)" audio routing with an explicit, remembered, hot-plug-adaptive device system for both input (mic) and output (speaker), driven by Windows Core Audio.

## Plain-language summary

Today the audio Output offers "(Follow Windows default)", which follows whatever Windows calls the default - confusing and unstable for this user (their Windows default is a Realtek jack, not their actual speakers; their PD200X is a microphone whose "Speakers (PD200X)" endpoint is only a monitor passthrough). We replace it with: the app lists the *real* input and output devices, the user picks explicitly, the app *remembers* the choice by a stable id, and it *adapts live* when a device is plugged in or removed (no crash, auto-reconnect).

## Background and research

- **sounddevice/PortAudio cannot see hot-plugged devices** without reinitialising PortAudio, which would tear down the Wispr bridge's open input stream. So sounddevice is NOT the source of truth for the live device list. ([sounddevice #125](https://github.com/spatialaudio/python-sounddevice/issues/125))
- **pycaw / Windows Core Audio gives a live device list AND change events** via `IMMNotificationClient` (`OnDeviceAdded/OnDeviceRemoved/OnDeviceStateChanged/OnDefaultDeviceChanged`), without reinitialising PortAudio. ([pycaw notification example](https://github.com/AndreMiras/pycaw/blob/develop/examples/notification_client_example.py), [MS Device Events](https://learn.microsoft.com/en-us/windows/win32/coreaudio/device-events))
- **Persist by endpoint ID, not friendly name.** Endpoint IDs are stable, unique, and survive restarts/reconnects; friendly names collide for identical devices. ([MS Endpoint ID Strings](https://learn.microsoft.com/en-us/windows/win32/coreaudio/endpoint-id-strings))
- The current `output/audio_devices.py` already enumerates via pycaw Active endpoints and matches names to sounddevice indices. This redesign extends it (endpoint IDs, render/capture split, notifications) and removes the follow-default path added earlier in `tts.py` (`_resolve_output_device_live` follow branch) and the "(Follow Windows default)" UI option.

## Approved approach: A (live notifications)

## Components

### 1. Core Audio device service (`src/jarvis/output/audio_devices.py`, extended)
- `list_devices() -> {"inputs": [...], "outputs": [...]}` where each entry is `{id, name, is_default, available}` sourced from pycaw Core Audio (render = output, capture = input), Active endpoints, with the stable **endpoint id**. Live (reflects hot-plug). Fail-open to a sounddevice-only list if pycaw is unavailable.
- `resolve_endpoint_to_sd_index(endpoint_id, friendly_name, *, kind) -> Optional[int]` - map a persisted endpoint id (preferred) or name (fallback) to a current sounddevice playback/capture index, truncation-tolerant, WASAPI-preferred. Returns None if the device is currently absent (caller treats as "disconnected", reconnects later).
- Remove `get_default_output_name()`-driven follow-mode from the play path.

### 2. Live device-change notifications (`IMMNotificationClient`)
- A small notifier (in `audio_devices.py` or a new `output/device_watcher.py`) registers an `IMMNotificationClient` via pycaw, on its own COM thread. On any add/remove/state/default change it invokes a registered callback. NEVER touches PortAudio (safe with the Wispr stream open).
- The daemon registers a callback that: (a) pushes a `devices_changed` event to the React UI over the existing api_server WebSocket, and (b) triggers re-resolution of the selected input/output (reconnect when the chosen device reappears).

### 3. Persistence (`config.py`)
- New keys: `audio_output_endpoint_id` + `audio_output_name`, `audio_input_endpoint_id` + `audio_input_name`. Migrate the old `tts_output_device` / `wispr_mic_device` values forward where possible (config migration). The "(Follow Windows default)" / empty-string-means-default semantics are removed.
- First run / no selection: pick the current OS default once, persist its endpoint id, then it is purely remembered (never silently follows the OS default afterward).

### 4. TTS output (`tts.py`)
- Resolve `audio_output_endpoint_id` -> sd index fresh per play; if absent, log "output device disconnected" and fail-open (no crash); reconnect automatically when it reappears. Remove the follow-Windows-default branch. Preserve the WASAPI-exclusive-only-for-default guard.

### 5. Wispr input (`wispr_bridge.py` / `listener.py`)
- The wake-word mic uses `audio_input_endpoint_id` -> sd index. On a device-change notification (or config change), the bridge re-opens its input stream on the new/returned device without a full restart; if the device is absent, it waits and reconnects when it returns (no crash).

### 6. UI (`AudioIOTab.tsx`)
- Two clearly separated, themed lists (Input / Output) populated from `list_devices()`. **Remove the "(Follow Windows default)" / "(System Default)" option.** Show the remembered selection; if the selected device is currently absent, show it as "(disconnected)" but keep it selected. Subscribe to the `devices_changed` WS event to refresh the lists live.

## Files touched
- `src/jarvis/output/audio_devices.py` (extend), maybe new `src/jarvis/output/device_watcher.py` (IMMNotificationClient)
- `src/jarvis/config.py` (new endpoint-id keys + migration)
- `src/jarvis/output/tts.py` (output resolution, remove follow-default)
- `src/jarvis/listening/wispr_bridge.py` + `listener.py` (input resolution + reconnect)
- `src/jarvis/api_server.py` (device list endpoint by id, `devices_changed` WS push, persistence endpoints)
- `ui/src/components/panel/tabs/AudioIOTab.tsx` + `ui/src/lib/api.ts` (lists by id, remove default option, live refresh, disconnected state)
- `requirements.txt` (pycaw/comtypes already present)
- specs / `docs/llm_contexts.md` (n/a - no LLM context change)

## Testing
- Unit (mock pycaw + sounddevice): list_devices splits render/capture + carries endpoint ids + availability; resolve by id (and name fallback) tolerant of truncation; fail-open when pycaw missing. Config migration old->new keys. TTS resolves the persisted id and fails open when absent. Notifier invokes its callback on a simulated change (mock the IMMNotificationClient).
- Manual (user, after restart): pick input + output explicitly; unplug/replug a device and confirm the list refreshes live and audio reconnects.

## Out of scope
- The Wispr Flow dictation mic (set inside the Wispr Flow app, not Jarvis). Jarvis's "input" = the wake-word mic only.
- Reply language (stays English), memory work (separate milestone).

## Key decisions
- Approach A (live `IMMNotificationClient`) chosen by the user.
- Persist by endpoint id (research-backed) with friendly name as display + fallback.
- Remove follow-default entirely; first run seeds from OS default once.
