"""Tests for the shared SSRF-safe fetch helpers (tools/builtin/_net.py).

One audited implementation of the public-URL check + redirect-revalidating,
byte-capped fetch, shared by webSearch and fetchWebPage.
"""

import pytest
from unittest.mock import Mock, patch

from src.jarvis.tools.builtin._net import (
    is_public_url,
    safe_fetch,
    UnsafeURLError,
)


class TestIsPublicUrl:
    def test_rejects_non_http_schemes(self):
        assert is_public_url("file:///etc/passwd") is False
        assert is_public_url("ftp://example.com/") is False
        assert is_public_url("javascript:alert(1)") is False

    def test_rejects_private_loopback_and_metadata(self):
        assert is_public_url("http://127.0.0.1/") is False
        assert is_public_url("http://10.0.0.1/") is False
        assert is_public_url("http://192.168.1.1/") is False
        assert is_public_url("http://169.254.169.254/latest/meta-data/") is False
        assert is_public_url("http://[::1]/") is False

    def test_allows_public_literal_ip(self):
        assert is_public_url("https://1.1.1.1/") is True


def _resp(**attrs):
    r = Mock(**attrs)
    r.close = Mock()
    return r


class TestSafeFetch:
    def test_refuses_loopback_without_any_request(self):
        with patch("src.jarvis.tools.builtin._net.requests.get") as g:
            with pytest.raises(UnsafeURLError):
                safe_fetch("http://127.0.0.1/secret")
            g.assert_not_called()

    def test_refuses_redirect_into_private_space(self):
        redirect = _resp(
            is_redirect=True,
            is_permanent_redirect=False,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
        )
        with patch("src.jarvis.tools.builtin._net.requests.get", return_value=redirect) as g:
            with pytest.raises(UnsafeURLError):
                safe_fetch("https://1.1.1.1/start")
            # Stopped AT the redirect — never issued the second (unsafe) request.
            assert g.call_count == 1

    def test_caps_bytes(self):
        big = b"x" * 8192
        resp = _resp(
            is_redirect=False,
            is_permanent_redirect=False,
            raise_for_status=Mock(),
        )
        resp.iter_content = Mock(return_value=iter([big] * 1000))
        with patch("src.jarvis.tools.builtin._net.requests.get", return_value=resp):
            final_url, body = safe_fetch("https://1.1.1.1/", max_bytes=20_000)
        assert len(body) >= 20_000
        assert len(body) <= 20_000 + len(big)  # at most one chunk of overshoot
