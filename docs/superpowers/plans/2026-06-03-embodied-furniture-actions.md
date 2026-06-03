# Embodied Furniture Actions Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a click on 3D dollhouse furniture perform the object's real action, fired in an *embodied* way — the robot walks to the object and the action fires on arrival — for the Living Room Spotify cluster.

**Architecture:** Approach A. A pure **action registry** (`id → action`) + a pure **effect planner** decide what each object does. The Operator detects arrival and calls `ix.arrive(id)`; a dispatcher hook turns that into effects (real Spotify control via a new backend endpoint, a Now-Playing panel, or a DND/Focus toggle). The Operator knows only "I reached X"; the dispatcher knows only "X means effect Y". Non-registered objects keep today's embodied-walk-only behaviour.

**Tech Stack:** React 19 + @react-three/fiber + three (UI under `ui/`), Vitest (pure-logic tests), FastAPI + spotipy (daemon under `src/jarvis/`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-03-embodied-furniture-actions-design.md`

**Repo facts the worker needs:**
- UI build gate: `cd ui && npm run build` (runs `tsc -b` strict — type-only imports MUST use `import type`).
- UI tests: `cd ui && npx vitest run <file>`; existing pure-logic tests live in `ui/src/console/lib/*.test.ts`.
- Backend tests: from repo root, `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest <file> -v` (run test files individually; the cp1252 console needs the UTF-8 env for emoji).
- The daemon serves the built UI; **after backend changes the user must restart Jarvis** (the running daemon holds old code in memory).
- Canvas click hit-testing is NOT automatable via synthetic DOM events in this dollhouse — 3D interaction is code-verified + live-confirmed. All unit tests target **pure logic** extracted out of the frame loop / React.

---

## Chunk 1: Backend — Spotify control endpoint + status fields

**Files:**
- Modify: `src/jarvis/api_server.py` (add `POST /api/spotify/control`; extend `_spotify_status`)
- Test: `tests/test_api_spotify_control.py` (create)

### Task 1.1: Extend `_spotify_status` with title/artist/image_url/is_playing

**Files:** Modify `src/jarvis/api_server.py` (the `if cur and cur.get("item"):` block, ~lines 936-941)

- [ ] **Step 1: Add the fields.** Find this block in `_spotify_status`:

```python
                if cur and cur.get("item"):
                    t = cur["item"]
                    artist = (t.get("artists") or [{}])[0].get("name", "")
                    playing = bool(cur.get("is_playing"))
                    data["active"] = playing
                    data["detail"] = f"{'▶' if playing else '⏸'} {t.get('name', '')} — {artist}".strip(" —")
                else:
                    data["detail"] = "idle"
```

Replace it with (adds 4 fields; behaviour otherwise unchanged):

```python
                if cur and cur.get("item"):
                    t = cur["item"]
                    artist = (t.get("artists") or [{}])[0].get("name", "")
                    playing = bool(cur.get("is_playing"))
                    imgs = (t.get("album") or {}).get("images") or []
                    data["active"] = playing
                    data["title"] = t.get("name", "")
                    data["artist"] = artist
                    data["image_url"] = imgs[0].get("url") if imgs else None
                    data["is_playing"] = playing
                    data["detail"] = f"{'▶' if playing else '⏸'} {t.get('name', '')} — {artist}".strip(" —")
                else:
                    data["detail"] = "idle"
```

- [ ] **Step 2: Smoke-import.** Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); import jarvis.api_server; print('import ok')"`
  Expected: `import ok`.

### Task 1.2: Failing test for the control endpoint (validation + auth paths)

**Files:** Create `tests/test_api_spotify_control.py`

- [ ] **Step 1: Write the failing test.**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import types
import jarvis.api_server as api
from fastapi.testclient import TestClient

client = TestClient(api.app)


def test_unknown_op_returns_not_ok():
    r = client.post("/api/spotify/control", json={"op": "frobnicate"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "op" in body["reason"]


def test_not_authorised_when_no_cache(monkeypatch):
    # No client id / cache => endpoint must report not authorised, never raise.
    monkeypatch.setattr(api, "_mcp_env", lambda: {})
    r = client.post("/api/spotify/control", json={"op": "playpause"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_playpause_happy_path(monkeypatch, tmp_path):
    # Fake spotipy so we never touch the network.
    calls = {"paused": False, "started": False}

    class FakeSpotify:
        def __init__(self, *a, **k): pass
        def devices(self): return {"devices": [{"id": "dev1", "is_active": True}]}
        def current_playback(self): return {"is_playing": True, "item": {"name": "X"}}
        def pause_playback(self, *a, **k): calls["paused"] = True
        def start_playback(self, *a, **k): calls["started"] = True
        def next_track(self, *a, **k): pass
        def previous_track(self, *a, **k): pass

    class FakeOAuth:
        def __init__(self, *a, **k):
            self.cache_handler = types.SimpleNamespace(get_cached_token=lambda: {"access_token": "t"})

    fake_spotipy = types.ModuleType("spotipy")
    fake_spotipy.Spotify = FakeSpotify
    fake_oauth = types.ModuleType("spotipy.oauth2")
    fake_oauth.SpotifyOAuth = FakeOAuth
    monkeypatch.setitem(sys.modules, "spotipy", fake_spotipy)
    monkeypatch.setitem(sys.modules, "spotipy.oauth2", fake_oauth)

    cache = tmp_path / ".spotify_cache"
    cache.write_text("{}")
    monkeypatch.setattr(api, "_MCPS_ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(api, "_mcp_env", lambda: {"SPOTIFY_CLIENT_ID": "id"})

    r = client.post("/api/spotify/control", json={"op": "playpause"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["is_playing"] is False  # was playing -> now paused
    assert calls["paused"] is True
```

- [ ] **Step 2: Run it to verify it fails.** Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/test_api_spotify_control.py -v`
  Expected: FAIL — `/api/spotify/control` returns 404 (route not defined yet).

### Task 1.3: Implement `POST /api/spotify/control`

**Files:** Modify `src/jarvis/api_server.py` — add immediately AFTER the `_spotify_status` function (after its `return data`).

- [ ] **Step 1: Add a request model + the route.** (pydantic `BaseModel` is already imported in this module — used by `ReminderCreate` etc.)

```python
class SpotifyControlBody(BaseModel):
    op: str  # 'playpause' | 'next' | 'prev'


@app.post("/api/spotify/control")
def spotify_control(body: SpotifyControlBody) -> Dict[str, Any]:
    """Control Spotify playback (Premium). Never raises to the client — every
    failure maps to {ok: False, reason}. Mirrors mcps/spotify_mcp.py logic but
    reuses the cached OAuth token like _spotify_status."""
    op = (body.op or "").strip().lower()
    if op not in ("playpause", "next", "prev"):
        return {"ok": False, "reason": "unknown op"}
    try:
        env = _mcp_env()
        cache_path = _MCPS_ENV_PATH.parent / ".spotify_cache"
        if not (env.get("SPOTIFY_CLIENT_ID") and cache_path.exists()):
            return {"ok": False, "reason": "not authorised"}

        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        auth = SpotifyOAuth(
            client_id=env["SPOTIFY_CLIENT_ID"],
            client_secret=env.get("SPOTIFY_CLIENT_SECRET", ""),
            redirect_uri=env.get("SPOTIFY_REDIRECT_URI", ""),
            scope="user-read-playback-state user-modify-playback-state user-read-currently-playing",
            cache_path=str(cache_path),
            open_browser=False,
        )
        try:
            token = auth.cache_handler.get_cached_token()
        except Exception:
            token = None
        if not token:
            return {"ok": False, "reason": "re-authorise Spotify"}

        sp = spotipy.Spotify(auth_manager=auth)

        device_id = None
        try:
            devices = (sp.devices() or {}).get("devices", [])
            active = next((d for d in devices if d.get("is_active")), None)
            device_id = ((active or (devices[0] if devices else None)) or {}).get("id")
        except Exception:
            device_id = None

        try:
            cur = sp.current_playback()
        except Exception:
            cur = None

        if op == "playpause":
            if cur and cur.get("is_playing"):
                sp.pause_playback()
                is_playing = False
            else:
                sp.start_playback(device_id=device_id)
                is_playing = True
        elif op == "next":
            sp.next_track(device_id=device_id)
            is_playing = True
        else:  # prev
            sp.previous_track(device_id=device_id)
            is_playing = True

        # Bust the status cache so the dashboard reflects the change on next poll.
        _spotify_cache["data"] = None
        _spotify_cache["at"] = 0.0
        return {"ok": True, "is_playing": is_playing}
    except Exception as e:
        debug_log(f"spotify control failed: {type(e).__name__}", "tools")
        reason = "no active device" if "NO_ACTIVE_DEVICE" in str(e).upper() else "spotify error"
        return {"ok": False, "reason": reason}
```

- [ ] **Step 2: Run tests to verify they pass.** Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/test_api_spotify_control.py -v`
  Expected: 3 passed.

- [ ] **Step 3: Commit.**

```bash
git add src/jarvis/api_server.py tests/test_api_spotify_control.py
git commit -m "feat(api): POST /api/spotify/control + now-playing fields in status"
```

---

## Chunk 2: Frontend foundation — types, context, registry, pure planner

**Files:**
- Modify: `ui/src/console/3d/dollhouseTypes.ts` (`Interaction.arrive`, `ActiveTarget.nonce`)
- Modify: `ui/src/console/3d/SceneContext.tsx` (`activate` w/ nonce, `dndActive`/`toggleDnd`, `openPanel`/`setOpenPanel`, DND-gated notifications)
- Modify: `ui/src/console/services/dashboardApi.ts` (extend `ServiceStatus`, add `spotifyControl`)
- Create: `ui/src/console/3d/furnitureActions.ts` (registry + pure planner + `shouldFireArrival`)
- Test: `ui/src/console/3d/furnitureActions.test.ts` (create)

### Task 2.1: Type additions

**Files:** Modify `ui/src/console/3d/dollhouseTypes.ts`

- [ ] **Step 1:** Add `nonce` to `ActiveTarget`:

```ts
export interface ActiveTarget {
  id: string
  position: [number, number, number]
  rotationY: number
  pose: OperatorPose
  nonce?: number // bumped on every activate() so re-clicking the same object re-fires on arrival
}
```

- [ ] **Step 2:** Add `arrive` to `Interaction`:

```ts
export interface Interaction {
  activate: (target: ActiveTarget) => void
  hover: (obj: HoveredObject | null) => void
  notify: (from: [number, number, number], color?: string) => void
  activeId: string | null
  arrive: (id: string) => void // fired once when the Operator reaches the active object
}
```

### Task 2.2: Registry + pure planner + arrival predicate (TDD)

**Files:** Create `ui/src/console/3d/furnitureActions.ts` and `ui/src/console/3d/furnitureActions.test.ts`

- [ ] **Step 1: Write the failing test** (`furnitureActions.test.ts`):

```ts
import { describe, it, expect } from 'vitest'
import { resolveAction, planFurnitureEffects, shouldFireArrival } from './furnitureActions'

describe('resolveAction', () => {
  it('maps the wired Living objects', () => {
    expect(resolveAction('living-vinyl')).toEqual({ kind: 'spotify', op: 'playpause' })
    expect(resolveAction('living-nowplaying')).toEqual({ kind: 'panel', panel: 'nowplaying' })
    expect(resolveAction('living-screen')).toEqual({ kind: 'panel', panel: 'nowplaying' })
    expect(resolveAction('living-headphones')).toEqual({ kind: 'focus' })
  })
  it('returns undefined for non-wired objects', () => {
    expect(resolveAction('living-sofa')).toBeUndefined()
    expect(resolveAction('office-laptop')).toBeUndefined()
  })
})

describe('planFurnitureEffects', () => {
  it('spotify playpause => optimistic toggle + control', () => {
    expect(planFurnitureEffects({ kind: 'spotify', op: 'playpause' }, { spotifyPlaying: true, dndActive: false }))
      .toEqual([{ type: 'spotify', op: 'playpause', optimisticToggle: true }])
  })
  it('panel => openPanel', () => {
    expect(planFurnitureEffects({ kind: 'panel', panel: 'nowplaying' }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([{ type: 'openPanel', panel: 'nowplaying' }])
  })
  it('focus while playing+off => toggleDnd then pauseMusic', () => {
    expect(planFurnitureEffects({ kind: 'focus' }, { spotifyPlaying: true, dndActive: false }))
      .toEqual([{ type: 'toggleDnd' }, { type: 'pauseMusic' }])
  })
  it('focus while not playing => only toggleDnd', () => {
    expect(planFurnitureEffects({ kind: 'focus' }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([{ type: 'toggleDnd' }])
  })
  it('focus when already active (turning off) => only toggleDnd, no pause', () => {
    expect(planFurnitureEffects({ kind: 'focus' }, { spotifyPlaying: true, dndActive: true }))
      .toEqual([{ type: 'toggleDnd' }])
  })
})

describe('shouldFireArrival', () => {
  it('fires once per nonce', () => {
    expect(shouldFireArrival(null, true, 1)).toBe(true)
    expect(shouldFireArrival(1, true, 1)).toBe(false) // already fired this activation
    expect(shouldFireArrival(1, true, 2)).toBe(true)  // new activation (re-click)
  })
  it('does not fire before arrival', () => {
    expect(shouldFireArrival(null, false, 1)).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails.** Run: `cd ui && npx vitest run src/console/3d/furnitureActions.test.ts`
  Expected: FAIL — module `./furnitureActions` not found.

- [ ] **Step 3: Implement `furnitureActions.ts`:**

```ts
// Registry + pure decision logic for "embodied" furniture actions.
// Pure (no React, no 3D) so it is unit-testable. See the dispatcher hook
// (useFurnitureActions) for the side-effecting execution of the effects.

export type FurnitureAction =
  | { kind: 'spotify'; op: 'playpause' | 'next' | 'prev' }
  | { kind: 'panel'; panel: 'nowplaying' }
  | { kind: 'focus' }
  | { kind: 'voice'; utterance: string } // reserved for future objects; unused this slice

// Map of object id -> action. Unknown ids resolve to undefined and stay
// embodied-walk-only (the dispatcher no-ops).
export const FURNITURE_ACTIONS: Record<string, FurnitureAction> = {
  'living-vinyl': { kind: 'spotify', op: 'playpause' },
  'living-nowplaying': { kind: 'panel', panel: 'nowplaying' },
  'living-screen': { kind: 'panel', panel: 'nowplaying' },
  'living-headphones': { kind: 'focus' },
}

export function resolveAction(id: string): FurnitureAction | undefined {
  return FURNITURE_ACTIONS[id]
}

export type FurnitureEffect =
  | { type: 'spotify'; op: 'playpause' | 'next' | 'prev'; optimisticToggle: boolean }
  | { type: 'openPanel'; panel: 'nowplaying' }
  | { type: 'toggleDnd' }
  | { type: 'pauseMusic' }

export interface DispatchCtx {
  spotifyPlaying: boolean
  dndActive: boolean
}

export function planFurnitureEffects(action: FurnitureAction, ctx: DispatchCtx): FurnitureEffect[] {
  switch (action.kind) {
    case 'spotify':
      return [{ type: 'spotify', op: action.op, optimisticToggle: action.op === 'playpause' }]
    case 'panel':
      return [{ type: 'openPanel', panel: action.panel }]
    case 'focus': {
      const enabling = !ctx.dndActive
      const effects: FurnitureEffect[] = [{ type: 'toggleDnd' }]
      if (enabling && ctx.spotifyPlaying) effects.push({ type: 'pauseMusic' })
      return effects
    }
    case 'voice':
      return []
  }
}

// True when the Operator has just arrived for an activation we have not fired yet.
export function shouldFireArrival(firedNonce: number | null, arrived: boolean, nonce: number): boolean {
  return arrived && firedNonce !== nonce
}
```

- [ ] **Step 4: Run tests to verify they pass.** Run: `cd ui && npx vitest run src/console/3d/furnitureActions.test.ts`
  Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add ui/src/console/3d/dollhouseTypes.ts ui/src/console/3d/furnitureActions.ts ui/src/console/3d/furnitureActions.test.ts
git commit -m "feat(dollhouse): furniture action registry + pure effect planner"
```

### Task 2.3: dashboardApi — extend `ServiceStatus` + add `spotifyControl`

**Files:** Modify `ui/src/console/services/dashboardApi.ts`

- [ ] **Step 1:** Add the optional now-playing fields to `ServiceStatus`:

```ts
export interface ServiceStatus {
  id: string
  name: string
  enabled: boolean
  connected: boolean
  detail: string
  count?: number
  active?: boolean
  // Spotify now-playing extras (present only on the spotify entry):
  title?: string
  artist?: string
  image_url?: string | null
  is_playing?: boolean
}
```

- [ ] **Step 2:** Add `spotifyControl` (reuses the existing `BASE` constant in this file — relative on port 38130, else `http://127.0.0.1:38130`):

```ts
export interface SpotifyControlResult {
  ok: boolean
  is_playing?: boolean
  reason?: string
}

export async function spotifyControl(op: 'playpause' | 'next' | 'prev'): Promise<SpotifyControlResult> {
  try {
    const r = await fetch(`${BASE}/api/spotify/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op }),
    })
    if (!r.ok) return { ok: false, reason: `http ${r.status}` }
    return (await r.json()) as SpotifyControlResult
  } catch {
    return { ok: false, reason: 'network' }
  }
}
```

- [ ] **Step 3: Typecheck.** Run: `cd ui && npx tsc -b`
  Expected: exit 0, no errors.

### Task 2.4: SceneContext — activate nonce, DND state, panel state, gated notifications

**Files:** Modify `ui/src/console/3d/SceneContext.tsx`

- [ ] **Step 1:** Extend `SceneContextType` (add to the interface):

```ts
  // Embodied furniture actions
  activate: (target: import('./dollhouseTypes').ActiveTarget) => void
  dndActive: boolean
  toggleDnd: () => void
  openPanel: 'nowplaying' | null
  setOpenPanel: (p: 'nowplaying' | null) => void
```

- [ ] **Step 2:** Add defaults in the `createContext` default object:

```ts
  activate: noop,
  dndActive: false, toggleDnd: noop,
  openPanel: null, setOpenPanel: noop,
```

- [ ] **Step 3:** In `SceneProvider`, add state + callbacks (place near the other `useState`s):

```ts
  const [dndActive, setDndActive] = useState(false)
  const [openPanel, setOpenPanel] = useState<'nowplaying' | null>(null)
  const nonceRef = useRef(0)
  const dndRef = useRef(false)

  const activate = useCallback((t: ActiveTarget) => {
    nonceRef.current += 1
    setActiveTarget({ ...t, nonce: nonceRef.current })
  }, [])

  const toggleDnd = useCallback(() => {
    setDndActive((prev) => {
      const next = !prev
      dndRef.current = next
      return next
    })
  }, [])
```

(`ActiveTarget` is **already imported** at the top of `SceneContext.tsx` — do not re-add it.)

- [ ] **Step 4:** Gate `pushNotification` with `dndRef` (suppress orbs in Focus). Change the existing `pushNotification`:

```ts
  const pushNotification = useCallback((from: [number, number, number], color = '#22d3ee') => {
    if (dndRef.current) return // Focus/DND: stay quiet
    const id = notifId.current++
    setNotifications((prev) => [...prev.slice(-6), { id, from, color }])
  }, [])
```

- [ ] **Step 5:** Add the new values to the `useMemo` value object AND its dependency array:

```ts
      activate, dndActive, toggleDnd, openPanel, setOpenPanel,
```
deps: add `activate, dndActive, toggleDnd, openPanel`.

- [ ] **Step 6: Typecheck.** Run: `cd ui && npx tsc -b`
  Expected: exit 0.

- [ ] **Step 7: Commit.**

```bash
git add ui/src/console/services/dashboardApi.ts ui/src/console/3d/SceneContext.tsx
git commit -m "feat(dollhouse): scene context DND + panel state, nonce activate, spotifyControl api"
```

---

## Chunk 3: Wiring — arrival fire, dispatcher, panel + badge, build gate

**Files:**
- Create: `ui/src/console/services/useFurnitureActions.ts` (dispatcher hook)
- Create: `ui/src/console/dashboard/NowPlayingPanel.tsx`
- Create: `ui/src/console/dashboard/FocusOverlay.tsx` (FOCUS badge + cool tint)
- Modify: `ui/src/console/3d/OperatorCharacter.tsx` (arrival detection → `onArrive`)
- Modify: `ui/src/console/3d/DollhouseScene.tsx` (build `ix` with `arrive` + `activate`; pass `onArrive`)
- Modify: `ui/src/console/sections/DashboardPage.tsx` (render panel + focus overlay)

### Task 3.1: Dispatcher hook

**Files:** Create `ui/src/console/services/useFurnitureActions.ts`

- [ ] **Step 1: Implement.**

```ts
import { useCallback } from 'react'
import { useSceneContext } from '@/console/3d/SceneContext'
import { resolveAction, planFurnitureEffects } from '@/console/3d/furnitureActions'
import { spotifyControl } from '@/console/services/dashboardApi'

// Returns the `arrive(id)` handler: when the Operator reaches a furniture
// object, look up its action and execute the planned effects. Side-effecting
// shell around the pure planFurnitureEffects().
export function useFurnitureActions(): (id: string) => void {
  const { services, toggleService, dndActive, toggleDnd, setOpenPanel } = useSceneContext()

  return useCallback(
    (id: string) => {
      const action = resolveAction(id)
      if (!action) return
      const effects = planFurnitureEffects(action, { spotifyPlaying: services.spotify, dndActive })
      for (const e of effects) {
        if (e.type === 'openPanel') {
          setOpenPanel(e.panel)
        } else if (e.type === 'toggleDnd') {
          toggleDnd()
        } else if (e.type === 'pauseMusic') {
          toggleService('spotify') // optimistic: vinyl stops spinning now
          void spotifyControl('playpause')
        } else if (e.type === 'spotify') {
          if (e.optimisticToggle) toggleService('spotify')
          void spotifyControl(e.op).then((r) => {
            if (!r.ok && e.optimisticToggle) toggleService('spotify') // revert on failure
          })
        }
      }
    },
    [services.spotify, dndActive, toggleService, toggleDnd, setOpenPanel],
  )
}
```

### Task 3.2: Operator arrival detection

**Files:** Modify `ui/src/console/3d/OperatorCharacter.tsx`

- [ ] **Step 1:** Add `onArrive` to `OperatorProps`:

```ts
export interface OperatorProps {
  activeTarget: ActiveTarget | null
  mood: SystemMood
  hovered: HoveredObject | null
  operatorPos: React.RefObject<THREE.Vector3 | null>
  onArrive?: (id: string) => void
}
```

- [ ] **Step 2:** Destructure it + add refs. Change the signature and add two refs near `lastDest`:

```ts
export default function OperatorCharacter({ activeTarget, mood, hovered, operatorPos, onArrive }: OperatorProps) {
```
```ts
  const firedNonce = useRef<number | null>(null)
  const onArriveRef = useRef(onArrive)
  onArriveRef.current = onArrive
```
Also add the import at top: `import { shouldFireArrival } from './furnitureActions'`.

- [ ] **Step 3:** Fire on arrival. Inside `useFrame`, replace the arrival computation block:

```ts
      const arrivedFinal = pathIdx.current >= lastIdx && dist < 0.2
      if (!arrivedFinal) {
```
with a version that fires the callback once per activation:

```ts
      const arrivedFinal = pathIdx.current >= lastIdx && dist < 0.2
      if (arrivedFinal && activeTarget) {
        const nonce = activeTarget.nonce ?? 0
        if (shouldFireArrival(firedNonce.current, true, nonce)) {
          firedNonce.current = nonce
          onArriveRef.current?.(activeTarget.id)
        }
      }
      if (!arrivedFinal) {
```

(The rest of the block — the `isWalking`/`step` movement inside `if (!arrivedFinal) { ... }` — stays exactly as-is.)

- [ ] **Step 4: Typecheck.** Run: `cd ui && npx tsc -b`  Expected: exit 0.

### Task 3.3: Now-Playing panel

**Files:** Create `ui/src/console/dashboard/NowPlayingPanel.tsx`

- [ ] **Step 1: Implement** (glass card matching `SystemStatusPanel` styling; reads live spotify status from the dashboard poll):

```tsx
import { useSceneContext } from '@/console/3d/SceneContext'
import { useDashboardDataCtx } from '@/console/services/DashboardDataContext'
import { spotifyControl } from '@/console/services/dashboardApi'
import { SkipBack, SkipForward, Play, Pause, X } from 'lucide-react'

export default function NowPlayingPanel() {
  const { openPanel, setOpenPanel } = useSceneContext()
  const { services } = useDashboardDataCtx()
  if (openPanel !== 'nowplaying') return null

  const sp = services.find((s) => s.id === 'spotify')
  const connected = sp?.connected ?? false
  const playing = sp?.is_playing ?? sp?.active ?? false

  return (
    <div
      className="absolute left-1/2 bottom-6 z-50 -translate-x-1/2"
      style={{
        width: 360,
        background: 'rgba(17, 24, 39, 0.95)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(34, 211, 238, 0.15)',
        borderRadius: 12,
        padding: 16,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#94a3b8', letterSpacing: '0.06em' }}>
          Now Playing
        </h3>
        <button title="Close" onClick={() => setOpenPanel(null)} style={{ color: '#94a3b8' }}>
          <X size={16} />
        </button>
      </div>

      {!connected ? (
        <div className="text-xs" style={{ color: '#475569' }}>Spotify not connected</div>
      ) : (
        <div className="flex items-center gap-3">
          <div className="w-14 h-14 rounded-md overflow-hidden shrink-0" style={{ background: '#0a0e17' }}>
            {sp?.image_url && <img src={sp.image_url} alt="" className="w-full h-full object-cover" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate" style={{ color: '#f8fafc' }}>{sp?.title || '—'}</div>
            <div className="text-xs truncate" style={{ color: '#94a3b8' }}>{sp?.artist || ''}</div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-center gap-6 mt-4" style={{ color: '#22d3ee' }}>
        <button title="Previous" onClick={() => void spotifyControl('prev')}><SkipBack size={20} /></button>
        <button title={playing ? 'Pause' : 'Play'} onClick={() => void spotifyControl('playpause')}>
          {playing ? <Pause size={24} /> : <Play size={24} />}
        </button>
        <button title="Next" onClick={() => void spotifyControl('next')}><SkipForward size={20} /></button>
      </div>
    </div>
  )
}
```

(`lucide-react` is already a dependency — `SystemStatusPanel` imports from it.)

### Task 3.4: Focus overlay (badge + cool tint)

**Files:** Create `ui/src/console/dashboard/FocusOverlay.tsx`

- [ ] **Step 1: Implement** (the DND "ambience": a non-interactive cool tint + a FOCUS badge; rendered only while `dndActive`):

```tsx
import { useSceneContext } from '@/console/3d/SceneContext'

export default function FocusOverlay() {
  const { dndActive } = useSceneContext()
  if (!dndActive) return null
  return (
    <>
      {/* Cool tint wash — non-interactive so clicks pass through to the scene. */}
      <div
        className="absolute inset-0 z-30 pointer-events-none"
        style={{ background: 'radial-gradient(ellipse at center, rgba(34,211,238,0.04), rgba(10,14,23,0.32))' }}
      />
      <div
        className="absolute top-6 left-1/2 z-50 -translate-x-1/2 flex items-center gap-2"
        style={{
          padding: '6px 14px',
          background: 'rgba(10,14,23,0.8)',
          border: '1px solid rgba(34,211,238,0.35)',
          borderRadius: 999,
          color: '#22d3ee',
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 11,
          letterSpacing: '0.18em',
          boxShadow: '0 0 18px rgba(34,211,238,0.25)',
        }}
      >
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: '#22d3ee' }} />
        FOCUS
      </div>
    </>
  )
}
```

### Task 3.5: Wire `ix` + Operator in DollhouseScene

**Files:** Modify `ui/src/console/3d/DollhouseScene.tsx`

- [ ] **Step 1:** Import the dispatcher hook (top of file):

```ts
import { useFurnitureActions } from '@/console/services/useFurnitureActions'
```

- [ ] **Step 2:** Destructure `activate` from the context (add to the existing `useSceneContext()` destructure):

```ts
    activeTarget, setActiveTarget, activate,
