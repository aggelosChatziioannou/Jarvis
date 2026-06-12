"""Deterministic session plan for a full wake-word recording programme.

The plan is the single source of truth for WHAT gets recorded: every prompt has
a stable ``prompt_id`` so a session can stop at any point and resume days later
(the manifest says which prompt_ids are done; the plan supplies the rest).
Counts are config-driven — tests assert the mechanism (counts follow the
config), not hardcoded totals.

Phase order minimises user effort: everything quiet first (one mic trip per
distance), then per music condition one banner ("start Spotify at X volume")
covers positives + reading + ambience bed before the next condition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_SCRIPT_PATH = Path(__file__).parent / "reading_script.json"

WAKE_PHRASE = "Hey Jarvis"

# Greek style directions shown for positive takes — variety in pace/level is
# what makes the model robust to how the phrase sounds at 7 am vs mid-party.
STYLE_DIRECTIONS_EL = {
    "normal": "κανονικά — όπως το λες καθημερινά",
    "fast": "γρήγορα και πρόχειρα, σαν βιαστικός",
    "slow": "αργά και καθαρά",
    "loud": "δυνατά — σαν να φωνάζεις από άλλο δωμάτιο",
    "soft": "σιγανά και χαλαρά",
    "sleepy": "νυσταγμένα, όπως μόλις ξύπνησες",
    "question": "με απορία, σαν ερώτηση",
}

NOISE_BANNERS_EL = {
    "quiet": "🤫 Ησυχία στο δωμάτιο — χωρίς μουσική/TV.",
    "music_med": "🎵 Βάλε Spotify σε ΜΕΤΡΙΑ ένταση (όπως ακούς μουσική κανονικά).",
    "music_loud": "🔊 Δυνάμωσε το Spotify — ΔΥΝΑΤΗ ένταση (party level).",
    "speech_bg": "🗣️ Βάλε podcast ή ομιλία (π.χ. ειδήσεις/YouTube συνέντευξη) σε κανονική ένταση.",
}


@dataclass(frozen=True)
class PlanItem:
    prompt_id: str
    phase: str
    label: str            # positive | negative | trap | bed
    say_text: str         # what the user must say ("" for beds)
    instruction: str      # style/setup direction shown with the prompt
    distance: str         # "0.3m" … "4.5m" ("" for beds/reading at desk)
    noise: str            # quiet | music_med | music_loud | speech_bg
    style: str            # positive style key, or "read"/"trap"/"bed"
    mode: str             # fixed | manual | bed
    window_s: float       # fixed-record window or bed target duration
    script_line_id: Optional[str] = None
    lang: str = ""


@dataclass
class PlanConfig:
    """Knobs for the programme size. Defaults = the 'full' (~75 min) programme."""
    distances: tuple = ("0.3m", "1m", "2m", "3m", "4.5m")
    clean_styles: dict = field(default_factory=lambda: {
        "normal": 4, "fast": 2, "slow": 2, "loud": 2, "soft": 2,
        "sleepy": 1, "question": 1,
    })
    noisy_distances: tuple = ("1m", "3m")
    noisy_positive_reps: dict = field(default_factory=lambda: {
        "music_med": 12, "music_loud": 10, "speech_bg": 8,
    })
    # How many reading lines to repeat under each music condition (clean pass
    # always covers ALL lines once).
    noisy_script_lines: dict = field(default_factory=lambda: {
        "music_med": 16, "music_loud": 12,
    })
    trap_reps: int = 3
    bed_seconds: dict = field(default_factory=lambda: {
        "quiet": 240, "music_med": 180, "music_loud": 180, "speech_bg": 180,
    })
    positive_window_s: float = 2.8


def load_reading_script(path: Optional[Path] = None) -> list[dict]:
    data = json.loads(Path(path or _SCRIPT_PATH).read_text(encoding="utf-8"))
    return data["lines"]


def _positive(prompt_id: str, phase: str, dist: str, noise: str, style: str,
              window_s: float) -> PlanItem:
    return PlanItem(
        prompt_id=prompt_id, phase=phase, label="positive",
        say_text=WAKE_PHRASE,
        instruction=STYLE_DIRECTIONS_EL.get(style, style),
        distance=dist, noise=noise, style=style, mode="fixed",
        window_s=window_s,
    )


def _reading(line: dict, noise: str) -> PlanItem:
    label = "trap" if line["kind"] == "trap" else "negative"
    return PlanItem(
        prompt_id=f"read_{noise}_{line['id']}",
        phase=f"reading_{noise}", label=label, say_text=line["text"],
        instruction="διάβασέ το φυσικά, σαν να μιλάς σε άνθρωπο",
        distance="", noise=noise, style="read", mode="manual", window_s=0.0,
        script_line_id=line["id"], lang=line["lang"],
    )


def _trap(line: dict, rep: int) -> PlanItem:
    return PlanItem(
        prompt_id=f"trap_{line['id']}_r{rep}",
        phase="traps", label="trap", say_text=line["text"],
        instruction="πες το φυσικά — ο στόχος είναι να μάθει να ΜΗΝ ξυπνάει σε αυτό",
        distance="", noise="quiet", style="trap", mode="manual", window_s=0.0,
        script_line_id=line["id"], lang=line["lang"],
    )


def _bed(noise: str, seconds: float) -> PlanItem:
    return PlanItem(
        prompt_id=f"bed_{noise}", phase=f"bed_{noise}", label="bed",
        say_text="", instruction="ΜΗΝ μιλάς — ηχογραφούμε τον ήχο του δωματίου",
        distance="", noise=noise, style="bed", mode="bed", window_s=seconds,
    )


def build_plan(cfg: PlanConfig, script: Optional[list[dict]] = None) -> list[PlanItem]:
    script = script if script is not None else load_reading_script()
    read_lines = [l for l in script if l["kind"] == "read"]
    trap_lines = [l for l in script if l["kind"] == "trap"]

    items: list[PlanItem] = []

    # -- Quiet block ---------------------------------------------------------
    items.append(_bed("quiet", cfg.bed_seconds.get("quiet", 240)))

    for dist in cfg.distances:
        for style, reps in cfg.clean_styles.items():
            for k in range(reps):
                items.append(_positive(
                    f"p1_{dist}_{style}_{k:02d}", "positives_clean",
                    dist, "quiet", style, cfg.positive_window_s,
                ))

    items.extend(_reading(line, "quiet") for line in read_lines)

    for line in trap_lines:
        for rep in range(cfg.trap_reps):
            items.append(_trap(line, rep))

    # -- Noisy blocks: one banner each, everything for that condition inside --
    for noise, reps in cfg.noisy_positive_reps.items():
        for dist in cfg.noisy_distances:
            for k in range(reps):
                items.append(_positive(
                    f"p2_{noise}_{dist}_{k:02d}", f"positives_{noise}",
                    dist, noise, "normal", cfg.positive_window_s,
                ))
        n_lines = cfg.noisy_script_lines.get(noise, 0)
        if n_lines:
            # Alternate EL/EN through the deck so both languages appear under music.
            subset = read_lines[:n_lines] if noise == "music_med" \
                else read_lines[n_lines:n_lines + cfg.noisy_script_lines.get(noise, 0)]
            items.extend(_reading(line, noise) for line in subset)
        if noise in cfg.bed_seconds:
            items.append(_bed(noise, cfg.bed_seconds[noise]))

    return items


def remaining_items(plan: list[PlanItem], done_prompt_ids: set[str]) -> list[PlanItem]:
    """Resume = the plan minus prompts that already have at least one good take."""
    return [i for i in plan if i.prompt_id not in done_prompt_ids]
