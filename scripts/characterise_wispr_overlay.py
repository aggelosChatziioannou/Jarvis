"""One-off live characterisation of Wispr Flow's recording overlay.

Run (no Jarvis daemon listener active, ports 38130/38127 free):

    .venv\\Scripts\\python.exe -X utf8 scripts/characterise_wispr_overlay.py

Snapshots every top-level window owned by a "Wispr Flow" process in three
phases (idle -> recording -> idle) by tapping the hands-free toggle
(Ctrl+Win+Space) via pynput, then prints a diff so we can pick the attribute
that deterministically distinguishes "recording" from "idle". That attribute
becomes the discriminator wired into ``WisprStateProbe`` (wispr_state.py).

Best-effort, non-destructive: it leaves Wispr toggled back to idle. Repeat
>= 3 times; a reliable discriminator must change the SAME way every run.
"""

from __future__ import annotations

import sys
import time
import winreg
from dataclasses import dataclass

try:
    import win32gui
    import win32process
    import psutil
except Exception as e:  # pragma: no cover - diagnostic script
    print(f"[ERROR] needs pywin32 + psutil: {e!r}", file=sys.stderr)
    sys.exit(1)

try:
    from pynput.keyboard import Controller, Key
except Exception as e:  # pragma: no cover - diagnostic script
    print(f"[ERROR] needs pynput: {e!r}", file=sys.stderr)
    sys.exit(1)

WISPR_PROC = "Wispr Flow"
KEY_GAP = 0.05


@dataclass(frozen=True)
class Win:
    pid: int
    cls: str
    title: str
    visible: bool
    w: int
    h: int
    left: int
    top: int

    def key(self) -> str:
        # Identity for matching the SAME window across phases.
        return f"{self.cls}|{self.title}"

    def state(self) -> str:
        return f"vis={self.visible} size={self.w}x{self.h} pos=({self.left},{self.top})"


def _proc_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def snapshot() -> list[Win]:
    out: list[Win] = []

    def cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if _proc_name(pid) != f"{WISPR_PROC}.exe" and _proc_name(pid) != WISPR_PROC:
                return True
            cls = win32gui.GetClassName(hwnd) or ""
            title = win32gui.GetWindowText(hwnd) or ""
            vis = bool(win32gui.IsWindowVisible(hwnd))
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            out.append(Win(pid, cls, title, vis, r - l, b - t, l, t))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def tap_toggle() -> None:
    kb = Controller()
    kb.press(Key.ctrl); time.sleep(KEY_GAP)
    kb.press(Key.cmd); time.sleep(KEY_GAP)
    kb.press(Key.space); time.sleep(KEY_GAP)
    kb.release(Key.space); time.sleep(KEY_GAP)
    kb.release(Key.cmd); time.sleep(KEY_GAP)
    kb.release(Key.ctrl)


_MIC_KEYS = [
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged",
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone",
]


def mic_usage() -> list[str]:
    """Return Wispr-related mic-consent entries with LastUsedTimeStart/Stop.

    Stop == 0 means the app is CURRENTLY using the microphone (Windows
    privacy indicator). Subkey names use '#' in place of path separators.
    """
    rows: list[str] = []
    for base in _MIC_KEYS:
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            if "wispr" not in sub.lower() and "flow" not in sub.lower():
                continue
            try:
                k = winreg.OpenKey(root, sub)
                start = _qv(k, "LastUsedTimeStart")
                stop = _qv(k, "LastUsedTimeStop")
                in_use = stop == 0
                rows.append(f"  [{base.split('ConsentStore')[-1]}] {sub}\n"
                            f"      start={start} stop={stop} IN_USE={in_use}")
            except OSError as e:
                rows.append(f"  {sub}: <read error {e!r}>")
    return rows


def _qv(key, name: str):
    try:
        v, _ = winreg.QueryValueEx(key, name)
        return v
    except OSError:
        return None


def print_mic(label: str) -> None:
    rows = mic_usage()
    print(f"\n--- MIC consent ({label}) ---")
    if not rows:
        print("  (no Wispr/Flow mic-consent entry found)")
    for r in rows:
        print(r)


def print_snapshot(label: str, wins: list[Win]) -> None:
    print(f"\n=== {label} ({len(wins)} windows) ===")
    for w in sorted(wins, key=lambda x: (x.cls, x.title)):
        print(f"  pid={w.pid} {w.state()} cls='{w.cls}' title='{w.title}'")


def diff(a: list[Win], b: list[Win], la: str, lb: str) -> None:
    print(f"\n=== DIFF {la} -> {lb} ===")
    amap = {w.key(): w for w in a}
    bmap = {w.key(): w for w in b}
    for k in sorted(set(amap) | set(bmap)):
        wa, wb = amap.get(k), bmap.get(k)
        if wa and not wb:
            print(f"  REMOVED  {k}  ({wa.state()})")
        elif wb and not wa:
            print(f"  ADDED    {k}  ({wb.state()})")
        elif wa.state() != wb.state():
            print(f"  CHANGED  {k}\n             {la}: {wa.state()}\n             {lb}: {wb.state()}")


def main() -> None:
    print("[INFO] Characterising Wispr overlay. Make sure no other dictation is running.")
    idle1 = snapshot()
    print_snapshot("IDLE (before)", idle1)
    print_mic("IDLE before")

    print("\n[ACTION] tapping Ctrl+Win+Space (start)...")
    tap_toggle()
    time.sleep(1.6)
    rec = snapshot()
    print_snapshot("RECORDING", rec)
    print_mic("RECORDING")

    print("\n[ACTION] tapping Ctrl+Win+Space (stop)...")
    tap_toggle()
    time.sleep(1.6)
    idle2 = snapshot()
    print_snapshot("IDLE (after)", idle2)
    print_mic("IDLE after")

    diff(idle1, rec, "IDLE", "RECORDING")
    diff(rec, idle2, "RECORDING", "IDLE")
    print("\n[DONE] Pick the attribute that changes the SAME way every run as the discriminator.")


if __name__ == "__main__":
    main()
