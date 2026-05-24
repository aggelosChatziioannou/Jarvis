"""TTS output cache: avoid regenerating audio for repeated phrases.

Chatterbox neural voice synthesis takes 5-20s per utterance. For phrases
the assistant says often ("Done.", "Sure.", "Paused.", a stock greeting),
we hash the text + the voice prompt + key generation parameters and reuse
the previously-generated audio when the same combination reappears.

Cache layout:
    <data_dir>/tts_cache/
        index.json                   # text -> {key, params}
        <key>.wav                    # cached audio per entry

Cache key includes the audio_prompt_path (voice clone source), so changing
the cloned voice does not return audio in the old voice.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Optional


def _data_dir() -> Path:
    """Return Jarvis data dir (~/.local/share/jarvis on all platforms)."""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return home / ".local" / "share" / "jarvis"


class TTSCache:
    """Disk-backed cache of synthesized audio keyed by (text, voice, params)."""

    def __init__(self, subdir: str = "tts_cache") -> None:
        self.dir = _data_dir() / subdir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.dir / "index.json"
        self._index: dict[str, dict[str, Any]] = self._load_index()
        self._lock = threading.Lock()

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self._index_path.exists():
            return {}
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_index(self) -> None:
        try:
            tmp = self._index_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
            tmp.replace(self._index_path)
        except OSError:
            pass

    @staticmethod
    def make_key(text: str, voice_prompt: Optional[str], exaggeration: float, cfg_weight: float) -> str:
        """Stable hash combining text + voice settings."""
        material = "|".join([
            (text or "").strip(),
            str(voice_prompt or ""),
            f"{exaggeration:.3f}",
            f"{cfg_weight:.3f}",
        ])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    def lookup(
        self,
        text: str,
        voice_prompt: Optional[str],
        exaggeration: float,
        cfg_weight: float,
    ) -> Optional[Path]:
        """Return cached wav path if available + valid, else None."""
        key = self.make_key(text, voice_prompt, exaggeration, cfg_weight)
        with self._lock:
            entry = self._index.get(key)
            if entry is None:
                return None
            wav_path = self.dir / entry["file"]
            if not wav_path.exists():
                self._index.pop(key, None)
                self._save_index()
                return None
            return wav_path

    def store(
        self,
        text: str,
        voice_prompt: Optional[str],
        exaggeration: float,
        cfg_weight: float,
        source_wav: Path,
    ) -> Path:
        """Persist a generated audio file into the cache. Returns the cached path."""
        key = self.make_key(text, voice_prompt, exaggeration, cfg_weight)
        cached_name = f"{key}.wav"
        target = self.dir / cached_name
        try:
            shutil.copy(source_wav, target)
        except OSError:
            return source_wav
        with self._lock:
            self._index[key] = {
                "text": (text or "").strip()[:200],
                "file": cached_name,
            }
            self._save_index()
        return target

    def size_info(self) -> tuple[int, int]:
        """Return (entry_count, total_bytes)."""
        with self._lock:
            entries = len(self._index)
        total = 0
        for p in self.dir.glob("*.wav"):
            try:
                total += p.stat().st_size
            except OSError:
                continue
        return entries, total


_singleton: Optional[TTSCache] = None
_singleton_lock = threading.Lock()


def get_cache() -> TTSCache:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = TTSCache()
        return _singleton
