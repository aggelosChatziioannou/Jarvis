"""FastAPI server bridging the React UI to the Jarvis daemon.

Runs on 127.0.0.1:38130 inside the daemon process. Provides:
  • REST endpoints for config read/write, MCP toggling, memory, etc.
  • WebSocket /ws/logs for live log streaming
  • WebSocket /ws/state for voice-state changes

The control_bus (port 38127) remains the lightweight command channel for
STOP/MUTE/PING — this API layer is *additive*, not a replacement. The
React UI uses this server for everything except the most latency-sensitive
single-shot commands.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import threading
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from . import control_bus
from . import config_safety
from .config import default_config_path, load_config, _save_json, _load_json
from .debug import debug_log
from .utils.redact import scrub_secrets


API_HOST = "127.0.0.1"
API_PORT = 38130

# Cap log buffer to avoid unbounded memory growth in long-running daemons.
LOG_BUFFER_SIZE = 2000


# ---------------------------------------------------------------------------
# Shared in-memory state — populated by daemon code via the bridge functions
# ---------------------------------------------------------------------------

_log_buffer: Deque[Dict[str, Any]] = deque(maxlen=LOG_BUFFER_SIZE)
_log_subscribers: List[asyncio.Queue] = []
_log_subscribers_lock = threading.Lock()

_voice_state: Dict[str, Any] = {
    "state": "idle",       # idle | listening | thinking | synthesizing | speaking
    "isMuted": False,
    "uptime": 0.0,
    "lastWake": None,
    "commandsProcessed": 0,
    "query": "",
}
_state_subscribers: List[asyncio.Queue] = []
_state_subscribers_lock = threading.Lock()

_started_at = time.time()
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def publish_log(level: str, message: str) -> None:
    """Called by daemon code to append a log entry and broadcast it.

    Safe to call from any thread.
    """
    entry = {
        "id": f"{time.time():.6f}",
        "timestamp": time.strftime("%H:%M:%S") + f".{int(time.time() * 100) % 100:02d}",
        "level": level,
        "message": message,
    }
    _log_buffer.append(entry)
    _broadcast_to_subscribers(_log_subscribers, _log_subscribers_lock, entry)


def publish_state(**fields: Any) -> None:
    """Update voice state and broadcast. Pass any subset of state fields."""
    _voice_state.update(fields)
    _broadcast_to_subscribers(_state_subscribers, _state_subscribers_lock, dict(_voice_state))


_devices_changed_seq = 0
_devices_changed_lock = threading.Lock()


def notify_devices_changed() -> int:
    """Signal the UI that the audio device list changed (live, from the watcher).

    Bumps a monotonic counter and broadcasts it as ``devices_changed`` on the
    voice-state socket, so the React Audio tab re-fetches ``/api/audio/devices``
    the moment a device is plugged in or removed. Returns the new sequence
    value. Safe to call from any thread.
    """
    global _devices_changed_seq
    with _devices_changed_lock:
        _devices_changed_seq += 1
        seq = _devices_changed_seq
    publish_state(devices_changed=seq)
    return seq


def _broadcast_to_subscribers(
    subs: List[asyncio.Queue],
    lock: threading.Lock,
    payload: Dict[str, Any],
) -> None:
    """Thread-safe broadcast — schedule put_nowait on the API event loop."""
    if _main_loop is None:
        return
    with lock:
        snapshot = list(subs)
    for q in snapshot:
        try:
            _main_loop.call_soon_threadsafe(q.put_nowait, payload)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Jarvis Control API", version="1.0.0")

# CORS — the React dev server runs on 5173 by default; allow loopback origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:38130",
        "http://127.0.0.1:38130",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _on_startup() -> None:
    global _main_loop
    _main_loop = asyncio.get_running_loop()


# ---------- Health & state ----------

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "uptime": time.time() - _started_at,
        "buffer_size": len(_log_buffer),
    }


@app.get("/api/state")
def get_state() -> Dict[str, Any]:
    return {**_voice_state, "uptime": time.time() - _started_at}


@app.get("/api/version")
def get_version_info() -> Dict[str, Any]:
    """App version + release channel for the console StatusBar.

    Local-only and non-sensitive. Sourced from the canonical core
    ``jarvis.get_version`` so the console matches the desktop app.
    """
    from . import get_version

    version, channel = get_version()
    return {"version": version, "channel": channel}


# ---------- Commands (proxy to control_bus) ----------

class CommandResponse(BaseModel):
    ok: bool
    response: Optional[str] = None


@app.post("/api/command/stop", response_model=CommandResponse)
def cmd_stop() -> CommandResponse:
    resp = control_bus.send_command("STOP")
    return CommandResponse(ok=resp is not None, response=resp)


@app.post("/api/command/mute", response_model=CommandResponse)
def cmd_mute() -> CommandResponse:
    resp = control_bus.send_command("MUTE")
    return CommandResponse(ok=resp is not None, response=resp)


@app.post("/api/command/unmute", response_model=CommandResponse)
def cmd_unmute() -> CommandResponse:
    resp = control_bus.send_command("UNMUTE")
    return CommandResponse(ok=resp is not None, response=resp)


@app.post("/api/command/trigger", response_model=CommandResponse)
def cmd_trigger() -> CommandResponse:
    resp = control_bus.send_command("TRIGGER")
    return CommandResponse(ok=resp is not None, response=resp)


# ---------- Config (read/write the JSON file directly) ----------

# Sentinel shown by GET /api/config in place of a stored secret. The UI renders
# it as "a value is set" without ever seeing the secret. PATCH treats an
# incoming value equal to this sentinel as "leave unchanged", so a round-trip
# of the masked config never wipes stored credentials.
_SECRET_MASK = "••••••"  # ••••••

# Name heuristic (not a hardcoded field list, so new secret keys are covered
# automatically): any top-level key whose name contains one of these is masked,
# plus every value inside an MCP server ``env`` block.
_SECRET_KEY_HINTS = ("api_key", "apikey", "secret", "password", "passwd", "token", "credential")


def _is_secret_key(key: str) -> bool:
    k = str(key).lower()
    return any(hint in k for hint in _SECRET_KEY_HINTS)


def _mask_env(env: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (_SECRET_MASK if v else "") for k, v in env.items()}


def _mask_secrets(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of ``cfg`` with secret values replaced by the mask.

    Masks top-level secret-named keys and every value inside ``mcps[*].env`` /
    ``mcp_servers[*].env`` (where MCP credentials live). Non-secret values pass
    through unchanged.
    """
    import copy
    if not isinstance(cfg, dict):
        return cfg
    masked = copy.deepcopy(cfg)
    for key, value in list(masked.items()):
        if key == "mcps" and isinstance(value, dict):
            for srv in value.values():
                if isinstance(srv, dict) and isinstance(srv.get("env"), dict):
                    srv["env"] = _mask_env(srv["env"])
        elif key == "mcp_servers" and isinstance(value, list):
            for srv in value:
                if isinstance(srv, dict) and isinstance(srv.get("env"), dict):
                    srv["env"] = _mask_env(srv["env"])
        elif _is_secret_key(key) and isinstance(value, str):
            masked[key] = _SECRET_MASK if value else ""
    return masked


