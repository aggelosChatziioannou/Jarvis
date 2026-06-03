# Embodied Furniture Actions — Living Room slice

**Date:** 2026-06-03
**Status:** Approved (design) — ready for implementation planning
**Area:** `ui/src/console/3d/*` (React/R3F dollhouse) + `src/jarvis/api_server.py` (FastAPI daemon)

## Problem

In the 3D dollhouse dashboard every furniture piece is wrapped in `<Interactive>` and
carries an action label ("Play / Pause", "Focus Mode", "Relax", "Now Playing"). Today a
click does **only three cosmetic things** ([ui/src/console/3d/Interactive.tsx](../../../ui/src/console/3d/Interactive.tsx) `onClick`):

1. fires a ripple ring,
2. calls `ix.activate(target)` — which is literally `setActiveTarget`, so the Operator
   walks to the anchor and plays a pose,
3. pushes a notification orb.

`ix.activate === setActiveTarget` ([DollhouseScene.tsx](../../../ui/src/console/3d/DollhouseScene.tsx)). **No real action ever fires.** The labels are
unwired promises: clicking the vinyl labelled "Play" makes the robot do a "press" pose
but Spotify does not play; "Focus Mode" lights nothing. Furniture *reacts* to backend
status (`services.spotify` makes the vinyl spin — the status poll lives in
`DashboardDataContext`/`dashboardApi.ts` and [SceneStateBridge.tsx](../../../ui/src/console/dashboard/SceneStateBridge.tsx) maps it into the
scene `services`) but that is a one-way mirror — the scene shows state, it never changes it.

## Goal

Make a furniture click perform the object's **real action**, fired in an **embodied**
way: click → robot walks to the object → **on arrival** the action executes. Action type
is **mixed per object** (real control / contextual panel / focus toggle). This spec
covers a **vertical slice: the Living Room Spotify cluster**, plus the reusable
arrival-fire mechanism and action-registry that later rooms will extend.

### Locked decisions (from brainstorming)

- **Mix per object** — each object maps to one action kind (designer-chosen map below).
- **Embodied timing** — the action fires when the Operator *arrives*, not on click.
- **Vertical slice first** — Living Room cluster only; mechanism built to extend.
- **Architecture = Approach A** — action registry + arrival callback + **direct backend
  endpoints** for real actions (voice-trigger kept only as a future fallback kind).
- **Focus Mode = DND + ambience + pause music** — see Object Map below.

> ⚠️ **Naming caution for the planner:** SceneContext **already** has an unrelated
> `focusMode` / `toggleFocusMode` ([SceneContext.tsx](../../../ui/src/console/3d/SceneContext.tsx)) that drives the cinematic
> **camera** room-lock (`FocusCamera`). The headphones "Focus Mode" in this spec is a
> **different** concept (DND). It MUST use a distinct name — this spec uses
> **`dndActive` / `toggleDnd`** — and must not touch the existing `focusMode`.

### Non-goals (this slice)

- Wiring the other 5 rooms (Office/Control/Wellness/Studio/Entrance). The registry and
  arrival mechanism are built to extend, but no other-room objects are wired here.
- A persistent backend Focus/DND state. Focus is a frontend scene state this slice (plus
  the real music-pause side effect). A backend DND flag is a future extension.
- The `living-sofa` "Relax" object — stays embodied-only (no action) this slice.

## Feasibility (verified)

- Spotify control exists: [mcps/spotify_mcp.py](../../../mcps/spotify_mcp.py) already implements `play_pause()`,
  `next_track()`, `previous_track()` via `spotipy` with the `user-modify-playback-state`
  scope (Premium required) and an `_ensure_active_device()` helper.
- `_spotify_status()` in [api_server.py](../../../src/jarvis/api_server.py) already authenticates with the cached OAuth
  token (read scope) and reads `current_playback()` — the new control endpoint reuses the
  same cached-token pattern with the modify scope.
