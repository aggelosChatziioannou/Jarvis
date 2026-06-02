"""Tests for fetch web page tool.

Transport (SSRF validation, redirect re-validation, byte cap) lives in the
shared ``tools/builtin/_net.py`` and is covered by ``test__net.py`` +
``test_fetch_web_page_ssrf.py``. These tests cover the tool's extraction logic
by stubbing the shared ``safe_fetch`` to return canned page bytes.
"""

import pytest
from unittest.mock import Mock, patch
import requests

from src.jarvis.tools.builtin.fetch_web_page import FetchWebPageTool
from src.jarvis.tools.base import ToolContext
from src.jarvis.tools.types import ToolExecutionResult

_FETCH = "src.jarvis.tools.builtin.fetch_web_page.safe_fetch"


class TestFetchWebPageTool:
    """Test fetch web page tool functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tool = FetchWebPageTool()
        self.context = Mock(spec=ToolContext)
        self.context.user_print = Mock()

    def test_tool_properties(self):
        """Test tool metadata properties."""
        assert self.tool.name == "fetchWebPage"
        assert "fetch" in self.tool.description.lower()
        assert self.tool.inputSchema["type"] == "object"
        assert "url" in self.tool.inputSchema["required"]

    def test_run_no_args(self):
        """Test fetch web page with no arguments."""
        result = self.tool.run(None, self.context)

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "url" in result.reply_text.lower()

    def test_run_empty_url(self):
        """Test fetch web page with empty URL."""
        args = {"url": ""}
        result = self.tool.run(args, self.context)

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "url" in result.reply_text.lower()

    @patch(_FETCH)
    def test_run_success(self, mock_fetch):
        """Test successful web page fetch."""
        mock_fetch.return_value = (
            "https://example.com",
            b'<html><head><title>Test</title></head><body><p>Content</p></body></html>',
        )

        args = {"url": "https://example.com"}
        result = self.tool.run(args, self.context)

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert "example.com" in result.reply_text
        self.context.user_print.assert_called()

    @patch(_FETCH)
    def test_run_success_without_beautifulsoup(self, mock_fetch):
        """Test successful web page fetch without BeautifulSoup."""
        mock_fetch.return_value = (
            "https://example.com",
            b'<html><body>Raw content</body></html>',
        )

        with patch('builtins.__import__', side_effect=ImportError):
            args = {"url": "https://example.com"}
            result = self.tool.run(args, self.context)

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert "Raw Content" in result.reply_text

    @patch(_FETCH)
    def test_run_http_error(self, mock_fetch):
        """Test fetch web page with HTTP error."""
        mock_fetch.side_effect = requests.exceptions.HTTPError("404 Not Found")

        args = {"url": "https://example.com/notfound"}
        result = self.tool.run(args, self.context)

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "Failed to fetch page" in result.reply_text

    @patch(_FETCH)
    def test_run_request_error(self, mock_fetch):
        """Test fetch web page with network error."""
        mock_fetch.side_effect = requests.exceptions.RequestException("Network error")

        args = {"url": "https://example.com"}
        result = self.tool.run(args, self.context)

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "Failed to fetch page" in result.reply_text

    @patch(_FETCH)
    def test_run_invalid_url(self, mock_fetch):
        """An unresolvable/non-public URL is refused by the SSRF guard."""
        from src.jarvis.tools.builtin._net import UnsafeURLError
        mock_fetch.side_effect = UnsafeURLError("not public")
        args = {"url": "not-a-url"}
        result = self.tool.run(args, self.context)
        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "failed" in result.reply_text.lower() or "error" in result.reply_text.lower()

    @patch(_FETCH)
    def test_run_with_links_extraction(self, mock_fetch):
        """Test fetch web page including link extraction when include_links=True."""
        html = (
            '<html><head><title>Links Page</title></head>'
            '<body><p>Intro</p>'
            '<a href="/relative">Relative Link</a>'
            '<a href="https://absolute.test/page">Absolute Link</a>'
            '<a href="mailto:test@example.com">Mail</a>'
            '</body></html>'
        )
        mock_fetch.return_value = ("https://example.com", html.encode())

        args = {"url": "https://example.com", "include_links": True}
        result = self.tool.run(args, self.context)
        assert result.success is True
        assert isinstance(result, ToolExecutionResult)
        assert "Links found on page" in result.reply_text
        # relative link should be resolved to absolute
        assert "https://example.com/relative" in result.reply_text
        assert "absolute.test" in result.reply_text
