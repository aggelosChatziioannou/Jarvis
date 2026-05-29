"""Screenshot tool: capture the primary screen and OCR its text (cross-platform).

Capture is delegated to the vision engine's mss-based ScreenCapture (in-memory,
never written to disk) and OCR to the shared Tesseract path in vision.analyzer,
so this works on Windows/Linux/macOS. The previous implementation shelled out to
macOS-only ``screencapture`` and silently returned empty text on every other
platform. Returns raw OCR text; the unified system prompt does the formatting.
For richer screen interaction (describe / locate / click) use the vision tools.
"""

from typing import Any, Dict, Optional

from ...debug import debug_log
from ..base import Tool, ToolContext
from ..types import ToolExecutionResult


class ScreenshotTool(Tool):
    """Capture the primary screen and return its OCR text."""

    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return (
            "Capture the primary screen and read its visible text via OCR (English and "
            "Greek). Use only when reading on-screen text will materially help the answer."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        context.user_print("📸 Capturing a screenshot for OCR…")
        debug_log("screenshot: capturing OCR...", "screenshot")
        ocr_text = ""
        try:
            from ...vision.capture import ScreenCapture
            from ...vision.analyzer import read_text

            image = ScreenCapture().capture_primary()
            ocr_text = read_text(image) or ""
        except Exception as exc:
            debug_log(f"screenshot: capture/OCR failed — {exc}", "screenshot")
        debug_log(f"screenshot: ocr_chars={len(ocr_text)}", "screenshot")
        context.user_print("✅ Screenshot processed.")
        # Raw OCR text only — no LLM processing here.
        return ToolExecutionResult(success=True, reply_text=ocr_text)
