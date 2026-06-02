# Unified Console - Phase 0 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Mount the redesigned console at `/panel` inside the existing `ui/` app (as a self-contained `console/` module), keep the orb HUD at `/`, make the build pass, wire the shell StatusBar to real daemon state/health/version, and add `GET /api/version`. Pages still show their own mock/demo data; per-page wiring is Phases 1-5.

**Architecture:** Port the design app (`C:\Users\aggel\Desktop\jarvis_frontend`) into `ui/src/console/` with its own `components/ui`, rewriting internal `@/` imports to `@/console/`. `ui/src/App.tsx` routes `/` -> existing `Home` (orb), `/panel` -> new `ConsoleRoot`. Merge Tailwind tokens/keyframes/fonts and add the 3D/animation deps. A small `console/services/` seam wraps the existing `ui/src/lib/api.ts` and falls back to demo data when the daemon is unreachable.

**Tech Stack:** React 19, react-router 7, Vite 7, TS (strict, verbatimModuleSyntax), Tailwind 3.4, three/@react-three/fiber/drei/postprocessing, framer-motion, gsap, FastAPI (backend).

---

## File structure (Phase 0)

- `ui/src/console/` - NEW home of the redesigned console
  - `ConsoleRoot.tsx` - the shell (was design `App.tsx`): TitleBar + Sidebar + StatusBar + lazy pages
  - `sections/`, `zones/`, `3d/`, `dashboard/`, `context/`, `hooks/`, `data/`, `types/`, `lib/`, `components/` (incl. `components/ui/`) - ported verbatim, imports rewritten to `@/console/...`
  - `services/` - NEW seam (REST + WS + demo fallback)
- `ui/src/App.tsx` - MODIFY: add `/panel` -> `ConsoleRoot`
- `ui/package.json` - MODIFY: add deps (3D, framer-motion, vitest)
- `ui/tailwind.config.js` - MODIFY: merge tokens/keyframes/fonts/boxShadow
- `ui/src/index.css` - MODIFY: append fonts + keyframes/globals from design `index.css`
- `ui/public/` - ADD design `public/` assets
- `ui/console.spec.md` - NEW spec for the console module
- `src/jarvis/api_server.py` - MODIFY: add `GET /api/version`
- `tests/test_api_version.py` - NEW pytest

---

## Task 1: Backend `GET /api/version` (TDD)

**Files:** Modify `src/jarvis/api_server.py` (near `/api/health`, ~line 156). Test: `tests/test_api_version.py`.

- [ ] **Step 1 - Failing test**

```python
# tests/test_api_version.py
from fastapi.testclient import TestClient
from jarvis import api_server


def test_version_endpoint_returns_version_string():
    client = TestClient(api_server.app)
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("version"), str)
    assert body["version"]  # non-empty
```

- [ ] **Step 2 - Run, expect FAIL** (`pytest tests/test_api_version.py -v`) -> 404.

- [ ] **Step 3 - Implement.** Add after the `/api/health` handler:

```python
@app.get("/api/version")
def get_version() -> dict:
    """App/daemon version for the console StatusBar. Best-effort, local-only."""
    version = "unknown"
    try:
        from importlib.metadata import version as _v
        version = _v("jarvis")
    except Exception:
        try:
            from jarvis import __version__ as version  # type: ignore
        except Exception:
            version = "dev"
    return {"version": version}
```

(If `jarvis` exposes a version constant already, prefer it; adjust the import to the real source. Verify before finalising.)

- [ ] **Step 4 - Run, expect PASS.**

- [ ] **Step 5 - Commit:** `feat(api): add /api/version for console status bar`

---

## Task 2: Add frontend dependencies

**Files:** Modify `ui/package.json`.

- [ ] **Step 1** - Add to `dependencies` (versions matched to design app):
  `@react-three/fiber@^9.6.1`, `@react-three/drei@^10.7.7`, `@react-three/postprocessing@^3.0.4`, `postprocessing@^6.39.1`, `framer-motion@^12.40.0`, `@gsap/react@^2.1.2`, `lenis@^1.3.23`.
  Add to `devDependencies`: `vitest@^4.1.8`, `jsdom@^25` (for component tests), `@testing-library/react`, `@testing-library/jest-dom`.
  Add script: `"test": "vitest run"`.
- [ ] **Step 2** - `cd ui && npm install`. Expect success.
- [ ] **Step 3 - Commit:** `chore(ui): add 3D + animation + vitest deps for console`

