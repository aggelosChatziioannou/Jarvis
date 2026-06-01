# Jarvis Web UI (`ui/`)

The **React + Vite + TypeScript** front-end for Jarvis. This is the canonical
user-facing UI; the PySide desktop shell (`src/desktop_app/`) embeds it.

## How it fits together

```
vite build  ->  ui/dist  ->  served by the daemon's FastAPI server (127.0.0.1:38130)
                                 │
        ┌────────────────────────┴───────────────────────────┐
        ▼                                                      ▼
  GET /        = Home (BootScreen + JarvisCard)         GET /panel = Control Panel
  -> embedded by desktop_app's WebFloatingHUD            -> embedded by JarvisConsoleWindow
     (the always-on-top orb)                                (Live Logs, Audio I/O, Wake Word,
                                                             Voice/TTS, Language Model, Services/MCP,
                                                             API Keys, Easter Eggs)
```

- `ui/dist` is **gitignored** (build output). The daemon serves whatever local
  `dist/` exists via `src/jarvis/api_server.py` (`_mount_static_if_present`,
  SPA-aware catch-all). Run `npm run build` after changing the UI.
- Live voice/log state reaches the UI over the daemon WebSocket and REST
  endpoints in `src/jarvis/api_server.py`. The TS client is `src/lib/api.ts`.
- A **separate** memory/diary/graph explorer is a Flask app
  (`src/desktop_app/memory_viewer.py`, port 5050) in its own window — it is
  **not** part of this React app.

## Develop

```bash
npm install        # first time
npm run dev        # Vite dev server (hot reload); voice/log data needs the daemon running
npm run build      # produce ui/dist that the daemon serves
npm run lint
```

## Layout

```
src/
  main.tsx, App.tsx   app entry + router
  pages/              route-level views (Home, Panel / Control Console)
  components/         orb (OrbCore / JarvisCard), panel/ (Sidebar, StatusBar, sections), StatusLabel
  hooks/              websocket + state hooks
  lib/api.ts          typed daemon client (REST + WS); VoiceStatePayload state vocab
  types/              shared TS types
```

> Voice-state vocab: the daemon publishes `idle | listening | thinking | speaking`.
> It collapses its internal `synthesizing` phase into `thinking` before publishing,
> so a `synthesizing` state is never actually received (see `lib/api.ts`).

For the full system (models, STT backends, ports, launch flow) see **`../AGENTS.md`**.
