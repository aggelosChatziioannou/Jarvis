"""Tests for the sticky language lock.

When the user speaks Greek 2 of the last 3 utterances, the next Whisper
transcribe call should hint `language="el"` instead of auto-detecting. This
saves the re-transcribe loop AND prevents hybrid EL/EN phonetic confusion
(the `καιρός → κύριος` failure case).
"""
from __future__ import annotations

import pytest

from jarvis.listening.language_lock import LanguageLock


def test_initial_state_returns_none_for_auto_detect():
    """No history yet → caller should fall back to auto-detect (language=None)."""
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    assert lock.suggest() is None


def test_single_observation_not_enough_for_lock():
    """One utterance is not enough evidence — still auto-detect."""
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("el")
    assert lock.suggest() is None


def test_two_consecutive_greek_locks_to_greek():
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("el")
    lock.record("el")
    assert lock.suggest() == "el"


def test_two_consecutive_english_locks_to_english():
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("en")
    lock.record("en")
    assert lock.suggest() == "en"


def test_majority_vote_in_3_utterance_window():
    """2 EL + 1 EN should lock to EL — majority wins."""
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("el")
    lock.record("en")
    lock.record("el")
    assert lock.suggest() == "el"


def test_evenly_split_does_not_lock():
    """1 EL + 1 EN — no majority → return None to let auto-detect take over."""
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("el")
    lock.record("en")
    assert lock.suggest() is None


def test_disallowed_language_observations_are_ignored():
    """Whisper sometimes returns 'cy' (Welsh) by mistake — those don't count toward consensus."""
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("cy")
    lock.record("cy")
    lock.record("cy")
    # No allowed languages observed → fall back to auto-detect
    assert lock.suggest() is None


def test_window_slides_with_history_size():
    """Oldest observation drops off when window fills up."""
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("el")
    lock.record("el")
    # At this point: lock should suggest el
    assert lock.suggest() == "el"
    # Three EN in a row should flip the lock once the window slides
    lock.record("en")
    lock.record("en")
    lock.record("en")
    assert lock.suggest() == "en"


def test_none_observations_skipped():
    """If Whisper returns no detected language, that recording is a no-op."""
    lock = LanguageLock(history_size=3, min_agreement=2, allowed=("el", "en"))
    lock.record("el")
    lock.record(None)
    lock.record(None)
    # Only one Greek observation — still no lock
    assert lock.suggest() is None