- Open-Meteo/weather etc. are unrelated.

## Architecture

### 1. Arrival-fire mechanism (the core)

`ActiveTarget` already carries an `id`. The Operator currently has no "arrived" signal.

- Extend the `Interaction` interface ([dollhouseTypes.ts](../../../ui/src/console/3d/dollhouseTypes.ts)) with `arrive(id: string): void`.
- [OperatorCharacter.tsx](../../../ui/src/console/3d/OperatorCharacter.tsx) detects arrival each frame: when it has an `activeTarget`,
  its waypoint path is empty, and its world position is within `ARRIVE_EPSILON` of the
  anchor, it calls `arrive(activeTarget.id)` **exactly once per activation**. A
  `lastFiredIdRef` guards against re-firing; it naturally resets because a new activation
  has a different `id` (or the same `id` re-clicked sets a re-fire via an activation nonce
  — see Edge Cases).
- The dispatcher hook `useFurnitureActions()` supplies the `arrive` handler passed into
  the `ix` object built in `DollhouseScene`.

**Unit boundary:** `OperatorCharacter` knows *only* "I reached target X" — it has no idea
what X does. The dispatcher knows *only* "id X means action Y" — it has no idea about 3D.

### 2. Action registry

New file `ui/src/console/3d/furnitureActions.ts`:

```ts
export type FurnitureAction =
  | { kind: 'spotify'; op: 'playpause' | 'next' | 'prev' }
  | { kind: 'panel'; panel: 'nowplaying' }
  | { kind: 'focus' }
  | { kind: 'voice'; utterance: string } // reserved for future objects, not used this slice

export const FURNITURE_ACTIONS: Record<string, FurnitureAction> = {
  'living-vinyl':      { kind: 'spotify', op: 'playpause' },
  'living-nowplaying': { kind: 'panel',   panel: 'nowplaying' },
  'living-screen':     { kind: 'panel',   panel: 'nowplaying' },
  'living-headphones': { kind: 'focus' },
}
```

Unknown ids (e.g. `living-sofa`, all other-room objects) → no entry → dispatcher is a
no-op (the embodied walk still happens). This is how non-wired objects stay harmless.

### 3. Object map (Living Room slice)

| Object id | Label | Kind | On arrival |
|---|---|---|---|
| `living-vinyl` | Play / Pause | `spotify` | `POST /api/spotify/control {op:'playpause'}`; optimistic flip of local `services.spotify` so the vinyl starts/stops spinning instantly, re-synced on next status poll |
| `living-nowplaying` | Now Playing | `panel` | opens the Now-Playing glass card |
| `living-screen` | Entertainment | `panel` | opens the same Now-Playing glass card |
| `living-headphones` | Focus Mode | `focus` | toggles `dndActive`: suppress notification orbs, dim service glows + cool tint, **pause Spotify if playing**, show "FOCUS" HUD badge (badge label is cosmetic; state is `dndActive`, distinct from camera `focusMode`) |
| `living-sofa` | Relax | — | not in registry → embodied-only (no action this slice) |

### 4. Dispatch logic (`useFurnitureActions`)

- `spotify` → call `spotifyControl(op)` (new `services/spotifyControl.ts` → `POST
  /api/spotify/control`). For `playpause`, optimistically flip `services.spotify` via
  SceneContext so the vinyl reacts immediately; the real status poll reconciles within one
  interval. On `{ok:false}` revert the optimistic flip and surface a toast.
- `panel` → `setOpenPanel('nowplaying')` (new SceneContext UI state). Closing is via the
  card's ✕ or pressing the same/another object.