def _restore_masked(updates: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve mask sentinels in ``updates`` against the stored ``current`` config.

    A masked value coming back from the UI means "unchanged" — we substitute
    the real stored value (or drop the key) so writing the config never wipes a
    secret the UI never actually saw. Applies to top-level secret keys and to
    ``env`` values inside ``mcps`` / ``mcp_servers``.
    """
    import copy
    if not isinstance(updates, dict):
        return updates
    cleaned = copy.deepcopy(updates)
    cur = current if isinstance(current, dict) else {}
    for key, value in list(cleaned.items()):
        if isinstance(value, str) and value == _SECRET_MASK:
            if key in cur:
                cleaned[key] = cur[key]
            else:
                del cleaned[key]
        elif key == "mcps" and isinstance(value, dict):
            cur_mcps = cur.get("mcps", {}) if isinstance(cur.get("mcps"), dict) else {}
            for sid, srv in value.items():
                if isinstance(srv, dict) and isinstance(srv.get("env"), dict):
                    cur_env = (cur_mcps.get(sid, {}) or {}).get("env", {}) if isinstance(cur_mcps.get(sid), dict) else {}
                    srv["env"] = {
                        ek: (cur_env.get(ek, "") if ev == _SECRET_MASK else ev)
                        for ek, ev in srv["env"].items()
                    }
        elif key == "mcp_servers" and isinstance(value, list):
            cur_servers = cur.get("mcp_servers", []) if isinstance(cur.get("mcp_servers"), list) else []
            cur_by_id = {s.get("id"): s for s in cur_servers if isinstance(s, dict)}
            for srv in value:
                if isinstance(srv, dict) and isinstance(srv.get("env"), dict):
                    cur_env = (cur_by_id.get(srv.get("id"), {}) or {}).get("env", {})
                    srv["env"] = {
                        ek: (cur_env.get(ek, "") if ev == _SECRET_MASK else ev)
                        for ek, ev in srv["env"].items()
                    }
    return cleaned


@app.get("/api/config")
def get_config() -> Dict[str, Any]:
    # Mask secrets: this endpoint is unauthenticated loopback, so it must never
    # return stored credentials in clear text. Privacy first.
    return _mask_secrets(load_config())


class ConfigPatch(BaseModel):
    updates: Dict[str, Any]


@app.patch("/api/config")
def patch_config(patch: ConfigPatch) -> Dict[str, Any]:
    cfg_path = Path(os.environ.get("JARVIS_CONFIG_PATH") or default_config_path())
    current = _load_json(cfg_path)
    if not isinstance(current, dict):
        current = {}
    # Resolve any masked secret sentinels back to the stored values so a UI
    # round-trip of the masked config can never wipe a credential.
    updates = _restore_masked(patch.updates, current)
    current.update(updates)
    # Use the safety-net writer: takes a snapshot first, then atomic-write.
    # If the file is corrupted mid-write (crash/reboot), the previous version
    # is preserved.
    if not config_safety.safe_write_config(cfg_path, current):
        raise HTTPException(500, "Failed to write config")
    publish_log("info", f"Config updated: {list(patch.updates.keys())}")
    return current


# ---------- Config backup diagnostics ----------

@app.get("/api/config/backups")
def list_config_backups() -> List[Dict[str, Any]]:
    """Diagnostic: list all stored config backups, newest first."""
    return config_safety.list_backups()


# ---------- Logs ----------

@app.get("/api/logs")
def get_logs(limit: int = 500) -> List[Dict[str, Any]]:
    items = list(_log_buffer)
    if limit > 0:
        items = items[-limit:]
    return items


@app.delete("/api/logs")
def clear_logs() -> Dict[str, bool]:
    _log_buffer.clear()
    publish_log("info", "Log buffer cleared")
    return {"ok": True}


# ---------- MCP servers ----------

MCP_CATALOG = [
    {"id": "weather", "name": "Weather", "description": "OpenWeather forecasts", "version": "1.2.0"},
    {"id": "spotify", "name": "Spotify", "description": "Music playback & search", "version": "2.0.1"},
    {"id": "gmail", "name": "Gmail", "description": "Email reading & search", "version": "1.0.4"},
    {"id": "calendar", "name": "Calendar", "description": "Google Calendar events", "version": "0.9.2"},
    {"id": "notes", "name": "Notes", "description": "Note-taking & reminders", "version": "1.1.0"},
    {"id": "browser", "name": "Browser", "description": "Web search & automation", "version": "1.3.0"},
    {"id": "apps", "name": "Apps", "description": "Desktop app launcher", "version": "1.0.0"},
]


@app.get("/api/mcps")
def get_mcps() -> List[Dict[str, Any]]:
    cfg = load_config()
    enabled_ids = {srv.get("id") for srv in cfg.get("mcp_servers", []) if isinstance(srv, dict)}
    return [
        {
            **entry,
            "enabled": entry["id"] in enabled_ids,
            "status": "connected" if entry["id"] in enabled_ids else "disconnected",
        }
        for entry in MCP_CATALOG
    ]


class MCPToggle(BaseModel):
    enabled: bool


@app.patch("/api/mcps/{server_id}")
def toggle_mcp(server_id: str, body: MCPToggle) -> Dict[str, Any]:
    if not any(e["id"] == server_id for e in MCP_CATALOG):
        raise HTTPException(404, f"Unknown MCP server: {server_id}")
    cfg_path = Path(os.environ.get("JARVIS_CONFIG_PATH") or default_config_path())
    cfg = _load_json(cfg_path)
    servers = cfg.get("mcp_servers", []) or []
    servers = [s for s in servers if not (isinstance(s, dict) and s.get("id") == server_id)]
    if body.enabled:
        servers.append({"id": server_id})
    cfg["mcp_servers"] = servers
    _save_json(cfg_path, cfg)
    publish_log("info", f"MCP {server_id} {'enabled' if body.enabled else 'disabled'}")
    return {"id": server_id, "enabled": body.enabled}


# ---------- Memory (dialogue summaries) ----------

@app.get("/api/memory")
def get_memory(q: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent conversation summaries from sqlite."""
    try:
        from .memory.db import Database
        cfg = load_config()
        db = Database(cfg.get("db_path"))
        rows = db.get_recent_conversation_summaries(days=30)
        items: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            snippet = (d.get("summary") or d.get("content") or "").strip()
            ts = d.get("date_utc") or d.get("created_at") or ""
            if q and q.lower() not in snippet.lower():
                continue
            items.append({
                "id": str(d.get("id", "")),
                "timestamp": str(ts),
                "snippet": snippet[:280],
            })
        return items[:limit]
    except Exception as e:
        debug_log(f"api: memory list failed: {e}", "api")
        return []


@app.delete("/api/memory")
def clear_memory() -> Dict[str, bool]:
    """Best-effort clear — depends on the schema. Logged for now."""
    publish_log("warning", "Memory clear requested via API (not fully wired)")
    return {"ok": True}


# ---------- Graph-fact scrub (review-gated) ----------
#
# Mirrors the diary deflection scrub's contract (NDJSON-streaming on the
# apply path, counts-only on every streamed event) but for the knowledge
# graph. Two stages behind ONE endpoint, switched by the ``apply`` query
# flag:
#   • propose (default): runs ``scrub_graph_facts`` and returns the per-
#     fact deletion proposals as plain JSON. Raw fact text is allowed in
#     THIS response only — it is the review surface the LOCAL user reads
#     to decide what to delete. Nothing is mutated.
#   • apply (``?apply=true``): runs ``apply_graph_scrub`` on the user-
#     confirmed subset and STREAMS NDJSON progress carrying COUNTS ONLY —
#     never raw fact text — so the streaming UI cannot become a data-
#     exfiltration channel. Privacy first.
#
# The store/settings resolution is factored into two helpers so tests can
# stub them without opening the live SQLite graph.


def _resolve_graph_store():
    """Open the knowledge-graph store at the configured DB path.

    Read-mostly: never triggers the legacy-shape migration (that is the
    daemon start-up path's job — see graph.spec.md). Kept as a module-
    level function so tests can monkeypatch it.
    """
    from .memory.graph import GraphMemoryStore

    settings = _load_settings_safe()
    return GraphMemoryStore(settings.db_path)


def _load_settings_safe():
    """Resolve runtime settings for the graph-scrub endpoint.

    Thin wrapper around ``load_settings`` so tests can monkeypatch the
    whole resolution in one place.
    """
    from .config import load_settings

    return load_settings()


class GraphScrubApply(BaseModel):
    # The user-confirmed subset of proposals to delete. Each item is a
    # ``{"branch", "fact"}`` dict echoed back from the propose response.
    approved: List[Dict[str, Any]] = []


@app.post("/api/graph/scrub-facts")
def graph_scrub_facts(apply: bool = False, body: Optional[GraphScrubApply] = None):
    """Propose (default) or apply (``?apply=true``) graph-fact deletions.

    Propose returns ``{"proposals": [...], "applied": false}`` as JSON —
    raw fact text included, since this is the local user's review surface.
    Apply streams NDJSON (``start`` → ``complete``) with counts only.

    Both paths fail open: the underlying ops swallow per-branch LLM
    failures, and the apply stream surfaces only an exception *class name*
    on a hard error so a corrupted fact's content cannot leak via a
    stringified exception.
    """
    from .memory import graph_ops

    if not apply:
        # ── Propose: review-gated, no mutation. Plain JSON (the local
        # user reads the raw facts here to decide what to delete).
        try:
            settings = _load_settings_safe()
            store = _resolve_graph_store()
            result = graph_ops.scrub_graph_facts(
                store,
                settings.ollama_base_url,
                settings.ollama_chat_model,
            )
        except Exception as e:
            debug_log(f"graph scrub propose failed: {type(e).__name__}", "memory")
            # Fail-open: an empty proposal set is a safe "nothing to do".
            return {"proposals": [], "applied": False}
        return result

    # ── Apply: stream NDJSON counts only. The raw approved facts arrive in
    # the request body (already reviewed by the user); the RESPONSE stream
    # carries only counts so it cannot echo memory content to the browser.
    approved = list(body.approved) if body is not None else []

    def generate():
        try:
            total = len(approved)
            yield json.dumps({"type": "start", "total": total}) + "\n"

            store = _resolve_graph_store()
            result = graph_ops.apply_graph_scrub(store, approved)

            yield json.dumps({
                "type": "complete",
                "processed": total,
                "removed": int(result.get("removed", 0)),
            }) + "\n"
        except Exception as e:
            # Surface only the class name to the streaming UI so an
            # approved fact's content cannot leak via the exception message.
            debug_log(f"graph scrub apply failed: {type(e).__name__}", "memory")
            yield json.dumps({"type": "error", "message": type(e).__name__}) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Fast paths ----------

@app.get("/api/fastpaths")
def get_fastpaths() -> List[Dict[str, Any]]:
    try:
        from .listening import fast_paths as fp_mod
        registry = getattr(fp_mod, "_PATTERNS", None) or getattr(fp_mod, "FAST_PATHS", None) or []
        result: List[Dict[str, Any]] = []
        for i, pat in enumerate(registry):
            if isinstance(pat, dict):
                result.append({
                    "id": str(i),
                    "pattern": str(pat.get("pattern", "")),
                    "tool": str(pat.get("tool_name", "") or pat.get("tool", "")),
                    "response": str(pat.get("response_override", "") or pat.get("response", "")),
                })
            else:
                result.append({
                    "id": str(i),
                    "pattern": str(getattr(pat, "pattern", "")),
                    "tool": str(getattr(pat, "tool_name", "")),
                    "response": str(getattr(pat, "response_override", "")),
                })
        return result
    except Exception as e:
        debug_log(f"api: fastpaths list failed: {e}", "api")
        return []


# ---------- Easter eggs ----------

@app.get("/api/eastereggs")
def get_eastereggs() -> List[Dict[str, Any]]:
    cfg = load_config()
    eggs = cfg.get("easter_eggs") or [{
        "id": "daddys_home",
        "name": "Daddy's Home",
        "triggers": ["daddy's home", "papa's home", "dad is home"],
        "description": "Plays The Clash + cinematic JARVIS greeting with calendar/weather context",
        "enabled": True,
    }]
    return eggs


class EggToggle(BaseModel):
    enabled: bool


@app.patch("/api/eastereggs/{egg_id}")
def toggle_egg(egg_id: str, body: EggToggle) -> Dict[str, Any]:
    # Persist the enabled flag to config (previously this only logged, so the
    # toggle reverted on refresh / restart).
    cfg_path = Path(os.environ.get("JARVIS_CONFIG_PATH") or default_config_path())
    current = _load_json(cfg_path)
    if not isinstance(current, dict):
        current = {}
    eggs = current.get("easter_eggs")
    if not isinstance(eggs, list) or not eggs:
        # Seed from the default so the toggle has a concrete entry to persist.
        eggs = [{
            "id": "daddys_home",
            "name": "Daddy's Home",
            "triggers": ["daddy's home", "papa's home", "dad is home"],
            "description": "Plays The Clash + cinematic JARVIS greeting with calendar/weather context",
            "enabled": True,
        }]
    found = False
    for egg in eggs:
        if isinstance(egg, dict) and egg.get("id") == egg_id:
            egg["enabled"] = bool(body.enabled)
            found = True
            break
    if not found:
        publish_log("warning", f"Easter egg '{egg_id}' not found — toggle ignored")
        return {"id": egg_id, "enabled": body.enabled, "ok": False}
    current["easter_eggs"] = eggs
    if not config_safety.safe_write_config(cfg_path, current):
        raise HTTPException(500, "Failed to write config")
    publish_log("info", f"Easter egg '{egg_id}' set to {body.enabled}")
    return {"id": egg_id, "enabled": body.enabled, "ok": True}


# ---------- LLM models ----------

@app.get("/api/llm/models")
def list_llm_models() -> List[Dict[str, Any]]:
    try:
        import requests
        cfg = load_config()
        url = cfg.get("ollama_base_url", "http://localhost:11434") + "/api/tags"
        r = requests.get(url, timeout=2.0)
        if r.status_code == 200:
            data = r.json()
            return [
                {"name": m.get("name"), "size": m.get("size", 0), "modified": m.get("modified_at")}
                for m in data.get("models", [])
            ]
    except Exception as e:
        debug_log(f"api: ollama tags failed: {e}", "api")
    return []


# ---------- Audio devices ----------

@app.get("/api/audio/devices")
def list_audio_devices() -> Dict[str, Any]:
    # Delegate to the Core Audio device service so the settings UI gets the
    # id-carrying device list: {inputs, outputs} where each entry is
    # {id, name, is_default, available}. Persisting + resolving by the stable
    # endpoint id (not friendly name) is what makes the selection survive
    # restarts/reconnects. Imported as a module (not by-name) so the function
    # stays monkeypatchable in tests.
    try:
        from .output import audio_devices
        return audio_devices.list_devices()
    except Exception as e:
        debug_log(f"api: audio devices failed: {e}", "api")
        return {"inputs": [], "outputs": []}


@app.post("/api/audio/test-tone")
def test_tone() -> Dict[str, bool]:
    try:
        import numpy as np
        import sounddevice as sd

        # Honor the configured output device (tts_output_device) so the tone
        # verifies the SAME speaker Jarvis speaks through. Resolve fresh from
        # config (not the cached helper) so a just-saved change is reflected.
        device = None
        try:
            # Resolve the SAME persisted endpoint-id selection the TTS path uses
            # (the old tts_output_device key is dead after the audio redesign).
            from .output.tts import _resolve_output_device_live
            device = _resolve_output_device_live()
        except Exception:
            device = None

        # Match the device's native rate — WASAPI devices reject mismatched
        # rates (e.g. 22050 on a 48000 headset), exactly like the TTS path.
        sr = 22050
        if device is not None:
            try:
                sr = int(round(float(sd.query_devices(device).get("default_samplerate", 22050))))
            except Exception:
                sr = 22050
        t = np.linspace(0, 0.4, int(sr * 0.4), endpoint=False)
        tone = (0.25 * np.sin(2 * np.pi * 880 * t)).astype("float32")
        try:
            sd.play(tone, sr, device=device)
        except Exception:
            sd.play(tone, 22050)  # last resort: system default
        try:
            _di = sd.query_devices(device) if device is not None else None
            _dn = (
                f"{_di['name']} [{sd.query_hostapis(_di['hostapi'])['name']}]"
                if _di else "(PortAudio default)"
            )
        except Exception:
            _dn = "?"
        publish_log("info", f"Test tone played (880 Hz, device={device} {_dn})")
        return {"ok": True}
    except Exception as e:
        publish_log("error", f"Test tone failed: {e}")
        return {"ok": False}


# ---------- TTS cache ----------

@app.get("/api/tts/cache")
def tts_cache_stats() -> Dict[str, Any]:
    try:
        from .output.tts_cache import get_cache
        cache = get_cache()
        return {
            "hits": int(getattr(cache, "hit_count", 0)),
            "misses": int(getattr(cache, "miss_count", 0)),
            "size_bytes": int(getattr(cache, "total_bytes", lambda: 0)() if callable(getattr(cache, "total_bytes", None)) else getattr(cache, "total_bytes", 0)),
            "count": int(getattr(cache, "entry_count", lambda: 0)() if callable(getattr(cache, "entry_count", None)) else getattr(cache, "entry_count", 0)),
        }
    except Exception:
        return {"hits": 0, "misses": 0, "size_bytes": 0, "count": 0}


@app.delete("/api/tts/cache")
def tts_cache_clear() -> Dict[str, bool]:
    try:
        from .output.tts_cache import get_cache
        cache = get_cache()
        if hasattr(cache, "clear"):
            cache.clear()
        publish_log("info", "TTS cache cleared")
        return {"ok": True}
    except Exception as e:
        publish_log("error", f"TTS cache clear failed: {e}")
        return {"ok": False}


# ---------- WebSocket: live logs ----------

@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _log_subscribers_lock:
        _log_subscribers.append(q)
    try:
        for entry in list(_log_buffer)[-100:]:
            await ws.send_json(entry)
        while True:
            entry = await q.get()
            await ws.send_json(entry)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        with _log_subscribers_lock:
            try:
                _log_subscribers.remove(q)
            except ValueError:
                pass


# ---------- WebSocket: voice state ----------

@app.websocket("/ws/state")
async def ws_state(ws: WebSocket) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    with _state_subscribers_lock:
        _state_subscribers.append(q)
    try:
        await ws.send_json({**_voice_state, "uptime": time.time() - _started_at})
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        with _state_subscribers_lock:
            try:
                _state_subscribers.remove(q)
            except ValueError:
                pass


# ---------- Static UI (built React) — SPA-aware ----------

def _mount_static_if_present() -> None:
    """If a built React UI exists under <repo>/ui/dist, serve it.

    React Router uses client-side routing (e.g. `/panel`), so any non-/api
    path that isn't a real asset file must return index.html — otherwise
    a direct hit on `/panel` 404s. We:
      1. Mount /assets for hashed JS/CSS
      2. Serve the favicon if it exists
      3. Add a catch-all route returning index.html for everything else
         (after the /api/* and /ws/* routes have had their chance)
    """
    candidates = [
        Path(__file__).resolve().parents[2] / "ui" / "dist",
        Path(__file__).resolve().parents[3] / "ui" / "dist",
    ]
    dist_dir: Optional[Path] = None
    for c in candidates:
        if c.exists() and (c / "index.html").exists():
            dist_dir = c
            break

    if dist_dir is None:
        return

    print(f"🌐 Serving React UI from {dist_dir}", flush=True)

    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    index_path = dist_dir / "index.html"

    @app.get("/")
    def _index_root() -> FileResponse:
        return FileResponse(str(index_path), media_type="text/html")

    @app.get("/{full_path:path}")
    def _spa_fallback(full_path: str) -> Response:
        # API + WebSocket routes are matched FIRST by FastAPI's routing
        # (they were registered with decorators above this function). This
        # catch-all only fires for unmatched paths — but be defensive and
        # 404 anything starting with api/ or ws/ that slipped through.
        if full_path.startswith(("api/", "ws/")):
            return Response(status_code=404)
        # If the request matches an actual file on disk (e.g. favicon.ico),
        # serve it; otherwise fall back to index.html for client routing.
        candidate = dist_dir / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index_path), media_type="text/html")


