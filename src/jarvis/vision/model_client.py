"""Client for a local Ollama vision model (default: moondream).

Owns the vision domain's request shape: PIL Image → base64 PNG → multimodal
Ollama call (via ``jarvis.llm.call_vision_model``) → text, plus robust parsing
of free-text coordinate replies into pixel points relative to the image.

The model is used for *understanding* (describe) and *locating* (find element →
coords). Text transcription is Tesseract's job (see ``analyzer.read_text``).
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Optional, Tuple

from ..debug import debug_log
from ..llm import call_vision_model

# Internal instructions to the vision model. These are model-facing prompts,
# not user-language matching, so a fixed English instruction is fine; OCR/Greek
# is handled separately by Tesseract. Default model is qwen2.5vl:3b (moondream
# was dropped — it returns empty for every grounding prompt via Ollama).
DESCRIBE_PROMPT = (
    "Describe what is shown on this screen. List the main windows, applications "
    "and key UI elements (buttons, fields, menus) concisely."
)
LOCATE_PROMPT_TEMPLATE = (
    "Locate the UI element described as: {target}. "
    "Output ONLY its bounding box as JSON in the form "
    '{{"bbox_2d": [x1, y1, x2, y2]}} using pixel coordinates of this image. '
    "If it is not visible, output: none"
)

_COORD_PAIR = re.compile(r"(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)")
# Numbers not embedded in identifiers — so the "2" in "bbox_2d" is never grabbed.
_ANY_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def parse_coordinates(
    text: Optional[str],
    img_size: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int]]:
    """Extract a centre (x, y) pixel pair from a free-text model reply.

    Handles ``"1450,450"``, ``"(1450, 450)"``, ``"1450 450"`` and prose like
    ``"at 1450,450 on monitor 1"`` (first pair wins). If both values are
    normalised floats in [0, 1] and ``img_size`` is known, they are scaled to
    pixels. Returns None when no usable pair is present.
    """
    if not text:
        return None
    match = _COORD_PAIR.search(text)
    if match:
        xs, ys = match.group(1), match.group(2)
    else:
        nums = _ANY_NUMBER.findall(text)
        if len(nums) < 2:
            return None
        xs, ys = nums[0], nums[1]
    try:
        x = float(xs)
        y = float(ys)
    except ValueError:
        return None
    is_float = ("." in xs) or ("." in ys)
    if img_size and is_float and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        w, h = img_size
        return (int(round(x * w)), int(round(y * h)))
    return (int(round(x)), int(round(y)))


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[A-Za-z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    return t


def _coerce_box_or_point(obj):
    """From parsed JSON, return a (x, y) point or box-centre, else None."""
    if isinstance(obj, dict):
        for key in ("bbox_2d", "bbox", "box"):
            b = obj.get(key)
            if isinstance(b, (list, tuple)) and len(b) >= 4:
                return ((float(b[0]) + float(b[2])) / 2, (float(b[1]) + float(b[3])) / 2)
        if "x" in obj and "y" in obj:
            try:
                return (float(obj["x"]), float(obj["y"]))
            except (TypeError, ValueError):
                return None
        if "point" in obj and isinstance(obj["point"], (list, tuple)) and len(obj["point"]) >= 2:
            p = obj["point"]
            return (float(p[0]), float(p[1]))
    if isinstance(obj, list):
        nums = [v for v in obj if isinstance(v, (int, float))]
        if len(nums) >= 4:
            return ((float(nums[0]) + float(nums[2])) / 2, (float(nums[1]) + float(nums[3])) / 2)
        if obj and isinstance(obj[0], dict):
            return _coerce_box_or_point(obj[0])
        if len(nums) >= 2:
            return (float(nums[0]), float(nums[1]))
    return None


def parse_point_or_box(
    text: Optional[str],
    img_size: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int]]:
    """Parse a grounding reply (qwen2.5vl emits ``{"bbox_2d":[...]}``,
    ``{"x":..,"y":..}``, bare lists, or prose) into a centre (x, y) pixel point.

    JSON-aware first (so the ``2`` in ``bbox_2d`` is never mistaken for a
    coordinate), with a regex fallback (4 numbers → box centre, 2 → point).
    """
    if not text:
        return None
    raw = _strip_fences(text)
    point = None
    try:
        point = _coerce_box_or_point(json.loads(raw))
    except Exception:
        point = None
    if point is None:
        nums = _ANY_NUMBER.findall(raw)
        if len(nums) >= 4:
            x1, y1, x2, y2 = (float(n) for n in nums[:4])
            point = ((x1 + x2) / 2, (y1 + y2) / 2)
        elif len(nums) >= 2:
            point = (float(nums[0]), float(nums[1]))
    if point is None:
        return None
    x, y = point
    if (
        img_size
        and 0.0 <= x <= 1.0
        and 0.0 <= y <= 1.0
        and not (float(x).is_integer() and float(y).is_integer())
    ):
        w, h = img_size
        return (int(round(x * w)), int(round(y * h)))
    return (int(x), int(y))


def _encode_image_b64(image, fmt: str = "PNG") -> str:
    """Encode a PIL Image to a base64 string in-memory (no disk)."""
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class VisionModelClient:
    """Thin wrapper around a local Ollama vision model."""

    def __init__(
        self,
        base_url: str,
        model: str = "qwen2.5vl:3b",
        timeout_sec: float = 30.0,
        keep_alive: Optional[str] = "5m",
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout_sec = timeout_sec
        # Short keep_alive by default: vision is bursty, so the model loads on
        # demand and self-evicts, returning VRAM to the resident chat model.
        self.keep_alive = keep_alive

    def analyze(self, image, prompt: str) -> Optional[str]:
        """Send an image + prompt to the vision model; return text or None."""
        img_b64 = _encode_image_b64(image)
        debug_log(f"model_client: analyze model={self.model} prompt={prompt[:48]!r}", "vision")
        return call_vision_model(
            base_url=self.base_url,
            model=self.model,
            prompt=prompt,
            images=[img_b64],
            timeout_sec=self.timeout_sec,
            keep_alive=self.keep_alive,
        )

    def describe(self, image) -> Optional[str]:
        return self.analyze(image, DESCRIBE_PROMPT)

    def locate(self, image, target: str) -> Optional[Tuple[int, int]]:
        """Return the centre (x, y) of ``target`` relative to the image, or None.

        Used as the *fallback* locate path (icons / coloured buttons) when
        Tesseract word-box matching finds no text label — see vision_engine.
        """
        prompt = LOCATE_PROMPT_TEMPLATE.format(target=target)
        text = self.analyze(image, prompt)
        coords = parse_point_or_box(text, img_size=getattr(image, "size", None))
        debug_log(f"model_client: ground {target!r} -> {coords}", "vision")
        return coords

    # Semantic alias used by the vision engine's fallback chain.
    ground = locate
