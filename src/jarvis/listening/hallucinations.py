"""
🛑 Shared Whisper-hallucination blocklist.

Whisper (and Whisper-derived STT backends) emit a small, stable set of
non-speech "hallucinations" on silence or echo: YouTube-subtitle residues
("subtitles by amara.org"), outro fillers ("thanks for watching"), and lone
filler words ("okay", "so", "um"). The Calm-Whisper paper (Interspeech 2025)
traced >75% of these to three decoder attention heads.

This module is the single source of truth for that blocklist so two
independent consumers can share it WITHOUT importing each other:

  - ``listening/listener.py`` rejects these at the STT boundary so they never
    reach the assistant pipeline.
  - ``memory/graph_ops.py`` drops them at write time so a residue that slips
    through STT (e.g. via a cloud backend) can never be stored as an enduring
    "fact".

``looks_like_hallucination`` is a pure function: no listener state, no audio,
just text in -> bool out. This keeps it cheap to call from the memory
write-path and trivially unit-testable.

NOTE: matching is whole-utterance for the exact set (lone filler words like
"you"/"so" appear in normal speech, so they only count when they ARE the
entire utterance) and substring for the distinctive-phrase set (those phrases
never occur inside legitimate speech).
"""

from __future__ import annotations

import re


# Whole-utterance whisper hallucinations: matched ONLY when the entire
# transcript (after punctuation strip) equals one of these. We use
# exact-match here because words like "you" / "thanks" / "bye"
# appear in normal speech and we must not blacklist them globally.
HALLUCINATION_EXACT = frozenset({
    "thank you",
    "thanks",
    "you",
    "bye",
    "bye bye",
    "goodbye",
    "subscribe",
    # Greek lone-word silence outputs
    "ευχαριστώ",
    "ευχαριστω",
    "ευχαριστώ πολύ",
    "ευχαριστω πολυ",
    "γεια σας",
    "καλή συνέχεια",
    "καλη συνεχεια",
    # Calm-Whisper (Interspeech 2025) identified the "crazy heads"
    # (decoder attention heads #1, #6, #11) that account for >75% of
    # Whisper's non-speech hallucinations. The most common outputs are
    # English filler / outro words. Drop them only when they appear as
    # the ENTIRE utterance (length ≤ 3 words after punctuation strip);
    # an embedded "okay" inside a real sentence is still legitimate.
    "so",
    "okay",
    "ok",
    "good",
    "take care",
    "alright",
    "all right",
    "um",
    "uh",
    "hmm",
    "mm",
    "mhm",
    # Pure punctuation / whitespace
    ".", "..", "...", "?", "!",
})

# Substring blacklist: any utterance containing one of these is rejected.
# These are distinctive enough that legitimate speech never contains them.
HALLUCINATION_SUBSTRINGS = (
    "thank you for watching",
    "thanks for watching",
    "like and subscribe",
    "please subscribe",
    "don't forget to subscribe",
    "subtitles by the amara.org community",
    "subtitles by amara.org",
    "subtitles by",
    "transcription by",
    "transcribed by",
    "captions by",
    "amara.org community",
    "amara.org",
    "see you in the next",
    "see you next time",
    # Sound-event markers
    "♪",
    "[music]",
    "[applause]",
    "[laughter]",
    "[silence]",
    # Our own initial_prompt echoes
    "the user mixes english and greek",
    # Greek YouTube-subtitle residues
    # AUTHORWAVE is a Greek subtitling collective whose stamp Whisper
    # learned during training; it leaks onto silence regardless of input.
    "υπότιτλοι authorwave",
    "authorwave",
    "ευχαριστώ που με παρακολουθήσατε",
    "ευχαριστω που με παρακολουθησατε",
    "εγγραφείτε στο κανάλι",
    "εγγραφειτε στο καναλι",
    "μην ξεχάσετε να κάνετε εγγραφή",
)


def looks_like_hallucination(text: str) -> bool:
    """Return True for Whisper's known silence/echo hallucinations.

    Triggers when:
      - The utterance contains ≤1 alphanumeric character (just punctuation).
      - The whole utterance exactly matches a known noise word/phrase.
      - The utterance contains any distinctive YouTube-subtitle substring.

    Pure function: text in, bool out. No listener/audio state, so both the
    STT boundary and the memory write-path can call it.
    """
    if not text:
        return False
    stripped = text.strip()
    # Pure punctuation / whitespace
    bare = re.sub(r"[^\wͰ-Ͽἀ-῿]", "", stripped, flags=re.UNICODE)
    if len(bare) <= 1:
        return True
    norm = stripped.lower().rstrip("!.?,;: \t\n")
    if norm in HALLUCINATION_EXACT:
        return True
    for phrase in HALLUCINATION_SUBSTRINGS:
        if phrase in norm:
            return True
    return False