---

## Task 3: Port the design app into `ui/src/console/`

**Files:** copy from `C:\Users\aggel\Desktop\jarvis_frontend\src\*` into `ui\src\console\`.

- [ ] **Step 1** - Copy these design `src/` dirs/files into `ui/src/console/` (NOT `main.tsx`, NOT the design `App.tsx` yet -> becomes `ConsoleRoot.tsx`):
  `3d/`, `dashboard/`, `sections/`, `zones/`, `context/`, `hooks/`, `data/`, `types/`, `lib/`, `components/` (includes `components/ui/`, `components/shell/`, `Card.tsx`, `Badge.tsx`, `ToggleSwitch.tsx`).
- [ ] **Step 2** - Copy design `src/App.tsx` -> `ui/src/console/ConsoleRoot.tsx`; rename the exported component to `ConsoleRoot`.
- [ ] **Step 3** - Rewrite internal imports in every file under `ui/src/console/`: replace `@/` with `@/console/` (covers `from '@/...'`, `from "@/..."`, and `import('@/...')`). Leave non-`@/` imports untouched.
- [ ] **Step 4** - Copy design `public/*` (character + house images, mp4s, holograms, og-image) into `ui/public/`.
- [ ] **Step 5 - Commit:** `feat(ui): port redesigned console into ui/src/console`

---

## Task 4: Merge Tailwind + CSS + tsconfig

**Files:** `ui/tailwind.config.js`, `ui/src/index.css`, `ui/tsconfig.app.json`.

- [ ] **Step 1** - Merge the design `tailwind.config.js` `theme.extend` additions into `ui/tailwind.config.js` (union): the hex colour tokens (`bg-void`, `cyan-primary`, `amber-warm`, `text-primary/secondary/disabled`, `success/warning/error/info`, `bg-floor*`, `bg-panel*`, `wall-*`), `fontFamily` (clash/inter/mono), the extra `boxShadow` (cyan-glow*), and all extra `keyframes`/`animation` (`pulse-dot`, `float`, `glow-pulse`, `ring-pulse`, `skeleton-shimmer`, `cyan-flash`, `slide-in-right`, `fade-in-up`, `data-flow`, `particle-drift`). Keep existing `sidebar` tokens. Keep `content` globs (already `./src/**/*`).
- [ ] **Step 2** - Append to `ui/src/index.css` any `@font-face`/font imports + global keyframe/util classes from the design `src/index.css` that are not Tailwind-generated (fonts: Inter, JetBrains Mono, optional Clash Display; plus any raw CSS the components rely on). Do not duplicate the shadcn `:root` token block already present.
- [ ] **Step 3** - tsconfig: `ui/tsconfig.app.json` already has `@/* -> ./src/*` and strict + verbatimModuleSyntax. No change needed unless the build complains; if vitest needs a separate include, handle in Task 7.
- [ ] **Step 4** - Commit: `feat(ui): merge console design tokens, fonts, keyframes`

---

## Task 5: Wire routing - `/panel` -> ConsoleRoot, keep orb at `/`

**Files:** `ui/src/App.tsx`.

- [ ] **Step 1** - Replace the `/panel` route's element with the new console:

```tsx
import { Routes, Route } from 'react-router'
import { lazy, Suspense } from 'react'
import Home from './pages/Home'
const ConsoleRoot = lazy(() => import('./console/ConsoleRoot'))

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route
        path="/panel"
        element={
          <Suspense fallback={<div className="h-screen w-screen bg-[#0a0e17]" />}>
            <ConsoleRoot />
          </Suspense>
        }
      />
    </Routes>
  )
}
```

- [ ] **Step 2** - Delete the now-unused old panel files only AFTER the new console builds and renders (defer deletion to Task 8). For now leave `components/panel/*` in place (unreferenced).
- [ ] **Step 3 - Commit:** `feat(ui): mount redesigned console at /panel`

---

## Task 6: Service seam + live StatusBar

**Files:** `ui/src/console/services/seam.ts` (NEW), `ui/src/console/components/shell/StatusBar.tsx` (MODIFY), `ui/src/console/services/useConnection.ts` (NEW).

- [ ] **Step 1** - `services/seam.ts`: re-export the shared client and add a connection/version helper.

```ts
import { api, openStateStream } from '@/lib/api'
import type { VoiceStatePayload } from '@/lib/api'
export { api, openStateStream }
export type { VoiceStatePayload }

export async function fetchVersion(): Promise<string> {
  try {
    const r = await fetch(
      (window.location.port === '38130' ? '' : 'http://127.0.0.1:38130') + '/api/version',
    )
    if (!r.ok) return 'dev'
    return (await r.json()).version ?? 'dev'
  } catch {
    return 'dev'
  }
}
```

- [ ] **Step 2** - `services/useConnection.ts`: a hook returning `{ state, connected, version }` from `openStateStream` + `api.health()` + `fetchVersion()`, with `connected=false` until the first state/health arrives, reconnect handled by `openStateStream`.

```ts
import { useEffect, useState } from 'react'
import { openStateStream, fetchVersion, api } from './seam'
import type { VoiceStatePayload } from './seam'

export function useConnection() {
  const [state, setState] = useState<VoiceStatePayload | null>(null)
  const [connected, setConnected] = useState(false)
  const [version, setVersion] = useState('')
  useEffect(() => {
    let alive = true
    fetchVersion().then((v) => alive && setVersion(v))
    api.health().then(() => alive && setConnected(true)).catch(() => {})
    const stop = openStateStream((s) => {
      if (!alive) return
      setState(s)
      setConnected(true)
    })
    return () => { alive = false; stop() }
  }, [])
  return { state, connected, version }
}
```

- [ ] **Step 3** - StatusBar: replace the hardcoded `Idle / Connected / v2.0.0-alpha / 22C / date` with live values: status label from `state.state` (fallback "Offline"), connected dot from `connected`, `version`, today's date from the browser. Temperature stays a placeholder until Phase 4 (`--`).
- [ ] **Step 4 - Commit:** `feat(console): wire StatusBar to live daemon state/health/version`

---

## Task 7: Frontend test setup + a seam test

**Files:** `ui/vitest.config.ts` (NEW), `ui/src/console/services/seam.test.ts` (NEW).

- [ ] **Step 1** - Add `ui/vitest.config.ts` (jsdom env, alias `@`->src). Ensure test files are excluded from `tsc -b` app build (add to a `tsconfig` exclude or rely on vitest-only).
- [ ] **Step 2** - Write a small unit test for a pure mapping helper that Phase 1 will need (e.g. a `mapLogLevel(backendLevel)` placed in `console/lib/logMap.ts`), proving the harness runs. Keep it minimal but real.
- [ ] **Step 3** - `cd ui && npm run test`. Expect PASS.
- [ ] **Step 4 - Commit:** `test(console): add vitest harness + first seam test`

---

## Task 8: Build gate, cleanup, verify

- [ ] **Step 1** - `cd ui && npm run build` (`tsc -b && vite build`). Fix any type/import errors (most likely: missing `import type`, an unrewritten `@/` import, a missing public asset). Expect exit 0.
- [ ] **Step 2** - Remove the old panel implementation now replaced: `ui/src/components/panel/` (ControlPanel/TopBar/Sidebar/StatusBar/tabs/*) and `ui/src/types/panel.ts`, ONLY if nothing else imports them (grep first). Re-run build.
- [ ] **Step 3** - Runtime verify: build, ensure daemon serves `ui/dist`; load `http://127.0.0.1:38130/panel` and `http://127.0.0.1:38130/` (orb still works). Playwright screenshot each of the 5 console pages + the orb; assert 0 console errors (3D canvas clicks verified live/manually).
- [ ] **Step 4** - Write `ui/console.spec.md` documenting the module (routing, structure, service seam, fallback, the `/panel` contract, "orb at / preserved").
- [ ] **Step 5 - Commit:** `chore(ui): drop legacy panel; Phase 0 console foundation complete`

---

## Self-review notes
- Spec coverage: integration into `ui/` at `/panel` (T3/T5), keep orb (T5/T8), service seam (T6), StatusBar live (T6), `/api/version` (T1), build+verify (T8) - all Phase 0 spec items covered.
- Pages remain mock until Phases 1-5 - intended.
- Risk: `@/` import rewrite must catch dynamic `import('@/...')` in `ConsoleRoot.tsx` (lazy pages). Verified as part of T3 Step 3.
- Risk: design `index.css` may carry a duplicate shadcn `:root`; only append non-duplicated rules (T4 Step 2).
- Risk: public asset paths - verify 3D textures/videos load at runtime (T8 Step 3).
