# Unified Console (ui/src/console) Spec

Covers the redesigned JARVIS console served at `/panel`. Design doc:
`docs/superpowers/specs/2026-06-02-unified-console-design.md`. Phase plan:
`docs/superpowers/plans/2026-06-02-unified-console-phase0.md`.

## Purpose

A single dark sci-fi console with five categories: Dashboard (3D dollhouse),
Memory (knowledge graph + timeline), Audio I/O, Live Logs, and Settings
(Settings arrives in Phase 5). It replaces the legacy `/panel` control panel.

## Routing (key invariant)

`ui/src/App.tsx` (react-router):
- `/` -> `pages/Home` (the floating **orb HUD**, loaded by the desktop
  `WebFloatingHUD` card). **This must keep working** - the console lives only
  under `/panel` and must never change the orb route, its transparent body
  background, or the boot screen.
- `/panel` -> `console/ConsoleRoot` (lazy). Internal page switching is
  state-based (`activePage`: dashboard | memory | audio | logs), no nested
  router. Default page: `dashboard`.

The daemon serves `ui/dist` with an SPA fallback (`api_server.py`), so `/panel`
resolves to the same bundle; assets are absolute (`/assets/...`).

## Module layout

`ui/src/console/` is self-contained: `ConsoleRoot.tsx`, `sections/`, `zones/`,
`3d/`, `dashboard/`, `context/`, `hooks/`, `data/`, `types/`, `lib/`,
`components/` (incl. its own `components/ui/` shadcn set + `components/shell/`).
Internal imports use the `@/console/...` alias; the shared daemon client is the
only cross-module dependency (`@/lib/api`).

## Service seam (`console/services/`)

All daemon I/O goes through `services/seam.ts`, which wraps the shared
`ui/src/lib/api.ts` (REST + `/ws/state` + `/ws/logs`) and adds `fetchVersion()`
(`GET /api/version`).

**Fail-open:** when the daemon is unreachable, calls fall back gracefully and
pages keep rendering with their demo/mock data (the console stays alive and
screenshotable). `useConnection()` exposes `{ state, connected, version }`;
`connected` is false until the daemon answers.

## StatusBar contract (Phase 0)

`console/components/shell/StatusBar.tsx` shows live values via `useConnection`:
- left: activity label + colour from `statusDisplay(state, connected)` -
  Offline (grey) when disconnected, Muted (rose) when muted, otherwise
  Idle/Listening/Thinking/Speaking.
- centre: connection dot + Connected/Disconnected + `v<version>`.
- right: temperature placeholder (`-`, wired in Phase 4) + today's date.

`console/lib/statusMap.ts` holds the pure mapping (unit-tested).

## Per-page data wiring status

| Page | Phase | Data source |
|---|---|---|
| Dashboard | 4 | mock today; later `/ws/state` + `/api/system/metrics` + `/api/services/status` |
| Memory | 3 | DONE (read + reminders CRUD) - real graph (`/api/graph/nodes` -> 3-branch view), timeline (reminders `/api/reminders` + diary `/api/memory`); EventStream add/complete/snooze wired; node CRUD-from-graph + detail-panel reminder delete/reschedule deferred. Provider `MemoryDataContext` fail-open to mock |
| Audio I/O | 2 | DONE - real state (`/ws/state`), devices (`/api/audio/devices`), sensitivity + device select (`/api/config`), mute/tone; waveform/spectrum/orb-pulse kept as browser mic preview |
| Live Logs | 1 | DONE - live `/ws/logs` (backfills ~100 on connect) via `console/lib/logMap.ts`; fail-open to demo generator |
| Settings | 5 | not built yet |

Phase 0 wires only the shell StatusBar; pages keep their mock/demo data until
their phase.

## Build & test

- Build: `cd ui && npm run build` (`tsc -b` strict + `verbatimModuleSyntax`,
  then `vite build`). Test files are excluded from the app build.
- Unit: `cd ui && npm run test` (Vitest; pure logic only, e.g. `statusMap`,
  `audioEngine`, `logsLogic`).
- Runtime: serve `ui/dist` (daemon or `vite preview`); `/panel` renders all
  pages and `/` renders the orb, with no console errors beyond benign
  daemon-unreachable network errors when offline.
