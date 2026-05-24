"""Sticky language lock for Whisper transcription.

Background: when Whisper is told `language=None` it auto-detects each
utterance independently. In a bilingual setup (50/50 Greek/English here) the
detector flickers between languages, occasionally landing on hybrid phonetic
decoding that produces failures like `καιρός` (weather) → `κύριος` (sir).

This helper records the language Whisper detected on each utterance and, once
a clear majority emerges in a small sliding window, returns that language as a
hint for the next transcribe call. When there's no consensus, it returns
`None` so the caller falls back to auto-detect.

The same `whisper_allowed_languages` setting the listener already respects
(default `["el", "en"]`) gates which detection observations are eligible — a
mis-detected "cy" (Welsh) or "pl" (Polish) never participates in the vote.
"""
from __future__ import annotations

from collections import Counter, deque
from typing import Iterable, Optional


class LanguageLock:
    """Rolling-window majority vote over recently detected languages."""

    def __init__(
        self,
        history_size: int = 3,
        min_agreement: int = 2,
        allowed: Iterable[str] = ("el", "en"),
    ) -> None:
        if history_size < 1:
            raise ValueError("history_size must be >= 1")
        if min_agreement < 1:
            raise ValueError("min_agreement must be >= 1")
        if min_agreement > history_size:
            raise ValueError("min_agreement cannot exceed history_size")

        self._history: deque[str] = deque(maxlen=history_size)
        self._min_agreement = min_agreement
        self._allowed = frozenset(allowed)

    def record(self, language: Optional[str]) -> None:
        """Record the language Whisper detected for an utterance.

        Observations of `None` or languages outside `allowed` are silently
        skipped — they neither populate the window nor evict older entries.
        """
        if language is None:
            return
        if language not in self._allowed:
            return
        self._history.append(language)

    def suggest(self) -> Optional[str]:
        """Return the language to hint to Whisper, or `None` for auto-detect.

        A language is suggested only when its count in the current window
        reaches `min_agreement`. Ties or insufficient data → `None`.
        """
        if not self._history:
            return None
        counts = Counter(self._history)
        top_lang, top_count = counts.most_common(1)[0]
        if top_count < self._min_agreement:
            return None
        return top_lang
