"""Window management tools: focus / move / split / list real OS windows.

Deterministic Windows-API control (no vision, no mouse emulation) so voice
commands like "put Chrome on the left screen" or "split Spotify and the
browser" land in milliseconds. Tools return raw data; the LLM loop phrases
the reply (see CLAUDE.md tool conventions).

Pure decision logic (window matching, target-rectangle maths) is module-level
and unit-testable without Windows; the thin win32 layer stays inside the
tools' ``run`` methods.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...debug import debug_log
from ..base import Tool, ToolContext
from ..types import ToolExecutionResult

# ── Pure helpers ───────────────────────────────────────────────────────────

# System/shell windows that are technically visible but never what the user
# means by "a window". Matched against the process basename, lowercase.
_SHELL_PROCESSES = frozenset({
    "textinputhost.exe", "shellexperiencehost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "applicationframehost.exe",
    "systemsettings.exe", "lockapp.exe",
})


# Transient launcher surfaces (splash/installer/updater windows) that appear
# FIRST when an app starts and then hand off to the real window. Matching
# them moves a window that is about to vanish. Technical window-title terms,
# not user-language patterns.
_TRANSIENT_TITLE_WORDS = ("installer", "install", "setup", "updater", "updating")


def is_transient_window(title: str) -> bool:
    t = (title or "").lower()
    return any(w in t for w in _TRANSIENT_TITLE_WORDS)


# The last window query manageWindow successfully resolved (process name).
# Pronoun follow-ups ("put IT fullscreen on the left") name no app — the
# router emits action/monitor/position without `window`, and failing the
# call over a field the conversation just established broke the natural
# two-step flow. Session-lifetime state, deliberately not persisted.
_LAST_MANAGED_QUERY: Optional[str] = None


def effective_window_query(args: Dict[str, Any], last_managed: Optional[str]) -> str:
    """The window a manageWindow call targets: explicit `window`, else
    `second_window` (half-split emissions), else the last managed window."""
    q = str((args or {}).get("window", "") or "").strip()
    if not q:
        q = str((args or {}).get("second_window", "") or "").strip()
    if not q and last_managed:
        q = str(last_managed).strip()
    return q


def score_window_match(query: str, title: str, process: str) -> int:
    """Rank how well a window answers the user's description.

    Returns 0 for no match; higher is better. Process-name hits beat title
    hits ("chrome" should match chrome.exe even when no tab says "chrome").
    Splash/installer windows are heavily penalised so the real app window
    wins whenever both exist.
    """
    q = (query or "").strip().lower()
    if not q:
        return 0
    t = (title or "").lower()
    p = (process or "").lower().removesuffix(".exe")
    score = 0
    if q == p:
        score = 100
    elif p and (q in p or p in q):
        score = 80
    elif q == t:
        score = 70
    elif q in t:
        score = 60
    else:
        # All query words present somewhere in the title (any order).
        words = [w for w in q.split() if len(w) >= 2]
        if words and all(w in t or w in p for w in words):
            score = 40
    if score and is_transient_window(title):
        score = max(1, score - 60)
    return score


def pick_window(windows: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    """Best-matching window for ``query``, or None. Ties prefer list order
    (which the caller supplies in z-order, most recently used first)."""
    best, best_score = None, 0
    for w in windows:
        s = score_window_match(query, w.get("title", ""), w.get("process", ""))
        if s > best_score:
            best, best_score = w, s
    return best


def compute_target_rect(work: Dict[str, int], position: str) -> Dict[str, int]:
    """Target window rectangle for a snap position inside a monitor work area.

    ``work``: {x, y, width, height} of the monitor's work area.
    ``position``: left-half | right-half | top-half | bottom-half | full.
    """
    x, y, w, h = work["x"], work["y"], work["width"], work["height"]
    pos = (position or "full").lower()
    if pos == "left-half":
        return {"x": x, "y": y, "width": w // 2, "height": h}
    if pos == "right-half":
        return {"x": x + w // 2, "y": y, "width": w - w // 2, "height": h}
    if pos == "top-half":
        return {"x": x, "y": y, "width": w, "height": h // 2}
    if pos == "bottom-half":
        return {"x": x, "y": y + h // 2, "width": w, "height": h - h // 2}
    return {"x": x, "y": y, "width": w, "height": h}


def pick_monitor(monitors: List[Dict[str, Any]], which: str,
                 current_index: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Resolve 'left'/'right'/'primary'/'current'/'1'/'2' to a monitor.

    Monitors are sorted by virtual-desktop x, so with two side-by-side
    screens 'left' is index 0 and 'right' is the last one.
    """
    if not monitors:
        return None
    ordered = sorted(monitors, key=lambda m: m["x"])
    w = (which or "current").strip().lower()
    if w in ("left", "first"):
        return ordered[0]
    if w in ("right", "second", "other" if len(ordered) > 1 else "right"):
        return ordered[-1]
    if w == "primary":
        return next((m for m in ordered if m.get("primary")), ordered[0])
    if w == "current" and current_index is not None:
        return next((m for m in monitors if m.get("index") == current_index), ordered[0])
    if w.isdigit():
        i = int(w) - 1
        if 0 <= i < len(ordered):
            return ordered[i]
    return next((m for m in ordered if m.get("primary")), ordered[0])


