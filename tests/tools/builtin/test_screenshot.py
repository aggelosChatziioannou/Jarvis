"""Tests for the screenshot tool (cross-platform: mss capture + Tesseract OCR)."""

from unittest.mock import Mock

import jarvis.vision.analyzer as analyzer
import jarvis.vision.capture as capture
from jarvis.tools.base import ToolContext
from jarvis.tools.builtin.screenshot import ScreenshotTool
from jarvis.tools.types import ToolExecutionResult


class TestScreenshotTool:
    def setup_method(self):
        self.tool = ScreenshotTool()
        self.context = Mock(spec=ToolContext)
        self.context.user_print = Mock()

    def test_tool_properties(self):
        assert self.tool.name == "screenshot"
        assert "capture" in self.tool.description.lower()
        assert self.tool.inputSchema["type"] == "object"
        assert self.tool.inputSchema["required"] == []

    def test_run_returns_ocr_text(self, monkeypatch):
        # Stub capture (no display) and OCR (no tesseract binary needed).
        monkeypatch.setattr(capture.ScreenCapture, "__init__", lambda self: None)
        monkeypatch.setattr(capture.ScreenCapture, "capture_primary", lambda self: object())
        monkeypatch.setattr(analyzer, "read_text", lambda image: "Sample OCR text")

        result = self.tool.run({}, self.context)

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert result.reply_text == "Sample OCR text"
        self.context.user_print.assert_called()

    def test_run_handles_capture_failure_gracefully(self, monkeypatch):
        def boom(self):
            raise RuntimeError("no display")

        monkeypatch.setattr(capture.ScreenCapture, "__init__", lambda self: None)
        monkeypatch.setattr(capture.ScreenCapture, "capture_primary", boom)

        result = self.tool.run({}, self.context)
        assert result.success is True
        assert result.reply_text == ""
