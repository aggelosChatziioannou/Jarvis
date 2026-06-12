"""scrollScreen — scroll up or down (safety-gated)."""

from typing import Any, Dict, Optional

from ...base import Tool, ToolContext
from ...types import ToolExecutionResult
from ._shared import disabled_reply, get_vision_engine, raw, vision_enabled


class ScrollScreenTool(Tool):
    @property
    def name(self) -> str:
        return "scrollScreen"

    @property
    def description(self) -> str:
        return (
            "Scroll the active window up or down. In Assist mode this PROPOSES the scroll "
            "(result says requires_confirmation); once the user agrees, call confirmScreenAction. "
            "In Auto mode (whitelisted apps) it scrolls immediately. Returns raw data."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction.",
                },
                "amount": {
                    "type": "integer",
                    "description": "Number of wheel steps (default 3).",
                },
            },
            "required": ["direction"],
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        if not vision_enabled(context.cfg):
            return ToolExecutionResult(success=True, reply_text=disabled_reply())
        args = args or {}
        direction = args.get("direction", "down")
        amount = args.get("amount", 3)
        context.user_print(f"🖱️ Preparing to scroll {direction}…")
        try:
            result = get_vision_engine(context.cfg).scroll(direction, amount=amount)
        except Exception as exc:
            return ToolExecutionResult(success=False, reply_text=None, error_message=f"scrollScreen failed: {exc}")
        return ToolExecutionResult(success=True, reply_text=raw(result))
