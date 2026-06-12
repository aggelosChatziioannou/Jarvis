#!/usr/bin/env python3
"""🎙️ Wake-word Recording Studio — guided session recorder.

Walks the user through the full recording programme (session_plan.py): shows
exactly what to say, counts down, records, quality-checks every take on the
spot and re-prompts bad ones. Clips land trainer-ready (16 kHz mono 16-bit)
with a full manifest row each. Stop any time with `q` — next run resumes where
you left off.

Run from the repo root (Windows, project venv):

    .venv\\Scripts\\python.exe wakeword-training\\studio\\record_studio.py

Useful flags:
    --list-devices      show input devices and exit
    --device N          record from input device N (default: system default)
    --print-script      print the reading script and exit
    --status            show progress of the session and exit
    --session NAME      session folder name (default: v2)
    --simulate [--auto] synthesise audio instead of recording (flow testing)
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252-hostile consoles

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from studio import qc  # noqa: E402
from studio.manifest import (  # noqa: E402
    MANIFEST_NAME,
    append_row,
    completed_prompt_ids,
    load_rows,
)
from studio.session_plan import (  # noqa: E402
    NOISE_BANNERS_EL,
    PlanConfig,
    PlanItem,
    build_plan,
    load_reading_script,
    remaining_items,
)

SR = 16000
DEFAULT_BASE = Path.home() / ".local" / "share" / "jarvis" / "wakeword" / "studio_sessions"

# Acceptable active-RMS floor per distance — far clips are legitimately quiet.
RMS_FLOORS_DBFS = {"0.3m": -38.0, "1m": -42.0, "2m": -46.0, "3m": -50.0, "4.5m": -54.0, "": -50.0}
MAX_AUTO_REDOS = 3


# ---------------------------------------------------------------------------
# Audio backends
# ---------------------------------------------------------------------------

class MicRecorder:
    def __init__(self, device: int | None):
        import sounddevice as sd  # imported lazily so --simulate needs no audio stack
        self.sd = sd
        self.device = device

    def record_fixed(self, seconds: float) -> np.ndarray:
        frames = int(seconds * SR)
        buf = self.sd.rec(frames, samplerate=SR, channels=1, dtype="float32",
                          device=self.device)
        self.sd.wait()
        return buf.reshape(-1)

    def record_until_enter(self, prompt: str) -> np.ndarray:
        chunks: list[np.ndarray] = []

        def _cb(indata, _frames, _time, _status):
            chunks.append(indata[:, 0].copy())

        stream = self.sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                     device=self.device, callback=_cb)
        with stream:
            input(prompt)
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)

    def record_timed(self, seconds: float, tick_cb) -> np.ndarray:
        chunks: list[np.ndarray] = []

        def _cb(indata, _frames, _time, _status):
            chunks.append(indata[:, 0].copy())

        stream = self.sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                     device=self.device, callback=_cb)
        start = time.monotonic()
        with stream:
            while time.monotonic() - start < seconds:
                time.sleep(1.0)
                tick_cb(time.monotonic() - start)
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


class SimulatedRecorder:
    """Synthesises speech-like audio so the full session flow can run headless."""

    def __init__(self):
        self._rng = np.random.default_rng(42)

    def _speechlike(self, seconds: float) -> np.ndarray:
        n = int(max(seconds, 1.2) * SR)
        a = self._rng.normal(0, 1e-4, n).astype(np.float32)
        s, e = int(0.3 * SR), min(n, int(0.3 * SR) + int(1.0 * SR))
        t = np.arange(e - s) / SR
        a[s:e] += (0.2 * np.sin(2 * np.pi * 170 * t)
                   * (0.6 + 0.4 * np.sin(2 * np.pi * 2.5 * t))).astype(np.float32)
        return a

    def record_fixed(self, seconds: float) -> np.ndarray:
        return self._speechlike(seconds)

    def record_until_enter(self, prompt: str) -> np.ndarray:
        return self._speechlike(3.0)

    def record_timed(self, seconds: float, tick_cb) -> np.ndarray:
        return self._rng.normal(0, 0.003, int(seconds * SR)).astype(np.float32)


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

class Console:
    def __init__(self, auto: bool):
        self.auto = auto

    def ask(self, prompt: str) -> str:
        if self.auto:
            return ""
        try:
            return input(prompt).strip().lower()
        except EOFError:
            return "q"

    def pause(self, prompt: str) -> None:
        self.ask(prompt)


def _banner(text: str) -> None:
    print()
    print("  " + "─" * 62)
    for line in text.splitlines():
        print(f"  {line}")
    print("  " + "─" * 62)


def _countdown(console: Console) -> None:
    if console.auto:
        return
    for n in (3, 2, 1):
        print(f"      {n}…", flush=True)
        time.sleep(0.7)
    print("      🔴 ΤΩΡΑ!", flush=True)


def _daemon_is_listening() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:38130/api/state", timeout=1.5):
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session runner
# ---------------------------------------------------------------------------

def _qc_floor(item: PlanItem) -> float:
    return RMS_FLOORS_DBFS.get(item.distance, RMS_FLOORS_DBFS[""])


def _take_number(rows: list[dict], prompt_id: str) -> int:
    return 1 + sum(1 for r in rows if r.get("prompt_id") == prompt_id)


def _record_item(item: PlanItem, recorder, console: Console) -> np.ndarray | None:
    """One recording attempt for a plan item. None means user skipped."""
    if item.mode == "fixed":
        _countdown(console)
        audio = recorder.record_fixed(item.window_s)
        print("      ⏹️ τέλος λήψης")
        return audio
    if item.mode == "manual":
        audio = recorder.record_until_enter(
            "      🔴 Ηχογραφώ — διάβασέ το και πάτα Enter μόλις τελειώσεις… ")
        return qc.trim_pad(audio, SR)
    if item.mode == "bed":
        mins = item.window_s / 60.0
        print(f"      🔴 Ηχογραφώ τον ήχο του χώρου για {mins:.0f} λεπτά — μην μιλάς.")

        def _tick(elapsed: float) -> None:
            if int(elapsed) % 30 == 0 and elapsed >= 29:
                print(f"      ⏳ {elapsed:.0f}s / {item.window_s:.0f}s", flush=True)

        return recorder.record_timed(item.window_s, _tick)
    return None


def _setup_banner(item: PlanItem, prev: PlanItem | None, console: Console) -> None:
    """Tell the user to move / change music ONLY when the condition changes."""
    if prev is not None and (prev.noise, prev.distance) == (item.noise, item.distance):
        return
    lines = []
    if prev is None or prev.noise != item.noise:
        lines.append(NOISE_BANNERS_EL.get(item.noise, item.noise))
    if item.distance and (prev is None or prev.distance != item.distance):
        lines.append(f"📏 Στάσου περίπου στα {item.distance.replace('m', ' μέτρα')} από το μικρόφωνο.")
    if not item.distance and prev is not None and prev.distance:
        lines.append("📏 Έλα ξανά κοντά στο γραφείο/μικρόφωνο (κανονική θέση).")
    if lines:
        _banner("\n".join(lines))
        console.pause("  ✅ Πάτα Enter όταν είσαι έτοιμος… ")


def run_session(args) -> int:
    session_dir = Path(args.base) / args.session
    clips_dir = session_dir / "clips"
    manifest_path = session_dir / MANIFEST_NAME

    plan = build_plan(PlanConfig())
    rows = load_rows(manifest_path)
    done = completed_prompt_ids(rows)
    todo = remaining_items(plan, done)

    print()
    print("  🎙️  Wake-word Recording Studio")
    print(f"      📂 Συνεδρία : {session_dir}")
    print(f"      📋 Πρόοδος  : {len(plan) - len(todo)}/{len(plan)} prompts ολοκληρωμένα")
    if not todo:
        print("      🎉 Όλα ολοκληρωμένα! Δεν έχει μείνει τίποτα για ηχογράφηση.")
        return 0

    if not args.simulate and _daemon_is_listening():
        _banner("🛑 Ο JARVIS ΤΡΕΧΕΙ ΚΑΙ ΑΚΟΥΕΙ!\n"
                "Θα ξυπνάει σε ΚΑΘΕ «Hey Jarvis» που θα ηχογραφήσεις.\n"
                "Κλείσε τον (ή κάνε mute) πριν συνεχίσεις.")
        if Console(args.auto).ask("  Συνέχεια ΧΩΡΙΣ να τον κλείσεις; (y/N) ") != "y":
            print("  👋 Σταμάτησα. Κλείσε τον Jarvis και ξανατρέξε με.")
            return 1

    console = Console(args.auto)
    recorder = SimulatedRecorder() if args.simulate else MicRecorder(args.device)

    if not args.simulate:
        _banner("🎚️ Έλεγχος στάθμης: πες 2-3 λέξεις με κανονική φωνή στη θέση σου.")
        console.pause("  Πάτα Enter και μίλα για ~3 δευτερόλεπτα… ")
        level = recorder.record_fixed(3.0)
        rep = qc.analyse(level, SR, rms_floor_dbfs=-50.0)
        print(f"      📊 Στάθμη: {rep.rms_dbfs:.1f} dBFS, κορυφή {rep.peak:.2f} "
              f"{'✅' if rep.ok else '⚠️ ' + '; '.join(rep.problems)}")

    saved = skipped = 0
    prev: PlanItem | None = None
    for item in todo:
        _setup_banner(item, prev, console)
        prev = item

        idx = len(plan) - len(todo) + saved + skipped + 1
        label_icon = {"positive": "🎯", "negative": "📖", "trap": "🪤", "bed": "🌫️"}[item.label]
        print()
        print(f"  {label_icon} [{idx}/{len(plan)}] {item.prompt_id}")
        if item.say_text:
            print(f"      🗣️  Πες: «{item.say_text}»")
        print(f"      💡 {item.instruction}")

        redos = 0
        while True:
            cmd = console.ask("      ▶️  Enter=ηχογράφηση | s=παράλειψη | q=αποθήκευση+έξοδος: ")
            if cmd == "q":
                print(f"\n  💾 Αποθηκεύτηκαν {saved} νέες λήψεις. Συνεχίζουμε από εδώ την επόμενη φορά!")
                return 0
            if cmd == "s":
                skipped += 1
                break

            audio = _record_item(item, recorder, console)
            if audio is None or not len(audio):
                print("      ⚠️ Κενή λήψη — ξαναπροσπάθησε.")
                continue

            report = qc.analyse(audio, SR, rms_floor_dbfs=_qc_floor(item))
            accept = report.ok or item.label == "bed"  # beds are allowed to be near-silent
            if not accept and redos < MAX_AUTO_REDOS:
                redos += 1
                print(f"      ⚠️ Πρόβλημα: {'; '.join(report.problems)} — πάμε ξανά ({redos}/{MAX_AUTO_REDOS}).")
                continue
            if not accept:
                print("      ⚠️ Την κρατάω παρ' όλα αυτά (σημειώνεται στο manifest).")

            rows = load_rows(manifest_path)
            take = _take_number(rows, item.prompt_id)
            rel = f"clips/{item.prompt_id}__t{take}.wav"
            qc.save_wav(audio, SR, session_dir / rel)
            append_row(manifest_path, {
                "prompt_id": item.prompt_id, "take": take, "file": rel,
                "label": item.label, "text": item.say_text,
                "lang": item.lang, "phase": item.phase,
                "distance": item.distance, "noise": item.noise,
                "style": item.style, "samplerate": SR,
                "duration_s": round(len(audio) / SR, 2),
                "rms_dbfs": round(report.rms_dbfs, 1),
                "peak": round(report.peak, 3),
                "qc_ok": bool(report.ok),
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            })
            saved += 1
            print(f"      ✅ Σώθηκε ({report.rms_dbfs:.1f} dBFS) — {rel}")

            again = console.ask("      🔁 r=ξαναπάρ'την | Enter=επόμενο: ")
            if again != "r":
                break
            redos = 0

    print()
    print("  🎉 ΣΥΝΕΔΡΙΑ ΟΛΟΚΛΗΡΩΜΕΝΗ!")
    print(f"      ✅ Νέες λήψεις: {saved}   ⏭️ Παραλείψεις: {skipped}")
    print(f"      📂 {session_dir}")
    print("      ➡️  Επόμενο βήμα: πες στον Claude ότι τελείωσες — αναλαμβάνει το training.")
    return 0


def show_status(args) -> int:
    session_dir = Path(args.base) / args.session
    plan = build_plan(PlanConfig())
    rows = load_rows(session_dir / MANIFEST_NAME)
    done = completed_prompt_ids(rows)
    by_phase: dict[str, list[PlanItem]] = {}
    for item in plan:
        by_phase.setdefault(item.phase, []).append(item)
    print(f"\n  📋 Πρόοδος συνεδρίας «{args.session}» ({len(done)}/{len(plan)}):")
    for phase, items in by_phase.items():
        d = sum(1 for i in items if i.prompt_id in done)
        mark = "✅" if d == len(items) else ("🔶" if d else "⬜")
        print(f"      {mark} {phase:<22} {d}/{len(items)}")
    total_s = sum(r.get("duration_s", 0.0) for r in rows)
    print(f"      🎧 Συνολικός ηχογραφημένος χρόνος: {total_s / 60:.1f} λεπτά\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Guided wake-word recording session")
    ap.add_argument("--session", default="v2")
    ap.add_argument("--base", default=str(DEFAULT_BASE))
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--print-script", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--simulate", action="store_true",
                    help="synthesise audio instead of recording (flow test)")
    ap.add_argument("--auto", action="store_true",
                    help="with --simulate: no keypresses, run straight through")
    args = ap.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0
    if args.print_script:
        for line in load_reading_script():
            tag = "🪤" if line["kind"] == "trap" else "📖"
            print(f"  {tag} [{line['id']}] {line['text']}")
        return 0
    if args.status:
        return show_status(args)
    return run_session(args)


if __name__ == "__main__":
    raise SystemExit(main())