# ── Win32 layer (imported lazily so non-Windows test envs stay importable) ──

def _enum_windows() -> List[Dict[str, Any]]:
    """All user-relevant top-level windows, z-order (foreground first)."""
    import win32gui
    import win32process
    try:
        import psutil
    except Exception:
        psutil = None  # type: ignore

    out: List[Dict[str, Any]] = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        # Skip tool windows (palettes, overlays).
        import win32con
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if ex & win32con.WS_EX_TOOLWINDOW:
            return
        process = ""
        try:
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            if psutil is not None:
                process = psutil.Process(pid).name()
        except Exception:
            pass
        if process.lower() in _SHELL_PROCESSES:
            return
        rect = win32gui.GetWindowRect(hwnd)
        out.append({
            "hwnd": hwnd,
            "title": title[:120],
            "process": process,
            "minimized": bool(win32gui.IsIconic(hwnd)),
            "rect": {"x": rect[0], "y": rect[1],
                     "width": rect[2] - rect[0], "height": rect[3] - rect[1]},
        })

    win32gui.EnumWindows(_cb, None)
    return out


def _enum_monitors() -> List[Dict[str, Any]]:
    """Physical monitors with their WORK areas (taskbar excluded)."""
    import win32api

    out: List[Dict[str, Any]] = []
    for i, (hmon, _hdc, _rect) in enumerate(win32api.EnumDisplayMonitors(None, None)):
        info = win32api.GetMonitorInfo(hmon)
        wx, wy, wr, wb = info["Work"]
        out.append({
            "index": i,
            "x": wx, "y": wy, "width": wr - wx, "height": wb - wy,
            "primary": bool(info.get("Flags", 0) & 1),
        })
    return out


def _force_foreground(hwnd: int) -> None:
    """Bring a window to the front, working around the SetForegroundWindow
    restriction for background processes (brief ALT tap releases the lock)."""
    import win32api
    import win32con
    import win32gui

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)


def _apply_rect(hwnd: int, rect: Dict[str, int]) -> None:
    import ctypes
    import win32con
    import win32gui

    # IsZoomed is NOT exposed by win32gui (pywin32) — call user32 directly.
    # Hit only when the window is not minimized, so the bug hid behind the
    # short-circuit until a maximized window was moved.
    zoomed = bool(ctypes.windll.user32.IsZoomed(hwnd))
    if win32gui.IsIconic(hwnd) or zoomed:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetWindowPos(
        hwnd, 0, rect["x"], rect["y"], rect["width"], rect["height"],
        win32con.SWP_NOZORDER | win32con.SWP_SHOWWINDOW,
    )


def _monitor_of(window: Dict[str, Any], monitors: List[Dict[str, Any]]) -> Optional[int]:
    """Index of the monitor whose area contains the window centre."""
    cx = window["rect"]["x"] + window["rect"]["width"] // 2
    cy = window["rect"]["y"] + window["rect"]["height"] // 2
    for m in monitors:
        if m["x"] <= cx < m["x"] + m["width"] and m["y"] <= cy < m["y"] + m["height"]:
            return m["index"]
    return None


# ── Tools ──────────────────────────────────────────────────────────────────