_mount_static_if_present()


# ---------------------------------------------------------------------------
# Public entry: start the server on a background thread
# ---------------------------------------------------------------------------

_server_thread: Optional[threading.Thread] = None
_server_instance: Optional[uvicorn.Server] = None


# ---------- stdout mirror so daemon prints appear in Live Logs ----------

_STDOUT_MIRROR_INSTALLED = False


class _StdoutMirror:
    """File-like wrapper that tees writes to the original stream AND publish_log.

    Categorises lines into log levels by scanning for emoji markers used
    throughout the codebase:
      ⚡ → fast-path     🎬 → easter-egg      🔌/🌐 → info
      ⚠️/❌/⛔ → warning/error    everything else → info
    """

    def __init__(self, real_stream) -> None:
        self._real = real_stream
        self._buf = ""

    def write(self, text: str) -> int:
        try:
            self._real.write(text)
        except Exception:
            pass
        if not text:
            return 0
        self._buf += text
        # Emit per complete line so we don't spam half-lines.
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            stripped = line.rstrip()
            if not stripped:
                continue
            level = _classify_log_level(stripped)
            # Privacy: the Live Logs buffer + SSE feed are served over the
            # unauthenticated loopback API. Scrub emails / card numbers / API
            # keys / tokens / keyword-anchored credentials before a transcript,
            # reply, or always-on error line is stored. scrub_secrets keeps the
            # line readable (no whitespace collapse) so logs stay useful.
            try:
                safe = scrub_secrets(stripped)
            except Exception:
                safe = stripped
            try:
                publish_log(level, safe)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        try:
            self._real.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._real.isatty())
        except Exception:
            return False

    def __getattr__(self, name):
        return getattr(self._real, name)


