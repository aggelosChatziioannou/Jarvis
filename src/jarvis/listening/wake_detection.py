"""Wake word and stop command detection logic."""

from typing import List, Optional, Tuple
import difflib

from ..debug import debug_log


def find_wake_word_position(
    text_lower: str,
    wake_word: str,
    aliases: List[str],
    fuzzy_ratio: float = 0.78,
) -> Tuple[int, int]:
    """Return (start_index, matched_length) of the FIRST wake-word occurrence.

    Returns (-1, 0) if not found. Considers exact substring match against
    wake_word and aliases first (earliest hit wins, ties broken by longer
    alias to avoid splitting "jarvis" inside "yarvison"); then falls back to
    token-by-token fuzzy match.

    Used by the strict-prefix rule: anything before the returned position is
    discarded so the intent judge only sees text the user spoke AFTER
    addressing the assistant.
    """
    if not text_lower:
        return (-1, 0)

    # Longer aliases first so e.g. "hey jarvis" beats "jarvis" when both match
    # at the same index — gives a cleaner discard.
    all_aliases = sorted(set(aliases) | {wake_word}, key=len, reverse=True)

    # 1. Exact substring — earliest match wins (ties broken by alias length).
    best: Tuple[int, int] = (-1, 0)
    for alias in all_aliases:
        if not alias:
            continue
        idx = text_lower.find(alias)
        if idx >= 0 and (best[0] == -1 or idx < best[0]):
            best = (idx, len(alias))
    if best[0] >= 0:
        return best

    # 2. Fuzzy fallback: walk tokens, return position of first token that
    # matches any alias above the ratio threshold.
    pos = 0
    try:
        for token in text_lower.split(" "):
            stripped = token.strip(".,!?;:()[]{}\"'`).-_/")
            if stripped:
                for alias in all_aliases:
                    if difflib.SequenceMatcher(a=alias, b=stripped).ratio() >= fuzzy_ratio:
                        return (pos, len(token))
            pos += len(token) + 1  # +1 for the space separator
    except Exception:
        pass

    return (-1, 0)


def is_wake_word_detected(text_lower: str, wake_word: str, aliases: List[str], fuzzy_ratio: float = 0.78) -> bool:
    """
    Check if text contains wake word using exact and fuzzy matching.
    
    Args:
        text_lower: Lowercase text to check
        wake_word: Primary wake word
        aliases: List of wake word aliases
        fuzzy_ratio: Threshold for fuzzy matching (0.0-1.0)
    
    Returns:
        True if wake word detected
    """
    if not text_lower or not text_lower.strip():
        return False
    
    # Combine wake word and aliases
    all_aliases = set(aliases) | {wake_word}
    
    # Check exact match first
    if wake_word in text_lower:
        return True
    
    # Check aliases exact match
    for alias in aliases:
        if alias in text_lower:
            return True
    
    # Fuzzy matching for close variations
    try:
        heard_tokens = [t.strip(".,!?;:()[]{}\"'`).-_/") for t in text_lower.split() if t.strip()]
        for token in heard_tokens:
            for alias in all_aliases:
                ratio = difflib.SequenceMatcher(a=alias, b=token).ratio()
                if ratio >= fuzzy_ratio:
                    debug_log(f"wake word fuzzy match: '{alias}' ~ '{token}' (ratio: {ratio:.3f})", "wake")
                    return True
    except Exception:
        pass
    
    return False


def extract_query_after_wake(text_lower: str, wake_word: str, aliases: List[str]) -> str:
    """
    Extract the query portion after removing wake word.
    
    Args:
        text_lower: Lowercase text containing wake word
        wake_word: Primary wake word
        aliases: List of wake word aliases
    
    Returns:
        Query text with wake word removed
    """
    if not text_lower:
        return ""
    
    all_aliases = set(aliases) | {wake_word}
    fragment = text_lower
    
    # Remove all aliases from the text
    for alias in all_aliases:
        fragment = fragment.replace(alias, " ")
    
    # Clean up punctuation that might be left after wake word removal
    fragment = fragment.strip().lstrip(",.!?;:")
    fragment = fragment.strip()
    
    return fragment if fragment else ""


def is_stop_command(text_lower: str, stop_commands: List[str], fuzzy_ratio: float = 0.8) -> bool:
    """
    Check if text contains a stop command.
    
    Args:
        text_lower: Lowercase text to check
        stop_commands: List of stop command phrases
        fuzzy_ratio: Threshold for fuzzy matching short inputs
    
    Returns:
        True if stop command detected
    """
    if not text_lower or not text_lower.strip():
        return False
    
    # Check for exact matches
    detected_commands = []
    for cmd in stop_commands:
        if cmd in text_lower:
            detected_commands.append(cmd)
    
    # Check fuzzy matches for short inputs (2 words or less)
    if len(text_lower.split()) <= 2:
        try:
            for word in text_lower.split():
                for cmd in stop_commands:
                    ratio = difflib.SequenceMatcher(a=cmd, b=word).ratio()
                    if ratio >= fuzzy_ratio:
                        detected_commands.append(f"{cmd}~{word}")
        except Exception:
            pass
    
    if detected_commands:
        debug_log(f"stop command detected: {detected_commands[0]} in '{text_lower}'", "voice")
        return True
    
    return False
