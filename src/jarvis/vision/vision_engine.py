"""VisionEngine — the single facade the Tools talk to.

Orchestrates capture + analysis (Tesseract / qwen2.5vl) + coordinate conversion
(monitor_map) + safety gating + interaction. Returns **raw data** (dicts and
points) only — never prose, never TTS. The reply engine's LLM loop and
``system_prompt.py`` do all formatting.

Locate uses the agreed fallback chain:
  1. Tesseract word-boxes (text labels) — fast, deterministic, 0 extra VRAM
  2. qwen2.5vl grounding (icons / coloured buttons)
  3. give up -> found: False

Action verbs (click/type/scroll) are gated by SafetyGuard, which returns
execute / confirm / refused. ``confirm()`` runs a stashed action only after the
user assents (the LLM judges the spoken confirmation), re-validating first.
"""

from __future__ import annotations

from typing import Optional

from ..debug import debug_log
from .analyzer import locate_text_label as _locate_text_label
from .analyzer import read_text as _read_text
from .capture import ScreenCapture
from .interaction import Interactor
from .model_client import VisionModelClient
from .monitor_map import MonitorMap, MonitorRef
from .safety import Mode, SafetyGuard, looks_sensitive


def _mon_name(monitor: MonitorRef) -> str:
    return str(monitor)


