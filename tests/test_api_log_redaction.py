"""Privacy: the Live Logs feed must not store raw secrets/PII.

Every daemon print is teed into an in-memory buffer served over the
unauthenticated GET /api/logs and the SSE stream. Transcript/reply prints and
always-on error lines could carry emails, card numbers, passwords or tokens
in clear text. We scrub secrets before they reach the buffer while keeping the
ordinary transcript readable for debugging.
"""

import io

from src.jarvis.api_server import _StdoutMirror, _log_buffer


def test_stdout_mirror_scrubs_email_and_card():
    _log_buffer.clear()
    mirror = _StdoutMirror(io.StringIO())
    mirror.write('📝 Heard: "email me at alice@example.com, card 4111 1111 1111 1111"\n')
    assert _log_buffer, "expected a log entry"
    msg = _log_buffer[-1]["message"]
    assert "alice@example.com" not in msg
    assert "4111 1111 1111 1111" not in msg
    assert "[REDACTED_EMAIL]" in msg


def test_stdout_mirror_scrubs_keyword_credentials():
    _log_buffer.clear()
    mirror = _StdoutMirror(io.StringIO())
    mirror.write("debug: password=hunter2 secret=topsecretvalue\n")
    msg = _log_buffer[-1]["message"]
    assert "hunter2" not in msg
    assert "topsecretvalue" not in msg
    assert "[REDACTED]" in msg


def test_stdout_mirror_keeps_ordinary_transcript_readable():
    _log_buffer.clear()
    mirror = _StdoutMirror(io.StringIO())
    mirror.write('📝 Heard: "what is the weather in Thessaloniki"\n')
    msg = _log_buffer[-1]["message"]
    assert "weather in Thessaloniki" in msg