def _classify_log_level(line: str) -> str:
    low = line.lower()
    if "⚡" in line or "fast-path" in low or "fast path" in low:
        return "fast-path"
    if "🎬" in line:
        return "easter-egg"
    if "[mcp]" in low or "mcp call" in low or "mcp server" in low:
        return "mcp"
    if "❌" in line or "error" in low or "traceback" in low or "exception" in low:
        return "error"
    if "⚠️" in line or "⚠" in line or "warning" in low:
        return "warning"
    return "info"


def install_stdout_mirror() -> None:
    """Wrap sys.stdout/sys.stderr so every print() also feeds the Live Logs feed.

    Idempotent — safe to call multiple times.
    """
    global _STDOUT_MIRROR_INSTALLED
    if _STDOUT_MIRROR_INSTALLED:
        return
    try:
        import sys as _sys
        if not isinstance(_sys.stdout, _StdoutMirror):
            _sys.stdout = _StdoutMirror(_sys.stdout)
        if not isinstance(_sys.stderr, _StdoutMirror):
            _sys.stderr = _StdoutMirror(_sys.stderr)
        _STDOUT_MIRROR_INSTALLED = True
    except Exception:
        pass


_startup_error: Optional[BaseException] = None
_startup_error_lock = threading.Lock()


def _set_startup_error(err: Optional[BaseException]) -> None:
    global _startup_error
    with _startup_error_lock:
        _startup_error = err


