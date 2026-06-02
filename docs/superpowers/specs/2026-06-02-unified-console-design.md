# JARVIS Unified Console - Design Spec

- **Date:** 2026-06-02
- **Status:** Approved design (user) -> phased implementation
- **Author:** Claude (brainstorming session with user)
- **Branch:** `feat/unified-console` (targets `develop` per project workflow; created from the current working tip so the verified `api_server.py` endpoints are present)
- **Frontend design source:** `C:\Users\aggel\Desktop\jarvis_frontend` (standalone Vite app, mock data)
- **Backend / integration target:** `c:\Users\aggel\Jarvis-src` (the `jarvis` daemon + `ui/`)

---

## 1. Goal

Replace the current Jarvis **control console** (served at `/panel`) with the newly redesigned unified console, and wire its currently-mock pages to the real Jarvis daemon. The small floating **orb HUD** (served at `/`) is preserved untouched.

The redesigned console has five categories:

| Icon | Page | State today | Target |
|---|---|---|---|
| Home | Dashboard (3D dollhouse) | 100% mock | Live state mirror + functional click panels |
| Brain | Memory (graph + timeline) | 100% mock | Full CRUD on the real 3-branch graph + reminders |
| Mic | Audio I/O | browser-local | Control panel for the real assistant's ears |
| ScrollText | Live Logs | random mock feed | Real `/ws/logs` stream |
| Settings | Settings (NEW 5th tab) | n/a | Config / models / MCP / wake / TTS / service auth |

## 2. User decisions (locked)

1. **Dashboard** = living state mirror **and** functional buttons (objects open a live info panel with an action button; not a real smart home).
2. **Audio I/O** = real control of the assistant's ears: live state, real device selection, real sensitivity (config; "applies after restart"). The waveform/spectrum stay as a local browser input preview.
3. **Memory** = full management (view / create / edit / delete memories and reminders).
4. **Memory structure** = the real 3-branch taxonomy (`user` / `directives` / `world`), not the design's 5 cosmetic categories.
5. **Settings** = a new 5th tab so the new console fully replaces the old one.
6. **System Status panel** metrics = real weather + real computer metrics (CPU / RAM / VRAM / uptime / active model).
7. **Service glows** = wire all of them: Weather, Reminders & Tasks (ready now), Spotify, Google (Gmail + Calendar) (need OAuth), plus anything else that proves useful.
8. **3D click** = open a small live-info panel with an action button.

## 3. Architecture

### 3.1 Where it lives
Integrate the redesigned console **into the existing `ui/` app** under the `/panel` route, keeping `/` (orb HUD) intact.

- `ui/src/App.tsx` keeps `react-router`: `/` -> `Home` (orb, unchanged); `/panel` -> the **new console shell** (TitleBar + Sidebar + StatusBar + lazy pages).
- The new console's internal navigation stays state-based (`activePage`) inside the `/panel` route - no nested router needed.
- The ported 3D module, zones, sections, hooks, data, and tokens move from the design app into `ui/src/`. Tailwind tokens, fonts, and keyframes are merged into `ui/`'s `tailwind.config.js` / `index.css`.
- `src/jarvis/api_server.py` already serves `ui/dist` with an SPA fallback ([api_server.py:790](../../../src/jarvis/api_server.py)), so no serving changes are required. `web_console_window.py` continues to load `http://127.0.0.1:38130/panel`.

**Why not alternatives:** a standalone app on `:3000` means two servers + CORS + it is not a true replacement; deleting `ui/` wholesale would drop the orb HUD at `/`.

### 3.2 Integration seam (the only supported coupling)
The `jarvis` core has no knowledge of the UI (per `desktop_app.spec.md`). All data flows through the **HTTP + WebSocket API** in `api_server.py`. New UI needs become new endpoints there, never direct imports of core internals.

