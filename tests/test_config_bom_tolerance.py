"""A UTF-8 BOM on config.json must never read as a wiped config.

Live failure (2026-06-12): the config was edited externally with PowerShell
5.1's ``Out-File -Encoding utf8`` which writes a BOM. ``json.load`` over plain
``encoding="utf-8"`` raises on the BOM, ``_load_json`` swallowed it into ``{}``
(zero user keys), and config_safety's wipe detector silently restored a
4-hour-old backup ON EVERY BOOT — the user's backend switch and wake-model
upgrade kept "reverting by themselves". ``utf-8-sig`` reads BOTH BOM'd and
clean files.
"""

import json

import pytest

from jarvis.config import _load_json
from jarvis.config_safety import _load_json_safe

pytestmark = pytest.mark.unit

_CFG = {"stt_backend": "wispr", "wispr_wake_threshold": 0.45,
        "chat_model": "m", "wake_word": "jarvis",
        "a": 1, "b": 2, "c": 3, "d": 4, "e": 5}


def _write_bom(path, data):
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(data).encode("utf-8"))


class TestBomTolerance:
    def test_load_json_reads_bom_config(self, tmp_path):
        p = tmp_path / "config.json"
        _write_bom(p, _CFG)
        loaded = _load_json(p)
        assert loaded.get("stt_backend") == "wispr"
        assert len(loaded) == len(_CFG), "a BOM must not read as a wiped config"

    def test_safety_loader_reads_bom_config(self, tmp_path):
        p = tmp_path / "config.json"
        _write_bom(p, _CFG)
        loaded = _load_json_safe(p)
        assert loaded is not None
        assert loaded.get("wispr_wake_threshold") == 0.45

    def test_clean_utf8_still_reads(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps(_CFG), encoding="utf-8")
        assert _load_json(p).get("stt_backend") == "wispr"
        assert _load_json_safe(p) is not None
