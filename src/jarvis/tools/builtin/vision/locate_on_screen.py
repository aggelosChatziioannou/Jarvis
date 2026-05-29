"""locateOnScreen — find an element's coordinates without clicking (raw data)."""

from typing import Any, Dict, Optional

from ...base import Tool, ToolContext
from ...types import ToolExecutionResult
from ._shared import get_vision_engine, raw, vision_enabled


class LocateOnScreenTool(Tool):
    @property
    def name(self) -> str:
        return "locateOnScreen"

    @property
    def description(self) -> str:
        return (
            "Find where a UI element is on screen and return its coordinates WITHOUT clicking. "
            "Use when the user asks where something is, or to check an element exists. To actually "
            "click it, use clickScreen instead. Returns raw data {found, coordinates, method}."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Visible label or description of the element, e.g. 'Submit button', 'the gear icon'.",
                }
            },
            "required": ["target"],
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        if not vision_enabled(context.cfg):
            return ToolExecutionResult(success=True, reply_text=raw({"result": "vision_disabled"}))
        target = (args or {}).get("target")
        if not target:
            return ToolExecutionResult(success=False, reply_text=None, error_message="locateOnScreen requires 'target'")
        context.user_print(f"🔎 Locating '{target}'…")
        try:
            result = get_vision_engine(context.cfg).locate(target)
        except Exception as exc:
            return ToolExecutionResult(success=False, reply_text=None, error_message=f"locateOnScreen failed: {exc}")
        return ToolExecutionResult(success=True, reply_text=raw(result))
