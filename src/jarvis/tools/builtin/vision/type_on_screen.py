"""typeOnScreen — type text via the keyboard (safety-gated)."""

from typing import Any, Dict, Optional

from ...base import Tool, ToolContext
from ...types import ToolExecutionResult
from ._shared import get_vision_engine, raw, vision_enabled


class TypeOnScreenTool(Tool):
    @property
    def name(self) -> str:
        return "typeOnScreen"

    @property
    def description(self) -> str:
        return (
            "Type the given text into whatever currently has keyboard focus. In Assist mode this "
            "PROPOSES the typing (result says requires_confirmation); once the user agrees, call "
            "confirmScreenAction. Sensitive input (card/account numbers) is always refused. "
            "Returns raw data with the result."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The exact text to type.",
                }
            },
            "required": ["text"],
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        if not vision_enabled(context.cfg):
            return ToolExecutionResult(success=True, reply_text=raw({"result": "vision_disabled"}))
        text = (args or {}).get("text")
        if text is None:
            return ToolExecutionResult(success=False, reply_text=None, error_message="typeOnScreen requires 'text'")
        context.user_print("⌨️ Preparing to type…")
        try:
            result = get_vision_engine(context.cfg).type_text(text)
        except Exception as exc:
            return ToolExecutionResult(success=False, reply_text=None, error_message=f"typeOnScreen failed: {exc}")
        return ToolExecutionResult(success=True, reply_text=raw(result))