class VisionEngine:
    def __init__(
        self,
        capture: ScreenCapture,
        monitors: MonitorMap,
        client: VisionModelClient,
        safety: SafetyGuard,
        interactor: Interactor,
        locate_text_fn=_locate_text_label,
        read_text_fn=_read_text,
    ) -> None:
        self.capture = capture
        self.monitors = monitors
        self.client = client
        self.safety = safety
        self.interactor = interactor
        self._locate_text = locate_text_fn
        self._read_text = read_text_fn

    # --- perception (OBSERVE-safe) -------------------------------------

    def observe(self, monitor: MonitorRef = "primary") -> dict:
        img = self.capture.capture_monitor(monitor)
        # Diagnostic: a "blank screen" report is either a black capture (mean
        # luminance ~0) or a real capture the model summarised as empty. Log
        # both so the two are distinguishable from the daemon logs.
        try:
            _thumb = img.convert("L").resize((32, 32))
            _data = list(_thumb.getdata())
            _mean = sum(_data) / len(_data)
            _nonblack = sum(1 for p in _data if p > 16) / len(_data) * 100
            debug_log(
                f"vision_engine: observe capture monitor={_mon_name(monitor)} "
                f"size={getattr(img, 'size', None)} mean_lum={_mean:.1f} "
                f"non_black={_nonblack:.0f}% (mean~0 = black capture vs content)",
                "vision",
            )
        except Exception:
            pass
        description = self.client.describe(img)
        debug_log(
            f"vision_engine: observe desc_len={len(description) if description else 0} "
            f"preview={(description or '')[:80]!r}",
            "vision",
        )
        if description is None:
            # Capture worked but the vision model did not respond (timeout or
            # still loading). Surface an explicit unavailable status so the
            # reply LLM tells the user vision is slow/unavailable instead of
            # confabulating screen contents from an empty description.
            debug_log("vision_engine: observe -> model unavailable (no response)", "vision")
            return {
                "status": "unavailable",
                "reason": "no_response",
                "description": None,
                "message": (
                    "The vision model did not respond in time (it may be slow to "
                    "load or temporarily unavailable); the screen was NOT analysed."
                ),
                "monitor": _mon_name(monitor),
            }
        return {"description": description, "monitor": _mon_name(monitor)}

    def read(self, monitor: MonitorRef = "primary") -> dict:
        img = self.capture.capture_monitor(monitor)
        text = self._read_text(img)
        return {"text": text, "monitor": _mon_name(monitor)}

    def locate(self, target: str, monitor: MonitorRef = "primary") -> dict:
        """Locate ``target`` and return its ABSOLUTE desktop coordinates."""
        img = self.capture.capture_monitor(monitor)
        rel = self._locate_text(img, target)
        method = "ocr"
        if rel is None:
            rel = self.client.locate(img, target)
            method = "vision"
        if rel is None:
            debug_log(f"vision_engine: locate {target!r} -> not found", "vision")
            return {"target": target, "found": False, "monitor": _mon_name(monitor)}
        abs_xy = self.monitors.to_absolute(rel[0], rel[1], monitor)
        debug_log(
            f"vision_engine: locate {target!r} -> abs={abs_xy} via {method}", "vision"
        )
        return {
            "target": target,
            "found": True,
            "coordinates": [int(abs_xy[0]), int(abs_xy[1])],
            "monitor": _mon_name(monitor),
            "method": method,
        }

    # --- actions (gated) ------------------------------------------------

    def click(self, target: str, monitor: MonitorRef = "primary") -> dict:
        loc = self.locate(target, monitor)
        if not loc.get("found"):
            return {"action": "click", "target": target, "result": "not_found",
                    "monitor": _mon_name(monitor)}
        coords = (loc["coordinates"][0], loc["coordinates"][1])
        decision = self.safety.decide("click", coordinates=coords, monitor=monitor, target=target)
        base = {
            "action": "click", "target": target, "coordinates": list(coords),
            "monitor": loc["monitor"], "method": loc["method"], "app": decision.app,
        }
        if decision.verdict == "refused":
            return {**base, "result": "refused", "reason": decision.reason}
        if decision.verdict == "execute":
            self.interactor.click(coords[0], coords[1])
            return {**base, "result": "executed"}
        return {**base, "result": "needs_confirmation", "requires_confirmation": True}

    def type_text(self, text: str, monitor: MonitorRef = "primary") -> dict:
        decision = self.safety.decide("type", text=text)
        preview = (text or "")[:120]
        base = {"action": "type", "text": preview, "chars": len(text or ""), "app": decision.app}
        if decision.verdict == "refused":
            return {**base, "result": "refused", "reason": decision.reason}
        if decision.verdict == "execute":
            self.interactor.type_text(text)
            return {**base, "result": "executed"}
        return {**base, "result": "needs_confirmation", "requires_confirmation": True}

    def scroll(self, direction: str, amount: int = 3, monitor: MonitorRef = "primary") -> dict:
        # direction is an API enum ('up'/'down'), mapped from any language by the LLM.
        sign = 1 if str(direction).lower().startswith("up") else -1
        signed = abs(int(amount)) * sign
        decision = self.safety.decide("scroll", direction=direction, amount=signed)
        base = {"action": "scroll", "direction": direction, "amount": signed, "app": decision.app}
        if decision.verdict == "refused":
            return {**base, "result": "refused", "reason": decision.reason}
        if decision.verdict == "execute":
            self.interactor.scroll(signed)
            return {**base, "result": "executed"}
        return {**base, "result": "needs_confirmation", "requires_confirmation": True}

    # --- confirmation (Turn 2) -----------------------------------------

    def confirm(self) -> dict:
        """Execute the stashed pending action after the user assents.

        Handles 'no pending' gracefully and re-validates a click target (the
        screen may have changed since it was proposed)."""
        p = self.safety.take_pending()
        if p is None:
            return {"result": "no_pending_action"}

        if p.action == "click":
            # Re-locate against a fresh screenshot — the screen may have moved.
            loc = self.locate(p.target, p.monitor or "primary") if p.target else None
            if not loc or not loc.get("found"):
                return {"result": "target_vanished", "target": p.target}
            coords = (loc["coordinates"][0], loc["coordinates"][1])
            if not self.safety.validate_coordinates(coords[0], coords[1], p.monitor or "primary"):
                return {"result": "refused", "reason": "out_of_bounds"}
            self.interactor.click(coords[0], coords[1])
            return {"result": "executed", "action": "click", "target": p.target,
                    "coordinates": list(coords), "method": loc["method"]}

        if p.action == "type":
            if looks_sensitive(p.text):
                return {"result": "refused", "reason": "sensitive_input"}
            self.interactor.type_text(p.text or "")
            return {"result": "executed", "action": "type", "chars": len(p.text or "")}

        if p.action == "scroll":
            self.interactor.scroll(int(p.amount or 0))
            return {"result": "executed", "action": "scroll", "amount": p.amount}

        return {"result": "unknown_action"}

    # --- construction ---------------------------------------------------

    @classmethod
    def build(cls, cfg) -> "VisionEngine":
        """Wire real collaborators from config."""
        monitors = MonitorMap()
        capture = ScreenCapture(monitor_map=monitors)
        client = VisionModelClient(
            base_url=getattr(cfg, "ollama_base_url", "http://127.0.0.1:11434"),
            model=getattr(cfg, "vision_model", "qwen2.5vl:3b"),
            keep_alive=getattr(cfg, "vision_keep_alive", "5m"),
            timeout_sec=float(getattr(cfg, "vision_timeout_sec", 20.0)),
            max_image_dim=getattr(cfg, "vision_max_width", 1280),
        )
        mode = Mode(str(getattr(cfg, "vision_default_mode", "assist")).lower())
        safety = SafetyGuard(
            monitor_map=monitors,
            mode=mode,
            auto_whitelist=getattr(cfg, "vision_auto_whitelist", ()) or (),
            auto_blacklist=getattr(cfg, "vision_auto_blacklist", ()) or (),
            pending_ttl_sec=float(getattr(cfg, "vision_pending_ttl_sec", 120.0)),
        )
        return cls(capture, monitors, client, safety, Interactor())
