"""Session manifest (JSONL) — the ground truth of what was recorded.

One row per saved take: which prompt, the EXACT text spoken, distance, noise
condition, level stats. This is what makes the dataset auditable ("what was I
reading in clip 0142?") and what drives resume and the trainer export.
"""

from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path

MANIFEST_NAME = "manifest.jsonl"


def append_row(manifest_path: Path, row: dict) -> None:
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_rows(manifest_path: Path) -> list[dict]:
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return []
    rows = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def completed_prompt_ids(rows: list[dict]) -> set[str]:
    """A prompt is complete once ANY take was saved for it (re-takes replace
    quality, not coverage)."""
    return {r["prompt_id"] for r in rows if r.get("file")}


def _is_trainer_wav(path: Path) -> bool:
    try:
        with wave.open(str(path)) as w:
            return (
                w.getframerate() == 16000
                and w.getnchannels() == 1
                and w.getsampwidth() == 2
                and w.getnframes() > 0
            )
    except Exception:
        return False


def export_positives_for_trainer(session_dir: Path, out_dir: Path) -> int:
    """Bucket positive takes into ``out_dir/<distance>_<noise>/`` for the
    injector (which treats each subfolder as a holdout/weighting bucket).

    Idempotent by construction: deterministic filenames, overwrite on re-run.
    Negatives/traps/beds are NEVER exported here — they feed the negative side
    of training via a separate path.
    """
    session_dir = Path(session_dir)
    out_dir = Path(out_dir)
    rows = load_rows(session_dir / MANIFEST_NAME)
    exported = 0
    for r in rows:
        if r.get("label") != "positive" or not r.get("file"):
            continue
        src = session_dir / r["file"]
        if not _is_trainer_wav(src):
            print(f"   ⚠️  skipping non-trainer-format clip: {src.name}")
            continue
        bucket = f"{r.get('distance') or 'na'}_{r.get('noise') or 'na'}"
        dst = out_dir / bucket / f"{r['prompt_id']}__t{r.get('take', 1)}.wav"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        exported += 1
    return exported
