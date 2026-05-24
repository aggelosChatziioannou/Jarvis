"""Tests for the extended hallucination blacklist (Greek + English YouTube residues).

The blacklist lives on the `VoiceListener` class as `_HALLUCINATION_EXACT` and
`_HALLUCINATION_SUBSTRINGS`, consumed by `_is_youtube_hallucination`. We test
the matcher directly without instantiating the full listener.
"""
from __future__ import annotations

import pytest

from jarvis.listening.listener import VoiceListener


# Use the unbound method against a sentinel — _is_youtube_hallucination only
# reads class-level state so no __init__ run is needed.
class _Sentinel:
    _HALLUCINATION_EXACT = VoiceListener._HALLUCINATION_EXACT
    _HALLUCINATION_SUBSTRINGS = VoiceListener._HALLUCINATION_SUBSTRINGS


_check = VoiceListener._is_youtube_hallucination.__get__(_Sentinel())


# --- English residues (should be filtered) ----------------------------------

@pytest.mark.parametrize("text", [
    "thank you for watching",
    "Thanks for watching!",
    "subtitles by amara.org",
    "Subtitles by the Amara.org community",
    "♪",
    "[music]",
    "thank you",       # lone-word exact
    "you",
])
def test_english_residues_filtered(text):
    assert _check(text) is True


# --- Greek residues (the new additions) -------------------------------------

@pytest.mark.parametrize("text", [
    "Υπότιτλοι AUTHORWAVE",          # the canonical Greek silence hallucination from memory
    "υπότιτλοι authorwave",          # lowercase
    "  Υπότιτλοι AUTHORWAVE  ",      # whitespace tolerant
    "ευχαριστώ που με παρακολουθήσατε",
    "εγγραφείτε στο κανάλι",
    "ευχαριστώ",                     # lone-word
    "γεια σας",
])
def test_greek_residues_filtered(text):
    assert _check(text) is True, f"expected to filter: {text!r}"


# --- Legit speech that happens to share words (MUST PASS THROUGH) -----------

@pytest.mark.parametrize("text", [
    "thank you for the weather update Jarvis",   # contains 'thank you' but is a full request
    "thanks for that, can you also check tomorrow",
    "ευχαριστώ Jarvis πες μου τι ώρα είναι",     # Greek with 'ευχαριστώ' embedded
    "υπότιτλοι σε αυτή την ταινία",              # legit use of 'υπότιτλοι'
    "γεια σας Jarvis πώς είσαι",                # greeting + question
    "ποιος είναι ο καιρός στην Θεσσαλονίκη αύριο",  # the user's failure-case sentence
    "what's the weather today",
])
def test_legit_speech_passes_through(text):
    assert _check(text) is False, f"should NOT be filtered: {text!r}"


# --- Edge cases -------------------------------------------------------------

def test_empty_string_not_a_hallucination():
    assert _check("") is False


def test_pure_punctuation_filtered():
    """Whisper sometimes outputs just '.' or '...' on silence — must be filtered."""
    for text in (".", "..", "...", "?", "!"):
        assert _check(text) is True
