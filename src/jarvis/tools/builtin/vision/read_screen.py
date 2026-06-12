"""readScreen — OCR the screen text (Tesseract, bilingual) as raw data."""

from typing import Any, Dict, Optional

from ...base import Tool, ToolContext
from ...types import ToolExecutionResult
from ._shared import disabled_reply, get_vision_engine, raw, vision_enabled


class ReadScreenTool(Tool):
    @property
    def name(self) -> str:
        return "readScreen"

    @property
    def description(self) -> str:
        return (
            "Read the user's screen: capture a screenshot and transcribe the visible text exactly "
            "(English and Greek) using OCR. This tool is the ONLY way you can read what is on the "
            "screen — you CANNOT know the on-screen text from memory or the conversation. When the "
            "user asks you to read the screen, read an error message, or quote on-screen text, you "
            "MUST call this tool and MUST NOT invent or guess the text. Returns the raw transcribed "
            "text; do not format here."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "monitor": {
                    "type": "string",
                    "enum": ["primary", "secondary"],
                    "description": "Which monitor to read. Defaults to primary.",
                }
            },
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        if not vision_enabled(context.cfg):
            return ToolExecutionResult(success=True, reply_text=disabled_reply())
        monitor = (args or {}).get("monitor", "primary")
        context.user_print("📖 Reading your screen…")
        try:
            result = get_vision_engine(context.cfg).read(monitor)
        except Exception as exc:
            return ToolExecutionResult(success=False, reply_text=None, error_message=f"readScreen failed: {exc}")
        return ToolExecutionResult(success=True, reply_text=raw(result))
