# Window Manager Tools Spec

## Purpose

Deterministic, millisecond-fast control of real OS windows by voice:
"put Chrome on the right screen", "split Spotify and the browser",
"what's open?". Direct Windows-API calls (pywin32) — never vision, never
synthetic mouse input — so arranging windows is reliable and instant.

## Tools

### `listOpenWindows` (no arguments)
Lists user-relevant top-level windows: app name, title, which physical
screen (left/right by virtual-desktop x-order), minimised state. Shell
surfaces (TextInputHost, search, settings hosts) are filtered out.
Answers "what do I have open?" without burning a vision call.

### `manageWindow`
| arg | values | notes |
|---|---|---|
| `action` | focus, move, maximize, minimize, close, split | required |
| `window` | free text | the app/title the user named, any language; when OMITTED, falls back to `second_window`, then to the LAST window this tool managed (session-lifetime) — pronoun follow-ups («βάλε ΤΟ full screen») name no app and must not fail over a field the conversation just established. Validation errors name ONLY the actually-missing fields. |
| `monitor` | left, right, primary, current, 1, 2 | default: window's current screen |
| `position` | left-half, right-half, top-half, bottom-half, full | default full |
| `second_window` | free text | split only: takes the right half |

## Principles

- **Tools return raw data**; the LLM loop phrases the reply (CLAUDE.md).
- **Pure logic is testable without Windows**: `score_window_match` /
  `pick_window` (process-name beats title; all-words title match as
  fallback), `compute_target_rect` (snap geometry on the monitor WORK
  area, taskbar excluded), `pick_monitor` ('left'/'right' = virtual-x
  order, so two side-by-side screens map naturally).
- **No hardcoded language patterns**: matching is substring/word-based on
  window titles + process names; the router LLM handles the user's
  language and fills `window` with the app name.
- `close` posts WM_CLOSE (graceful — apps may prompt to save); never
  TerminateProcess.
- Focus uses the ALT-tap workaround for the SetForegroundWindow
  background-process restriction.
- Unknown window → success=True with the list of open apps (honest reply
  material, not an error), so the model can ask the user to clarify.
- All failures are caught; never raises into the engine.

## Future (not this slice)

Scenes/routines ("gaming time") composing manageWindow + open_app +
SignalRGB; window-to-monitor memory per app.
