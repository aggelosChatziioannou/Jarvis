"""clickScreen — click a UI element by label/description (safety-gated)."""

from typing import Any, Dict, Optional

from ...base import Tool, ToolContext
from ...types import ToolExecutionResult
from ._shared import get_vision_engine, raw, vision_enabled


class ClickScreenTool(Tool):
    @property
    def name(self) -> str:
        return "clickScreen"

    @property
    def description(self) -> str:
        return (
            "Click a UI element identified by its visible label or description. In Assist mode "
            "this PROPOSES the click and the result will say requires_confirmation — tell the user "
            "what you will click and, once they agree, call confirmScreenAction. In Auto mode (only "
            "for whitelisted apps) it clicks immediately. Returns raw data with the result."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Visible label or description of the element to click, e.g. 'Submit button', 'the gear icon'.",
                }
            },
            "required": ["target"],
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        if not vision_enabled(context.cfg):
            return ToolExecutionResult(success=True, reply_text=raw({"result": "vision_disabled"}))
        target = (args or {}).get("target")
        if not target:
            return ToolExecutionResult(success=False, reply_text=None, error_message="clickScreen requires 'target'")
        context.user_print(f"🖱️ Locating '{target}' to click…")
        try:
            result = get_vision_engine(context.cfg).click(target)
        except Exception as exc:
            return ToolExecutionResult(success=False, reply_text=None, error_message=f"clickScreen failed: {exc}")
        return ToolExecutionResult(success=True, reply_text=raw(result))