class ListOpenWindowsTool(Tool):
    """What is open right now — titles, apps, which monitor."""

    @property
    def name(self) -> str:
        return "listOpenWindows"

    @property
    def description(self) -> str:
        return (
            "List the windows currently open on the user's computer (app name, "
            "window title, which monitor, minimised or not). Use when the user "
            "asks what is open / running, or before arranging windows."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        try:
            monitors = _enum_monitors()
            windows = _enum_windows()
            lines = []
            for w in windows[:25]:
                mon = _monitor_of(w, monitors)
                ordered = sorted(monitors, key=lambda m: m["x"])
                side = ""
                if mon is not None and len(ordered) > 1:
                    side = " [left screen]" if mon == ordered[0]["index"] else " [right screen]"
                state = " (minimised)" if w["minimized"] else ""
                app = w["process"].removesuffix(".exe") if w["process"] else "?"
                lines.append(f"- {app}: {w['title']}{side}{state}")
            body = "\n".join(lines) if lines else "No windows with a title are open."
            return ToolExecutionResult(success=True, reply_text=f"Open windows:\n{body}")
        except Exception as e:
            debug_log(f"listOpenWindows failed: {e!r}", "tools")
            return ToolExecutionResult(success=False, reply_text=None,
                                       error_message=f"Could not list windows: {type(e).__name__}")


class ManageWindowTool(Tool):
    """Move / focus / snap / split real windows across monitors."""

    @property
    def name(self) -> str:
        return "manageWindow"

    @property
    def description(self) -> str:
        return (
            "Arrange application windows on the user's screens: focus a window, "
            "move it to the left/right monitor, snap it to a half of the screen, "
            "maximise, minimise, close, or split two apps side by side. Use for "
            "requests like 'put Chrome on the right screen', 'Spotify on the left "
            "half', 'split the browser and the editor'. The window argument is "
            "the app or title the user named, in any language."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["focus", "move", "maximize", "minimize", "close", "split"],
                    "description": "What to do with the window(s).",
                },
                "window": {
                    "type": "string",
                    "description": "App or window the user named (e.g. 'chrome', 'spotify').",
                },
                "monitor": {
                    "type": "string",
                    "enum": ["left", "right", "primary", "current", "1", "2"],
                    "description": "Which screen. Default: the window's current screen.",
                },
                "position": {
                    "type": "string",
                    "enum": ["left-half", "right-half", "top-half", "bottom-half", "full"],
                    "description": "Where on that screen. Default: full (whole work area).",
                },
                "second_window": {
                    "type": "string",
                    "description": "For split: the app that takes the right half.",
                },
            },
            "required": ["action", "window"],
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        global _LAST_MANAGED_QUERY
        a = args or {}
        action = str(a.get("action", "")).strip().lower()
        query = str(a.get("window", "")).strip()
        # Half-split emissions sometimes carry only second_window — treat it
        # as the window rather than failing the call.
        if not query and str(a.get("second_window", "")).strip():
            query = str(a.pop("second_window")).strip()
        # Pronoun follow-ups ("put IT fullscreen on the left") name no app:
        # fall back to the last window this tool managed in this session.
        if not query and _LAST_MANAGED_QUERY:
            query = _LAST_MANAGED_QUERY
            print(f"  🪟 No window named — using the last managed window '{query}'", flush=True)
        missing = [name for name, val in (("action", action), ("window", query)) if not val]
        if missing:
            return ToolExecutionResult(success=False, reply_text=None,
                                       error_message=f"missing required field(s): {', '.join(missing)}")
        # Tolerant action normalisation: small models emit creative variants
        # like 'move_to_left_monitor'. Map them onto the real enum and pull
        # an embedded monitor/position out rather than failing the request.
        if action not in ("focus", "move", "maximize", "minimize", "close", "split"):
            compact = action.replace("-", "_")
            for known in ("split", "maximize", "minimize", "close", "focus", "move"):
                if known in compact or (known == "maximize" and "maximise" in compact):
                    action = known
                    break
            else:
                action = "move"  # placement-ish unknowns degrade to a move
            # A bare left/right action means SNAP on the current screen
            # (Windows-Snap intuition), not a jump to the other monitor —
            # unless the model already named a monitor explicitly.
            if not a.get("position"):
                if "left" in compact:
                    a["position"] = "left-half"
                elif "right" in compact:
                    a["position"] = "right-half"
        try:
            import time as _time

            monitors = _enum_monitors()
            windows = _enum_windows()
            target = pick_window(windows, query)
            # The window may belong to an app launched a moment ago (the
            # open_app -> manageWindow sequence): poll before giving up so
            # "open Spotify on the left" works in one breath. A transient
            # splash/installer match keeps polling for the REAL window (it
            # is accepted only if nothing better ever appears).
            for _ in range(8):
                if target is not None and not is_transient_window(target.get("title", "")):
                    break
                _time.sleep(1.2)
                windows = _enum_windows()
                target = pick_window(windows, query) or target
            if target is None:
                open_names = ", ".join(sorted({w["process"].removesuffix(".exe")
                                               for w in windows if w["process"]})[:12])
                return ToolExecutionResult(
                    success=True,
                    reply_text=(f"No open window matches '{query}'. "
                                f"Currently open apps: {open_names or 'none'}. "
                                f"(If the app isn't running, launch it with the open_app tool, "
                                f"then call manageWindow again.)"),
                )
            # Remember the target so a pronoun follow-up ("put it fullscreen")
            # can omit `window` and still mean this app.
            _LAST_MANAGED_QUERY = (
                target.get("process", "").removesuffix(".exe") or query
            )

            import win32con
            import win32gui

            if action == "focus":
                _force_foreground(target["hwnd"])
                return ToolExecutionResult(success=True, reply_text=f"Focused: {target['title']}")

            if action == "minimize":
                win32gui.ShowWindow(target["hwnd"], win32con.SW_MINIMIZE)
                return ToolExecutionResult(success=True, reply_text=f"Minimised: {target['title']}")

            if action == "close":
                win32gui.PostMessage(target["hwnd"], win32con.WM_CLOSE, 0, 0)
                return ToolExecutionResult(success=True,
                                           reply_text=f"Asked {target['title']} to close (it may prompt to save).")

            cur_mon = _monitor_of(target, monitors)
            mon = pick_monitor(monitors, str(a.get("monitor") or "current"), current_index=cur_mon)
            if mon is None:
                return ToolExecutionResult(success=False, reply_text=None,
                                           error_message="No monitor found")

            if action == "maximize":
                _apply_rect(target["hwnd"], compute_target_rect(mon, "full"))
                _force_foreground(target["hwnd"])
                return ToolExecutionResult(success=True,
                                           reply_text=f"Maximised {target['title']} on the "
                                                      f"{'left' if mon == sorted(monitors, key=lambda m: m['x'])[0] else 'right'} screen.")

            if action == "move":
                pos = str(a.get("position") or "full")
                _apply_rect(target["hwnd"], compute_target_rect(mon, pos))
                _force_foreground(target["hwnd"])
                # Freshly-launched apps often recreate their window (or
                # restore remembered geometry) SEVERAL seconds after the
                # splash — Spotify does both — so an early move loses the
                # race. Keep verifying and re-applying on the CURRENT best
                # match; exits on the first check for already-open apps.
                for _ in range(6):
                    _time.sleep(2.0)
                    cur = pick_window(_enum_windows(), query)
                    if cur is None:
                        break
                    if (_monitor_of(cur, monitors) == mon["index"]
                            and not is_transient_window(cur.get("title", ""))):
                        break
                    _apply_rect(cur["hwnd"], compute_target_rect(mon, pos))
                    _force_foreground(cur["hwnd"])
                return ToolExecutionResult(success=True,
                                           reply_text=f"Moved {target['title']} ({pos}).")

            if action == "split":
                second_q = str(a.get("second_window", "")).strip()
                # Models often emit a split as TWO half-position calls
                # (split window=A position=left-half, then split
                # second_window=B position=right-half). Each half IS just a
                # move — honour the intent instead of erroring.
                if not second_q and a.get("position"):
                    action = "move"
                    pos = str(a.get("position"))
                    _apply_rect(target["hwnd"], compute_target_rect(mon, pos))
                    _force_foreground(target["hwnd"])
                    return ToolExecutionResult(success=True,
                                               reply_text=f"Moved {target['title']} ({pos}).")
                second = pick_window(windows, second_q) if second_q else None
                if second is None:
                    return ToolExecutionResult(
                        success=True,
                        reply_text=f"Found '{target['title']}' but no window matches "
                                   f"'{second_q or '(missing second_window)'}' for the split.",
                    )
                _apply_rect(target["hwnd"], compute_target_rect(mon, "left-half"))
                _apply_rect(second["hwnd"], compute_target_rect(mon, "right-half"))
                _force_foreground(second["hwnd"])
                _force_foreground(target["hwnd"])
                return ToolExecutionResult(
                    success=True,
                    reply_text=f"Split: {target['title']} on the left, {second['title']} on the right.",
                )

            return ToolExecutionResult(success=False, reply_text=None,
                                       error_message=f"Unknown action '{action}'")
        except Exception as e:
            debug_log(f"manageWindow failed: {e!r}", "tools")
            return ToolExecutionResult(success=False, reply_text=None,
                                       error_message=f"Window action failed: {type(e).__name__}")
