"""seeScreen — describe what is on the user's screen (raw data)."""

from typing import Any, Dict, Optional

from ...base import Tool, ToolContext
from ...types import ToolExecutionResult
from ._shared import get_vision_engine, raw, vision_enabled


class SeeScreenTool(Tool):
    @property
    def name(self) -> str:
        return "seeScreen"

    @property
    def description(self) -> str:
        return (
            "See the user's screen: capture a screenshot and return a description of the visible "
            "windows, applications and UI elements. This tool is the ONLY way you can perceive the "
            "screen — you CANNOT know what is currently displayed from memory or the conversation. "
            "When the user asks what is on their screen or what you can see, you MUST call this tool "
            "and MUST NOT invent, guess, or describe screen contents without it. For reading exact "
            "text use readScreen instead. If the result has status 'unavailable', the vision model "
            "did not respond (slow to load or temporarily down): tell the user the vision system is "
            "temporarily unavailable or delayed and ask them to try again — do NOT guess or describe "
            "what might be on screen. Returns raw data; do not format here."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "monitor": {
                    "type": "string",
                    "enum": ["primary", "secondary"],
                    "description": "Which monitor to look at. Defaults to primary.",
                }
            },
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        if not vision_enabled(context.cfg):
            return ToolExecutionResult(success=True, reply_text=raw({"result": "vision_disabled"}))
        monitor = (args or {}).get("monitor", "primary")
        context.user_print("👁️ Looking at your screen…")
        try:
            result = get_vision_engine(context.cfg).observe(monitor)
        except Exception as exc:
            return ToolExecutionResult(success=False, reply_text=None, error_message=f"seeScreen failed: {exc}")
        return ToolExecutionResult(success=True, reply_text=raw(result))
