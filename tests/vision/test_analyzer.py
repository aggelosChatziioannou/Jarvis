"""Behaviour tests for vision.analyzer.

Covers Tesseract binary resolution (PATH → known install locations), OCR with
a bilingual EL+EN language string and graceful fallback, and that describe/
locate delegate to the injected vision-model client.
"""

from PIL import Image

import jarvis.vision.analyzer as an
from jarvis.vision.analyzer import (
    ScreenAnalyzer,
    locate_text_label,
    read_text,
    resolve_tesseract,
)


def _img():
    return Image.new("RGB", (200, 100), (255, 255, 255))


class _FakeClient:
    def __init__(self):
        self.calls = []

    def describe(self, image):
        self.calls.append(("describe", image))
        return "a settings window"

    def locate(self, image, target):
        self.calls.append(("locate", target))
        return (120, 40)


# --- tesseract resolution ----------------------------------------------

def test_resolve_prefers_path(monkeypatch):
    monkeypatch.setattr(an.shutil, "which", lambda name: r"C:\on\path\tesseract.exe")
    assert resolve_tesseract() == r"C:\on\path\tesseract.exe"


def test_resolve_falls_back_to_known_install_location(monkeypatch):
    monkeypatch.setattr(an.shutil, "which", lambda name: None)
    known = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    monkeypatch.setattr(an.os.path, "isfile", lambda p: p == known)
    assert resolve_tesseract() == known


def test_resolve_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(an.shutil, "which", lambda name: None)
    monkeypatch.setattr(an.os.path, "isfile", lambda p: False)
    assert resolve_tesseract() is None


# --- OCR ----------------------------------------------------------------

def test_read_text_uses_bilingual_langs_and_strips(monkeypatch):
    seen = {}

    def fake_ocr(image, lang):
        seen["lang"] = lang
        return "  Γειά σου world  \n"

    monkeypatch.setattr(an, "resolve_tesseract", lambda: r"C:\t\tesseract.exe")
    monkeypatch.setattr(an.pytesseract, "image_to_string", fake_ocr)
    out = read_text(_img())
    assert out == "Γειά σου world"
    assert seen["lang"] == "eng+ell"   # English + Greek by default


def test_read_text_falls_back_to_english_when_greek_pack_missing(monkeypatch):
    calls = []

    def fake_ocr(image, lang):
        calls.append(lang)
        if lang == "eng+ell":
            raise RuntimeError("Failed loading language 'ell'")
        return "english only"

    monkeypatch.setattr(an, "resolve_tesseract", lambda: r"C:\t\tesseract.exe")
    monkeypatch.setattr(an.pytesseract, "image_to_string", fake_ocr)
    assert read_text(_img()) == "english only"
    assert calls == ["eng+ell", "eng"]


def test_read_text_returns_empty_on_total_failure(monkeypatch):
    def boom(image, lang):
        raise RuntimeError("no binary")

    monkeypatch.setattr(an, "resolve_tesseract", lambda: None)
    monkeypatch.setattr(an.pytesseract, "image_to_string", boom)
    assert read_text(_img()) == ""


# --- analyzer facade ----------------------------------------------------

def test_analyzer_describe_delegates_to_client():
    client = _FakeClient()
    analyzer = ScreenAnalyzer(client)
    assert analyzer.describe(_img()) == "a settings window"
    assert client.calls[0][0] == "describe"


def test_analyzer_locate_delegates_to_client():
    client = _FakeClient()
    analyzer = ScreenAnalyzer(client)
    assert analyzer.locate(_img(), "OK button") == (120, 40)
    assert client.calls[0] == ("locate", "OK button")


# --- Tesseract word-box locate (primary locate path) --------------------

def _fake_data(words):
    """Build an image_to_data-style DICT from word dicts."""
    keys = ["text", "left", "top", "width", "height", "conf",
            "block_num", "par_num", "line_num"]
    d = {k: [] for k in keys}
    for w in words:
        d["text"].append(w["text"])
        d["left"].append(w["left"])
        d["top"].append(w["top"])
        d["width"].append(w["width"])
        d["height"].append(w["height"])
        d["conf"].append(w.get("conf", 96))
        d["block_num"].append(w.get("block", 1))
        d["par_num"].append(w.get("par", 1))
        d["line_num"].append(w.get("line", 1))
    return d


def _patch_ocr(monkeypatch, words):
    monkeypatch.setattr(an, "resolve_tesseract", lambda: r"C:\t\tesseract.exe")
    monkeypatch.setattr(an.pytesseract, "image_to_data", lambda *a, **k: _fake_data(words))


def test_locate_text_label_single_word(monkeypatch):
    _patch_ocr(monkeypatch, [{"text": "Cancel", "left": 120, "top": 120, "width": 140, "height": 30}])
    assert locate_text_label(_img(), "Cancel") == (190, 135)


def test_locate_text_label_ignores_generic_extra_token(monkeypatch):
    # "button" has no OCR match but the distinctive "Cancel" anchors the result.
    _patch_ocr(monkeypatch, [{"text": "Cancel", "left": 120, "top": 120, "width": 140, "height": 30}])
    assert locate_text_label(_img(), "Cancel button") == (190, 135)


def test_locate_text_label_greek(monkeypatch):
    _patch_ocr(monkeypatch, [{"text": "Αποθήκευση", "left": 150, "top": 300, "width": 200, "height": 32}])
    assert locate_text_label(_img(), "Αποθήκευση") == (250, 316)


def test_locate_text_label_fuzzy_typo(monkeypatch):
    _patch_ocr(monkeypatch, [{"text": "Cancel", "left": 120, "top": 120, "width": 140, "height": 30}])
    # OCR/user typo tolerance.
    assert locate_text_label(_img(), "Cancl") == (190, 135)


def test_locate_text_label_multiword_unions_box(monkeypatch):
    _patch_ocr(monkeypatch, [
        {"text": "Save", "left": 100, "top": 100, "width": 60, "height": 30, "line": 1},
        {"text": "As", "left": 170, "top": 100, "width": 40, "height": 30, "line": 1},
    ])
    # Union of both word boxes: x 100..210, y 100..130 -> centre (155,115).
    assert locate_text_label(_img(), "Save As") == (155, 115)


def test_locate_text_label_returns_none_when_no_match(monkeypatch):
    _patch_ocr(monkeypatch, [{"text": "Cancel", "left": 120, "top": 120, "width": 140, "height": 30}])
    assert locate_text_label(_img(), "Xyzzy") is None


def test_locate_text_label_filters_low_confidence(monkeypatch):
    _patch_ocr(monkeypatch, [{"text": "Cancel", "left": 120, "top": 120, "width": 140, "height": 30, "conf": 10}])
    assert locate_text_label(_img(), "Cancel") is None