```

- [ ] **Step 3:** Build the dispatcher and extend `ix`:

```ts
  const arrive = useFurnitureActions()

  const ix: Interaction = useMemo(
    () => ({
      activate,
      hover: setHovered,
      notify: pushNotification,
      activeId: activeTarget?.id ?? null,
      arrive,
    }),
    [activate, setHovered, pushNotification, activeTarget, arrive],
  )
```

- [ ] **Step 4:** Pass `onArrive` to the Operator:

```tsx
          <OperatorCharacter activeTarget={activeTarget} mood={mood} hovered={hovered} operatorPos={operatorPos} onArrive={arrive} />
```

(`onPointerMissed={() => setActiveTarget(null)}` stays — it clears the target on empty clicks.)

### Task 3.6: Render panel + overlay in DashboardPage

**Files:** Modify `ui/src/console/sections/DashboardPage.tsx`

- [ ] **Step 1:** Import + render (inside the providers, next to `SystemStatusPanel`):

```tsx
import NowPlayingPanel from '@/console/dashboard/NowPlayingPanel'
import FocusOverlay from '@/console/dashboard/FocusOverlay'
```
```tsx
          <ZoomControls />
          <StatePanel />
          <SystemStatusPanel />
          <NowPlayingPanel />
          <FocusOverlay />