- `focus` → `toggleDnd()` (new SceneContext state `dndActive`, **separate from the existing
  camera `focusMode`**). Side effects:
  - orbs suppressed while active (NotificationOrbs receives `suppressed` / push is gated),
  - service glows dimmed + scene cool tint (a `focusActive` flag read by the furniture/
    lighting that already recolour on mood — reuse that prop path, do not add new per-mesh
    wiring beyond a single flag),
  - if `services.spotify` is currently playing, call `spotifyControl('playpause')` to
    pause,
  - a "FOCUS" badge renders in the dashboard overlay layer.
  - toggling off reverses ambience; it does **not** auto-resume music (explicit, avoids
    surprise playback).

`pushNotification` in SceneContext is gated while `dndActive` (the orb suppression).

### 5. Now-Playing panel

New `ui/src/console/dashboard/NowPlayingPanel.tsx`: a glass card matching
[SystemStatusPanel.tsx](../../../ui/src/console/dashboard/SystemStatusPanel.tsx) aesthetic (`rgba(17,24,39,0.95)`, cyan border, blur), positioned
bottom-centre of the dashboard content area. Renders only when `openPanel==='nowplaying'`.
Contents:

- album art (`image_url`), track title, artist, play state,
- transport buttons ◁ / ❚❚▶ / ▷, each calling `spotifyControl('prev'|'playpause'|'next')`,
- a ✕ close button (sets `openPanel=null`).

It reads live data from the existing dashboard status poll (no new poller). Empty/unauth
state shows "Spotify not connected".

### 6. Backend changes ([api_server.py](../../../src/jarvis/api_server.py))

- **New** `POST /api/spotify/control` with body `{op: 'playpause'|'next'|'prev'}`. Reuses
  the `_spotify_status` cached-token pattern but with scope
  `user-read-playback-state user-modify-playback-state user-read-currently-playing`. Mirrors
  the proven logic of `mcps/spotify_mcp.py` (`_ensure_active_device` then
  `pause/start/next/previous`). Returns `{ok: bool, is_playing: bool|null, reason?: str}`.
  Never raises to the client — all failures map to `{ok:false, reason}`.
- **Extend** `_spotify_status()` to also return `title`, `artist`, `image_url`,
  `is_playing` (it already reads the playback item for the artist; add the remaining
  fields). These optional fields are added to the existing **`ServiceStatus`** interface in
  [dashboardApi.ts](../../../ui/src/console/services/dashboardApi.ts) (there is no separate `Spotify` type today — `ServiceStatus`
  already carries optional `count?`/`active?`).

> **Spotify auth note (planner):** the new endpoint shares the same cached-token file
> (`mcps/.spotify_cache`) that `spotify_mcp.py` authed with the full
> `user-modify-playback-state` grant, so control works when the MCP flow has run. If a user
> only ever ran the read-scope status flow, the cached token lacks modify scope and
> `start/pause_playback` returns 403 → the endpoint maps this to `{ok:false, reason:
> "re-authorise Spotify"}` (intelligible, non-fatal).

### 7. Files touched

**New:**
- `ui/src/console/3d/furnitureActions.ts` — registry + `FurnitureAction` type + a pure
  `resolveAction(id)` helper.
- `ui/src/console/services/spotifyControl.ts` — `spotifyControl(op)` fetch wrapper.
- `ui/src/console/dashboard/NowPlayingPanel.tsx` — contextual card.
- `ui/src/console/services/useFurnitureActions.ts` — dispatcher hook returning `arrive(id)`.

**Edited:**
- `ui/src/console/3d/dollhouseTypes.ts` — add `arrive` to `Interaction`.
- `ui/src/console/3d/SceneContext.tsx` — add `dndActive`+`toggleDnd` (distinct from the
  existing `focusMode`), `openPanel`+`setOpenPanel`, and gate `pushNotification` when
  `dndActive`.
- `ui/src/console/3d/OperatorCharacter.tsx` — arrival detection → `arrive(id)`.
- `ui/src/console/3d/DollhouseScene.tsx` — build `ix.arrive` from `useFurnitureActions`;
  render `NowPlayingPanel` + FOCUS badge in the overlay layer; pass `focusActive` flag down.
