"""Untrusted-content fence hardening.

Several tools wrap untrusted text (fetched web pages, user-dictated meal text,
stored facts) between ``<<<BEGIN UNTRUSTED ...>>>`` / ``<<<END UNTRUSTED ...>>>``
sentinel markers and instruct the model to treat everything inside as data, not
instructions. If the untrusted content itself contains the literal END marker,
it can 'close' the fence early so injected instructions appear OUTSIDE the
boundary to a small model. ``strip_fence_markers`` neutralises any embedded
sentinel before the content is wrapped, preserving the surrounding text as
inert data.
"""
from __future__ import annotations

import re

# Match any ``<<< BEGIN|END ... >>>`` sentinel, case-insensitive, regardless of
# the exact label after BEGIN/END (UNTRUSTED WEB EXTRACT, MEAL TEXT, etc.).
_FENCE_MARKER_RE = re.compile(r"<<<\s*(?:BEGIN|END)\b[^>]*>>>", re.IGNORECASE)


def strip_fence_markers(text):
    """Remove any embedded untrusted-fence sentinel markers from ``text``.

    Returns ``text`` unchanged when it is falsy/non-string or contains no
    marker. Ordinary text (including stray ``<<<`` or ``>>>`` that is not a
    full sentinel) is left intact.
    """
    if not text or not isinstance(text, str):
        return text
    return _FENCE_MARKER_RE.sub("", text)
