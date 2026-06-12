"""Ollama model administration: what is loaded, and unloading on demand.

Backs the console's VRAM controls (Live Logs page): the vision toggle evicts
the vision model immediately, and the full-VRAM flush unloads every resident
model. Unloading uses the documented Ollama idiom — a request with
``keep_alive: 0`` — via ``/api/generate`` for generative models and
``/api/embed`` for embedding models (a generate call against an embed-only
model errors instead of unloading).
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests

from .debug import debug_log

_TIMEOUT = 15.0


def is_embedding_model(name: str) -> bool:
    return "embed" in (name or "").lower()


def unload_payload(name: str) -> Dict[str, Any]:
    """The request body that makes Ollama release a model's VRAM."""
    if is_embedding_model(name):
        return {"model": name, "input": "", "keep_alive": 0}
    return {"model": name, "prompt": "", "keep_alive": 0}


def list_loaded_models(base_url: str) -> List[Dict[str, Any]]:
    """[{name, size_vram}] for every model currently resident (GET /api/ps)."""
    try:
        with requests.get(f"{base_url.rstrip('/')}/api/ps", timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        debug_log(f"model_admin: /api/ps failed — {e}", "llm")
        return []
    models = []
    for m in (data or {}).get("models", []) or []:
        models.append({
            "name": str(m.get("name") or m.get("model") or ""),
            "size_vram": int(m.get("size_vram") or m.get("size") or 0),
        })
    return [m for m in models if m["name"]]


def unload_model(base_url: str, name: str) -> bool:
    """Ask Ollama to release one model's VRAM. True if the request succeeded."""
    endpoint = "/api/embed" if is_embedding_model(name) else "/api/generate"
    try:
        with requests.post(
            f"{base_url.rstrip('/')}{endpoint}",
            json=unload_payload(name),
            timeout=_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
        debug_log(f"model_admin: unloaded {name}", "llm")
        return True
    except Exception as e:
        debug_log(f"model_admin: unload {name} failed — {e}", "llm")
        return False


def unload_all(base_url: str) -> List[str]:
    """Unload every resident model. Returns the names that were released."""
    released = []
    for m in list_loaded_models(base_url):
        if unload_model(base_url, m["name"]):
            released.append(m["name"])
    return released