- `ui/src/console/services/dashboardApi.ts` — `spotifyControl(op)` (reusing the existing
  `BASE` URL pattern: relative when served on port 38130, else `http://127.0.0.1:38130`) +
  extended `ServiceStatus` fields.
- `src/jarvis/api_server.py` — new control endpoint + extended status.

**Explicitly NOT edited:** `Interactive.tsx` — the arrival-fire is purely additive
(`OperatorCharacter` + `ix.arrive`); the existing ripple/notify/walk behaviour on click is
preserved unchanged.

## Data flow

```
click (Interactive.onClick)
  └─ ix.activate({id, anchor})            → SceneContext.activeTarget set
       └─ OperatorCharacter walks path
            └─ arrives (pos≈anchor, path empty, once)
                 └─ ix.arrive(id)
                      └─ useFurnitureActions: resolveAction(id)
                           ├─ spotify → POST /api/spotify/control  (+optimistic services flip)
                           ├─ panel   → setOpenPanel('nowplaying')
                           └─ focus   → toggleFocus (+pause if playing)
status poll (existing) → SceneStateBridge → services → furniture glows reconcile
```

## Edge cases & error handling

- **Re-click same object:** clicking an already-active object should re-fire on arrival
  (e.g. play, then pause). Because `lastFiredIdRef` blocks same-id re-fire, `activate`
  attaches a monotonic `nonce` to `ActiveTarget`; arrival compares `nonce`, not just `id`,
  so a fresh click re-arms even when already standing there (fires immediately).
- **Spotify failure** (no Premium / no active device / token lacks modify scope / not
  authorised): endpoint returns `{ok:false, reason}`; UI reverts any optimistic flip and
  shows a subtle toast (e.g. "No active Spotify device"). Scene never crashes.
- **Focus while nothing playing:** ambience toggles; the pause call is skipped (guarded by
  `services.spotify`).
- **Panel open with no Spotify auth:** card renders an empty "Spotify not connected" state.
- **Operator never reaches anchor** (path edge case): arrival uses an epsilon + a max-time
  fallback so the action still fires shortly after the walk animation settles, preventing a
  dead click.
- **Unknown id:** dispatcher no-ops; embodied walk unaffected.

## Testing

- **Backend (pytest, run individually per the repo's capture caveat):**
  `/api/spotify/control` with `spotipy` mocked — success, no-device, no-premium, no-token
  paths all return well-formed `{ok,...}`; extended `_spotify_status` shape.
- **Frontend (vitest):**
  - `resolveAction(id)` returns the correct descriptor for each Living id and `undefined`
    for unknown ids.
  - dispatcher: each action kind triggers the right effect (mock `spotifyControl`,
    `setOpenPanel`, `toggleFocus`) — including the focus→pause side effect when playing.
  - arrival-fires-**once** + re-fires on a new nonce (pure logic extracted from the frame
    loop so it is unit-testable without a canvas).
- **3D behaviour:** code-verified + live-confirmed in the browser — canvas click
  hit-testing is not automatable via synthetic DOM events (`offsetX=0`), a known constraint
  of this dollhouse.
- **Gate:** `npm run build` (tsc strict, exit 0) + `npx vitest run` green; daemon import
  smoke (`python -c "import jarvis.api_server"`).

## Success criteria

- Click the vinyl → robot walks → **Spotify actually toggles** and the vinyl starts/stops
  spinning.
- Click the headphones → robot walks → music pauses, "FOCUS" badge shows, notification
  orbs go silent; click again → ambience restored.
- Click the hologram or the screen → robot walks → Now-Playing card opens with working
  ◁ ❚❚▶ ▷ buttons and live track info.
- Non-wired objects (sofa, other rooms) behave exactly as before (embodied walk only).
- `npm run build` + `vitest` pass; no new console errors beyond the known-benign ones.
