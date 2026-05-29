"""Behaviour tests for vision.model_client.

The Ollama call is injected/monkeypatched so tests assert the request the
client builds and how it parses coordinates out of free-text model replies —
without a running model.
"""

import base64

from PIL import Image

import jarvis.vision.model_client as mc
from jarvis.vision.model_client import (
    VisionModelClient,
    parse_coordinates,
    parse_point_or_box,
)


def _img(w=800, h=600):
    return Image.new("RGB", (w, h), (10, 20, 30))


# --- coordinate parsing -------------------------------------------------

def test_parse_plain_comma_pair():
    assert parse_coordinates("1450,450") == (1450, 450)


def test_parse_pair_with_spaces_and_parens():
    assert parse_coordinates("The button centre is at (1450, 450).") == (1450, 450)


def test_parse_pair_space_separated():
    assert parse_coordinates("1450 450") == (1450, 450)


def test_parse_picks_first_pair_ignoring_trailing_numbers():
    assert parse_coordinates("at 1450,450 on monitor 1") == (1450, 450)


def test_parse_normalised_floats_scaled_to_image():
    # Some models emit 0..1 normalised coords; scale by image size.
    assert parse_coordinates("0.5, 0.25", img_size=(800, 600)) == (400, 150)


def test_parse_returns_none_when_no_pair():
    assert parse_coordinates("I cannot find it") is None
    assert parse_coordinates("") is None
    assert parse_coordinates(None) is None


# --- point-or-box parsing (qwen2.5vl returns several formats) ------------

def test_parse_box_json_to_centre():
    # The "2" inside "bbox_2d" must NOT pollute the coordinates.
    assert parse_point_or_box('{"bbox_2d": [920, 600, 1120, 680]}') == (1020, 640)


def test_parse_box_json_with_markdown_fence():
    assert parse_point_or_box('```json\n{"bbox_2d": [0, 0, 100, 50]}\n```') == (50, 25)


def test_parse_point_json():
    assert parse_point_or_box('{"x": 1198, "y": 566}') == (1198, 566)


def test_parse_bare_list_box():
    assert parse_point_or_box("[10, 20, 30, 40]") == (20, 30)


def test_parse_prose_point():
    assert parse_point_or_box("located at approximately (1200, 100)") == (1200, 100)


def test_parse_point_or_box_none():
    assert parse_point_or_box("none") is None
    assert parse_point_or_box("") is None


# --- request shape ------------------------------------------------------

def test_analyze_builds_multimodal_request(monkeypatch):
    seen = {}

    def fake_call(base_url, model, prompt, images, timeout_sec, keep_alive, **kw):
        seen.update(base_url=base_url, model=model, prompt=prompt,
                    images=images, keep_alive=keep_alive)
        return "a description"

    monkeypatch.setattr(mc, "call_vision_model", fake_call)
    client = VisionModelClient(base_url="http://x:11434", model="moondream", keep_alive="5m")
    out = client.analyze(_img(), "describe this")

    assert out == "a description"
    assert seen["model"] == "moondream"
    assert seen["prompt"] == "describe this"
    assert seen["keep_alive"] == "5m"
    # one base64 image string is sent
    assert isinstance(seen["images"], list) and len(seen["images"]) == 1
    # it must be valid base64 that decodes to PNG bytes
    raw = base64.b64decode(seen["images"][0])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_locate_returns_parsed_pixel_coordinates(monkeypatch):
    monkeypatch.setattr(mc, "call_vision_model",
                        lambda *a, **k: "the Submit button is at 1450, 450")
    client = VisionModelClient(base_url="http://x:11434", model="moondream")
    assert client.locate(_img(), "Submit button") == (1450, 450)


def test_locate_returns_none_when_model_cannot_find(monkeypatch):
    monkeypatch.setattr(mc, "call_vision_model", lambda *a, **k: "I don't see it")
    client = VisionModelClient(base_url="http://x:11434", model="moondream")
    assert client.locate(_img(), "nonexistent") is None


def test_analyze_handles_model_failure_gracefully(monkeypatch):
    monkeypatch.setattr(mc, "call_vision_model", lambda *a, **k: None)
    client = VisionModelClient(base_url="http://x:11434", model="moondream")
    assert client.analyze(_img(), "describe") is None
    assert client.locate(_img(), "thing") is None