def get_startup_error() -> Optional[BaseException]:
    """Return the most recent uvicorn / port-binding failure, or None."""
    with _startup_error_lock:
        return _startup_error


def _check_port_available(host: str, port: int) -> bool:
    """Return True iff (host, port) can currently be bound for listening."""
    import socket as _socket
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def start_in_background() -> bool:
    """Start uvicorn in a daemon thread. Returns True on success.

    Hardening over the naive version:
      • If the port is already in use, refuse to start and record an
        actionable error retrievable via ``get_startup_error()`` — instead
        of letting uvicorn die silently inside the daemon thread.
      • Wait up to ~10s for the socket to accept connections (was ~2s),
        and propagate any uvicorn-thread crash as the startup error so the
        caller can surface it.
    """
    global _server_thread, _server_instance
    if _server_thread is not None and _server_thread.is_alive():
        return True

    _set_startup_error(None)

    if not _check_port_available(API_HOST, API_PORT):
        err = RuntimeError(
            f"Port {API_PORT} is already in use on {API_HOST}. "
            f"Another Jarvis instance may be running. "
            f"Find the holder with: netstat -ano | findstr :{API_PORT}"
        )
        _set_startup_error(err)
        print(f"⚠️ {err}", flush=True)
        return False

    config = uvicorn.Config(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="warning",
        access_log=False,
    )
    _server_instance = uvicorn.Server(config)

    def _run() -> None:
        try:
            _server_instance.run()
        except Exception as e:
            _set_startup_error(e)
            print(f"⚠️ API server crashed: {e}", flush=True)

    _server_thread = threading.Thread(target=_run, daemon=True, name="JarvisAPIServer")
    _server_thread.start()

    import socket as _socket
    for _ in range(100):
        time.sleep(0.1)
        if get_startup_error() is not None:
            return False
        try:
            with _socket.create_connection((API_HOST, API_PORT), timeout=0.2):
                print(f"🌐 API server listening on http://{API_HOST}:{API_PORT}", flush=True)
                return True
        except OSError:
            continue
    print(f"⚠️ API server did not become reachable on {API_PORT} within 10s", flush=True)
    return False


def stop() -> None:
    if _server_instance is not None:
        _server_instance.should_exit = True