### 3.3 Frontend service seam
Replace the design app's `data/*Mock.ts` with a thin `services/` layer built on the existing [ui/src/lib/api.ts](../../../ui/src/lib/api.ts):
- one "fetch real data" (REST) + one "subscribe live" (WebSocket) function per page;
- **fail-open fallback to demo/mock** when the daemon is unreachable, so the console stays alive (mirrors the Audio page's existing Live/Demo pattern).

The polished visuals are unchanged; only the data source changes.

## 4. Backend additions (new endpoints)

All additive, local-only, privacy-first. Each ships with `pytest` coverage. The graph store and reminder store already implement the underlying operations internally; these endpoints are thin bridges.

| Area | New endpoint(s) | Notes |
|---|---|---|
| Version | `GET /api/version` | app/daemon version for StatusBar |
| Memory graph | `GET /api/graph/nodes`, `GET /api/graph/node/{id}`, `POST /api/graph/node`, `PUT /api/graph/node/{id}`, `DELETE /api/graph/node/{id}`, `GET /api/graph/search`, `GET /api/graph/stats` | reuse `GraphMemoryStore`; root + 3 fixed branches are non-deletable |
| Reminders | `GET /api/reminders`, `POST /api/reminders`, `PUT /api/reminders/{id}`, `DELETE /api/reminders/{id}` | reuse `ReminderStore`; supports snooze / complete / cancel / reschedule |
| System metrics | `GET /api/system/metrics` | CPU%, RAM, GPU/VRAM (nvidia-smi if present), uptime, active model(s) via `ollama ps` |
| Service status | `GET /api/services/status` | per service: enabled, connected/authed, cheap live snapshot (weather now, next reminder, now-playing/unread/next-event when authed) |
| Live activity | extend `/ws/state` payload with a current-activity field (e.g. `activeTool` / `activeService`) | drives "glow when running now"; backend instrumented where a tool runs |
| Service auth | `GET /api/services/{id}/auth-url` (+ OAuth callback handler) | Spotify + Google connect flows (Phase 6) |

Existing endpoints reused as-is: `/api/state` + `/ws/state`, `/ws/logs` + `/api/logs`, `/api/config` (GET/PATCH, masked), `/api/audio/devices`, `/api/audio/test-tone`, `/api/mcps`, `/api/memory` (diary summaries), `/api/llm/models`, `/api/eastereggs`, `/api/fastpaths`, `/api/command/*`.

## 5. Per-page wiring

### 5.1 Live Logs (no backend change)
Consume `/ws/logs` (+ `/api/logs?limit=N` backfill). Map backend levels (`info/warning/error/fast-path/mcp/easter-egg`) to the design's (`info/success/warn/error/debug`) and best-effort source tags (System/Memory/Audio/Services/Wake/Voice) from content. Filters, search, sparkline run on the real buffer.

### 5.2 Audio I/O (existing endpoints)
- Orb + listening state from `/ws/state` (idle/listening/thinking/speaking, muted).
- Input/output device selects from `/api/audio/devices`; selection persisted via `/api/config` (`audio_input_endpoint_id`, `tts_output_device`). Test tone via `/api/audio/test-tone`.
- Sensitivity sliders mapped to real config fields (`wispr_wake_threshold`, `vad_silero_threshold`, `vad_silero_neg_threshold`, `endpoint_silence_ms`, ...) with a clear "applies after restart" notice.
- Waveform/spectrum remain a labelled **local browser-mic preview**; mute/trigger via `/api/command/*`.

### 5.3 Memory (new graph + reminders endpoints)
- Graph renders the real `user` / `directives` / `world` branches and their children; node click -> detail panel; edit/create/delete via the new graph endpoints. A real `MemoryNode` is a container holding many newline facts in `data`; the UI exposes node fields (name, description, data, importance, permanent, ttl) plus the per-fact view.
- Timeline = real reminders (new endpoints) + episodic = diary summaries (`/api/memory`, read-only because they are auto-generated). Calendar dots from both.
- Full create/edit/delete for reminders; "forget"/delete + edit for graph facts.

### 5.4 Dashboard (state + metrics + services)
- Operator character / mood mirror `/ws/state`.
- System Status panel: weather (existing weather tool data via `/api/services/status`) + computer metrics (`/api/system/metrics`).
- Service furniture glows from `/api/services/status` (+ live "running now" from `/ws/state`). Click -> live-info panel + action button (play/pause, open mail, next event, etc.). Weather + reminders functional immediately; Spotify/Google after Phase 6 auth.

### 5.5 Settings (new tab, existing endpoints)
Config (`/api/config`, masked secrets), models (`/api/llm/models`), MCP toggles (`/api/mcps`), wake/VAD/TTS/voice fields, easter eggs/fast paths, plus "Connect" buttons for Spotify/Google (Phase 6).

## 6. Phase roadmap (build + test one at a time)

Each phase is independently shippable and verified before the next.

0. **Foundation** - integrate the design into `ui/` at `/panel`, keep orb at `/`; build the `services/` seam; wire the shell StatusBar to real state/health/version. Backend: `GET /api/version`.
1. **Live Logs** - real `/ws/logs`. No backend change.
2. **Audio I/O** - real state + devices + sensitivity (config). No new backend.
3. **Memory** - graph + reminders endpoints; 3-branch graph; full CRUD; timeline.
4. **Dashboard** - state mirror; `/api/system/metrics` + `/api/services/status`; glows + click panels.
5. **Settings** - 5th tab over existing endpoints.
6. **Services live** - OAuth (Spotify + Google); real now-playing / unread / next-event; live-activity instrumentation on `/ws/state`.

## 7. Verification

- **Backend:** `pytest` for every new endpoint (happy path + guard rails, e.g. cannot delete root/fixed branches; reminder status transitions).
- **Frontend logic:** Vitest for the service-seam mapping (log level/source mapping, graph shaping, reminder shaping).
- **Visual/runtime:** `ui` build (`tsc -b && vite build`) exits 0; Playwright screenshot per page against the daemon (or demo fallback); 0 console errors. 3D canvas clicks verified live.
- Run evals only if an LLM prompt/context changes (none expected in Phases 0-5).

## 8. Constraints (project rules)

- Privacy-first: all new endpoints local-only; no secrets leaked (config GET stays masked; logs stay scrubbed).
- Spec files (`*.spec.md`) created/updated next to new code (e.g. `ui/console.spec.md`, endpoint specs) during each phase.
- Update `docs/llm_contexts.md` if any phase adds/changes an LLM context (Phase 6 service summarisation is the only likely candidate).
- British English everywhere; emojis in user-facing CLI output; conventional commits; PR targets `develop`.

## 9. Risks & gotchas

- **Two log-level vocabularies** - map carefully; keep `meta` for expandable detail.
- **Sensitivity needs restart** - models stay resident; never imply live effect. Surface a restart hint.
- **Two mics** - the browser console mic is not the assistant's mic; label the preview honestly; real "is it listening" comes from `/ws/state`.
- **OAuth scope** - Spotify (Premium for playback) + Google are the heaviest part; isolated in Phase 6 so Phases 0-5 ship without them.
- **3D performance** - keep the design app's perf settings (dpr, ContactShadows frames=1, PCFShadowMap); do not "fix" benign three.js warnings.
- **Strict tsc** (`verbatimModuleSyntax`) - type-only imports use `import type`.
- **Orb HUD must keep working** - `/` route and the WebFloatingHUD card stay untouched; verify after the `ui/` restructure.
