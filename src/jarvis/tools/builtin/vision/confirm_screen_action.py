"""confirmScreenAction — execute the screen action awaiting confirmation."""

from typing import Any, Dict, Optional

from ...base import Tool, ToolContext
from ...types import ToolExecutionResult
from ._shared import disabled_reply, get_vision_engine, raw, vision_enabled


class ConfirmScreenActionTool(Tool):
    @property
    def name(self) -> str:
        return "confirmScreenAction"

    @property
    def description(self) -> str:
        return (
            "Execute the screen action (click / type / scroll) that was just proposed and is "
            "awaiting confirmation. Call this ONLY when the user has clearly agreed to proceed "
            "(in any language). It re-checks the target before acting. If nothing is pending or it "
            "has expired, it says so. Returns raw data with the outcome."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        if not vision_enabled(context.cfg):
            return ToolExecutionResult(success=True, reply_text=disabled_reply())
        context.user_print("✅ Confirming the action…")
        try:
            result = get_vision_engine(context.cfg).confirm()
        except Exception as exc:
            return ToolExecutionResult(success=False, reply_text=None, error_message=f"confirmScreenAction failed: {exc}")
        return ToolExecutionResult(success=True, reply_text=raw(result))
