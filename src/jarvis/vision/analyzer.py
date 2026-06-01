"""High-level perception: describe + locate (vision model) and read_text (OCR).

Division of labour (per the approved plan):
  - **Tesseract** does exact bilingual text transcription (Greek + English).
    Small vision models are unreliable at Greek glyphs, so they are never used
    for the text path.
  - **Vision model** (qwen2.5vl:3b) does scene/UI description and element locating.

All methods return raw structures (text, coordinates) — never prose. The reply
engine's LLM loop + system prompt format the spoken answer.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Optional, Tuple

import pytesseract
from pytesseract import Output
from rapidfuzz import fuzz

from ..debug import debug_log

# Language-agnostic tokeniser (matches the recall_gate convention): \w+ with
# re.UNICODE so Greek/any-script labels tokenise correctly. Never hardcode
# language-specific keyword lists here.
_LABEL_TOKEN = re.compile(r"\w+", re.UNICODE)

# Known Tesseract install locations to try when it is not on PATH. The user's
# machine has it at the first entry (v5.5.0 with eng+ell packs).
_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
]

# English + Greek by default so bilingual screens transcribe correctly.
DEFAULT_OCR_LANGS = "eng+ell"


def resolve_tesseract() -> Optional[str]:
    """Locate the tesseract binary (PATH first, then known locations) and point
    pytesseract at it. Returns the path, or None if not found."""
    found = shutil.which("tesseract")
    if not found:
        for candidate in _TESSERACT_CANDIDATES:
            if candidate and os.path.isfile(candidate):
                found = candidate
                break
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        debug_log(f"analyzer: tesseract at {found}", "vision")
    else:
        debug_log("analyzer: tesseract binary not found", "error")
    return found


def read_text(image, langs: str = DEFAULT_OCR_LANGS) -> str:
    """OCR an image with Tesseract. Falls back to English if the multi-language
    pack is unavailable, and returns "" on total failure (fail-open)."""
    resolve_tesseract()
    try:
        text = pytesseract.image_to_string(image, lang=langs)
    except Exception as exc:
        debug_log(f"analyzer: OCR lang={langs} failed ({exc}); retrying eng", "vision")
        try:
            text = pytesseract.image_to_string(image, lang="eng")
        except Exception as exc2:
            debug_log(f"analyzer: OCR failed — {exc2}", "error")
            return ""
    return (text or "").strip()


def locate_text_label(
    image,
    target: str,
    langs: str = DEFAULT_OCR_LANGS,
    min_conf: float = 40.0,
    threshold: float = 80.0,
) -> Optional[Tuple[int, int]]:
    """Locate a text-labelled element by OCR word-box matching (deterministic).

    This is the *primary* locate path: fast (~0.2s), zero extra VRAM, bilingual.
    Each OCR word is fuzzy-matched (rapidfuzz) against the target's tokens; the
    best-matching word anchors the result, and matched words sharing its text
    line are unioned so a multi-word label ("Save As") yields a centre over the
    whole phrase. Returns the centre (x, y) relative to the image, or None.

    Language-agnostic by construction (``\\w+`` tokenisation + fuzzy ratio); it
    never relies on hardcoded language keywords. Falls back to icon/visual
    grounding (qwen2.5vl) live in the clickScreen tool when this returns None.
    """
    target_tokens = [t for t in _LABEL_TOKEN.findall(target.lower()) if t]
    if not target_tokens:
        return None
    resolve_tesseract()
    try:
        data = pytesseract.image_to_data(image, lang=langs, output_type=Output.DICT)
    except Exception as exc:
        debug_log(f"analyzer: locate image_to_data lang={langs} failed ({exc}); retrying eng", "vision")
        try:
            data = pytesseract.image_to_data(image, lang="eng", output_type=Output.DICT)
        except Exception as exc2:
            debug_log(f"analyzer: locate OCR failed — {exc2}", "error")
            return None

    texts = data.get("text", [])
    candidates = []  # (score, idx, line_key)
    for i in range(len(texts)):
        word = (texts[i] or "").strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < min_conf:
            continue
        word_l = word.lower()
        score = max(fuzz.ratio(word_l, tok) for tok in target_tokens)
        if score >= threshold:
            line_key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            candidates.append((score, i, line_key))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    _, _, best_line = candidates[0]
    matched = [c for c in candidates if c[2] == best_line]
    x0 = min(data["left"][i] for _, i, _ in matched)
    y0 = min(data["top"][i] for _, i, _ in matched)
    x1 = max(data["left"][i] + data["width"][i] for _, i, _ in matched)
    y1 = max(data["top"][i] + data["height"][i] for _, i, _ in matched)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    debug_log(
        f"analyzer: locate_text_label {target!r} -> ({cx},{cy}) score={candidates[0][0]:.0f}",
        "vision",
    )
    return (cx, cy)


class ScreenAnalyzer:
    """Facade that pairs a vision-model client with Tesseract OCR."""

    def __init__(self, client) -> None:
        self.client = client

    def describe(self, image) -> str:
        return self.client.describe(image) or ""

    def locate(self, image, target: str) -> Optional[Tuple[int, int]]:
        return self.client.locate(image, target)

    def read_text(self, image, langs: str = DEFAULT_OCR_LANGS) -> str:
        return read_text(image, langs)
