"""Tests for bounded/tuned generation in ``chat_with_messages``.

Verifies that the optional ``num_predict`` and ``temperature`` parameters are
forwarded into the Ollama request ``options`` payload when provided, and are
omitted entirely when left at their "unset" sentinel values. This keeps
default behaviour byte-for-byte identical to before the feature was added.
"""

from unittest.mock import patch, MagicMock

import pytest

from jarvis.llm import chat_with_messages


def _capture_payload(mock_post):
    """Extract the JSON payload from the first call to requests.post."""
    assert mock_post.called, "requests.post was never called"
    _, kwargs = mock_post.call_args
    return kwargs.get("json") or {}


def _make_resp():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"message": {"content": "ok"}}
    mock_resp.raise_for_status = MagicMock()
    # Support context-manager usage (``with requests.post(...) as resp``)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestChatGenerationBounds:
    @patch("jarvis.llm.requests.post")
    def test_num_predict_and_temperature_forwarded_to_options(self, mock_post):
        mock_post.return_value = _make_resp()

        msgs = [{"role": "user", "content": "hi"}]
        chat_with_messages(
            "http://localhost:11434",
            "gemma4:e2b",
            msgs,
            num_predict=200,
            temperature=0.3,
        )

        payload = _capture_payload(mock_post)
        options = payload.get("options") or {}
        assert options.get("num_predict") == 200
        assert options.get("temperature") == 0.3
        # num_ctx must still be present alongside the new keys.
        assert options.get("num_ctx") == 8192

    @patch("jarvis.llm.requests.post")
    def test_neither_key_present_when_unset(self, mock_post):
        mock_post.return_value = _make_resp()

        msgs = [{"role": "user", "content": "hi"}]
        chat_with_messages("http://localhost:11434", "gemma4:e2b", msgs)

        payload = _capture_payload(mock_post)
        options = payload.get("options") or {}
        assert "num_predict" not in options
        assert "temperature" not in options
        # Default behaviour: only num_ctx is set.
        assert options.get("num_ctx") == 8192

    @patch("jarvis.llm.requests.post")
    def test_explicit_none_omits_keys(self, mock_post):
        mock_post.return_value = _make_resp()

        msgs = [{"role": "user", "content": "hi"}]
        chat_with_messages(
            "http://localhost:11434",
            "gemma4:e2b",
            msgs,
            num_predict=None,
            temperature=None,
        )

        payload = _capture_payload(mock_post)
        options = payload.get("options") or {}
        assert "num_predict" not in options
        assert "temperature" not in options

    @patch("jarvis.llm.requests.post")
    def test_non_positive_num_predict_is_omitted(self, mock_post):
        """A num_predict of 0 (or negative) means 'no cap' — do not send it."""
        mock_post.return_value = _make_resp()

        msgs = [{"role": "user", "content": "hi"}]
        chat_with_messages(
            "http://localhost:11434",
            "gemma4:e2b",
            msgs,
            num_predict=0,
        )

        payload = _capture_payload(mock_post)
        options = payload.get("options") or {}
        assert "num_predict" not in options

    @patch("jarvis.llm.requests.post")
    def test_temperature_zero_is_forwarded(self, mock_post):
        """temperature=0.0 is a meaningful value (greedy) and must be sent."""
        mock_post.return_value = _make_resp()

        msgs = [{"role": "user", "content": "hi"}]
        chat_with_messages(
            "http://localhost:11434",
            "gemma4:e2b",
            msgs,
            temperature=0.0,
        )

        payload = _capture_payload(mock_post)
        options = payload.get("options") or {}
        assert options.get("temperature") == 0.0