```

### Task 3.7: Build gate + commit

- [ ] **Step 1: Full build.** Run: `cd ui && npm run build`
  Expected: exit 0 (tsc strict + vite build succeed).

- [ ] **Step 2: Run the unit tests.** Run: `cd ui && npx vitest run src/console/3d/furnitureActions.test.ts`
  Expected: all pass.

- [ ] **Step 3: Commit.**

```bash
git add ui/src/console/services/useFurnitureActions.ts ui/src/console/dashboard/NowPlayingPanel.tsx ui/src/console/dashboard/FocusOverlay.tsx ui/src/console/3d/OperatorCharacter.tsx ui/src/console/3d/DollhouseScene.tsx ui/src/console/sections/DashboardPage.tsx
git commit -m "feat(dollhouse): embodied furniture actions — Living slice wiring"
```

---

## Final verification (live — needs the user)

After all chunks: restart Jarvis (the daemon must reload the new `api_server.py`), open the Dashboard, then confirm in the running app (canvas clicks are not automatable):

- [ ] Click the **vinyl** → robot walks → on arrival Spotify actually toggles + the vinyl starts/stops spinning. (Requires Spotify Premium + an active device; otherwise a graceful "no active device"/"re-authorise" reason and the optimistic spin reverts.)
- [ ] Click the **headphones** → robot walks → music pauses, a "FOCUS" badge + cool tint appear, notification orbs go silent; click again → tint/badge clear.
- [ ] Click the **hologram** or **screen** → robot walks → Now-Playing card opens with working ◁ ❚❚▶ ▷ buttons and live track info.
- [ ] Click the **sofa** or any other-room object → behaves exactly as before (embodied walk only, no action).
- [ ] No new console errors beyond the known-benign three.js ones.

## Notes / deviations from spec
- `spotifyControl` lives in `dashboardApi.ts` (not a separate `services/spotifyControl.ts`) to reuse the existing `BASE` URL constant — avoids a duplicated/hardcoded host. Functionally identical to the spec.
- DND "ambience" is implemented as a lightweight CSS cool-tint overlay + FOCUS badge (`FocusOverlay.tsx`) rather than recolouring 3D materials — keeps the slice low-risk and the 3D furniture untouched, while still reading as a distinct mode. The music-pause + orb-suppression are the functional DND effects.
- `dndActive`/`toggleDnd` are intentionally **separate** from the pre-existing `focusMode`/`toggleFocusMode` (camera room-lock), which is left untouched.
- **Toast on Spotify failure deferred:** the spec mentions a subtle failure toast; the dispatcher instead **reverts the optimistic flip silently** (the key correctness behaviour). A toast is a deliberate follow-up to avoid depending on a `<Toaster>` being mounted in this slice — add it once the app has a confirmed toast host.
