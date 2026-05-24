"""Tests for the Calm-Whisper hallucination blocklist additions.

The Calm-Whisper paper (Interspeech 2025) identified that 3 of 20 decoder
attention heads emit specific English filler words on non-speech audio. We
extended `_HALLUCINATION_EXACT` to include these. Critical: they must drop
only when they are the ENTIRE utterance (one or two words), not when
embedded in real speech.
"""
from __future__ import annotations

import pytest

from jarvis.listening.listener import VoiceListener


class _Sentinel:
    _HALLUCINATION_EXACT = VoiceListener._HALLUCINATION_EXACT
    _HALLUCINATION_SUBSTRINGS = VoiceListener._HALLUCINATION_SUBSTRINGS


_check = VoiceListener._is_youtube_hallucination.__get__(_Sentinel())


# Calm-Whisper filler words — must be filtered when they appear alone.
@pytest.mark.parametrize("text", [
    "so",
    "So",
    "So.",
    "Okay",
    "okay.",
    "OK",
    "ok.",
    "Good",
    "Take care",
    "alright",
    "All right",
    "um",
    "uh",
    "Hmm",
    "Mm",
])
def test_calm_whisper_fillers_filtered_when_alone(text):
    assert _check(text) is True, f"{text!r} should be filtered as a Calm-Whisper hallucination"


# Real speech that includes these words as substrings — must pass through.
@pytest.mark.parametrize("text", [
    "so what's the weather today",
    "okay let me check",
    "good morning Jarvis",
    "alright tell me the time",
    "um can you do something",
    "I want to take care of this",
    "is everything alright with the schedule",
])
def test_calm_whisper_fillers_pass_when_embedded(text):
    assert _check(text) is False, f"{text!r} is real speech and must NOT be filtered"
