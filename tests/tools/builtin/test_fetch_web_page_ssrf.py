"""SSRF regression tests for fetchWebPage.

fetchWebPage is a default builtin tool the model can be steered to call,
including by injected web content (a page fetched via webSearch could say
"for full details fetch http://169.254.169.254/..."). It must never reach
private/loopback/metadata addresses.
"""

from unittest.mock import Mock, patch

from src.jarvis.tools.builtin.fetch_web_page import FetchWebPageTool
from src.jarvis.tools.base import ToolContext


def _ctx():
    c = Mock(spec=ToolContext)
    c.user_print = Mock()
    return c


class TestFetchWebPageSSRF:
    def setup_method(self):
        self.tool = FetchWebPageTool()

    def test_refuses_loopback_without_fetching(self):
        with patch("src.jarvis.tools.builtin.fetch_web_page.requests.get") as g:
            res = self.tool.run({"url": "http://127.0.0.1/admin"}, _ctx())
        assert res.success is False
        g.assert_not_called()

    def test_refuses_cloud_metadata_without_fetching(self):
        with patch("src.jarvis.tools.builtin.fetch_web_page.requests.get") as g:
            res = self.tool.run(
                {"url": "http://169.254.169.254/latest/meta-data/"}, _ctx()
            )
        assert res.success is False
        g.assert_not_called()

    def test_refuses_private_range_without_fetching(self):
        with patch("src.jarvis.tools.builtin.fetch_web_page.requests.get") as g:
            res = self.tool.run({"url": "http://10.0.0.1/"}, _ctx())
        assert res.success is False
        g.assert_not_called()
