"""Standalone Phase-1 verification for the Jarvis Vision Engine.

Run from the repo root with the project venv:

    set PYTHONIOENCODING=utf-8
    .venv\\Scripts\\python.exe scripts\\vision\\verify_vision_model.py            # Tests A-E (no mouse movement)
    .venv\\Scripts\\python.exe scripts\\vision\\verify_vision_model.py --click    # also Test F (moves the mouse!)

Tests:
  A  describe          qwen2.5vl describes a captured screen
  B  OCR (English)     Tesseract transcribes known English text
  C  locate accuracy   Tesseract word-box vs qwen grounding on a known target
  E  OCR (Greek)       Tesseract vs vision model on known Greek text (Tesseract should win)
  F  DPI click         capture -> convert -> ACTUAL pyautogui click within 20px (needs --click)

Writes docs/vision_test_report.md. Test F builds its own full-screen target window,
so clicks land on a harmless known marker (ground truth for the 20px gate).
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from jarvis.vision.analyzer import ScreenAnalyzer, locate_text_label, read_text, resolve_tesseract  # noqa: E402
from jarvis.vision.capture import ScreenCapture  # noqa: E402
from jarvis.vision.model_client import VisionModelClient  # noqa: E402
from jarvis.vision.monitor_map import MonitorMap, ensure_dpi_awareness  # noqa: E402

BASE_URL = "http://localhost:11434"
MODEL = "qwen2.5vl:3b"
_report_lines = []


def log(line=""):
    print(line, flush=True)
    _report_lines.append(line)


def _font(size=30):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _token_overlap(expected, got):
    import re
    e = set(re.findall(r"\w+", expected.lower(), re.UNICODE))
    g = set(re.findall(r"\w+", got.lower(), re.UNICODE))
    return (len(e & g) / len(e) * 100.0) if e else 0.0


def test_a_describe(client, capture):
    log("\n👁️  TEST A — describe a real screen")
    t0 = time.time()
    img = capture.capture_primary()
    desc = client.describe(img) or ""
    dt = time.time() - t0
    ok = len(desc.strip()) >= 30
    log(f"   latency={dt:.2f}s chars={len(desc)} -> {'PASS' if ok else 'FAIL'}")
    log(f"   snippet: {desc[:160]!r}")
    return ok


def test_b_ocr_english():
    log("\n📖 TEST B — OCR English (synthetic, known text)")
    expected = "The quick brown fox jumps over the lazy dog"
    img = Image.new("RGB", (900, 200), (255, 255, 255))
    ImageDraw.Draw(img).text((20, 80), expected, fill=(0, 0, 0), font=_font(34))
    got = read_text(img, langs="eng")
    acc = _token_overlap(expected, got)
    ok = acc >= 80.0
    log(f"   accuracy={acc:.0f}% -> {'PASS' if ok else 'FAIL'}  got={got!r}")
    return ok


def test_c_locate(client):
    log("\n🔎 TEST C — locate accuracy (synthetic, known centre)")
    W, H = 1280, 800
    img = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([120, 120, 360, 180], outline=(0, 0, 200), width=3)
    d.text((150, 132), "Cancel", fill=(0, 0, 200), font=_font(30))
    known = (240, 150)
    ocr = locate_text_label(img, "Cancel")
    vis = client.locate(img, "the Cancel button")
    ocr_err = (((ocr[0] - known[0]) ** 2 + (ocr[1] - known[1]) ** 2) ** 0.5) if ocr else None
    vis_err = (((vis[0] - known[0]) ** 2 + (vis[1] - known[1]) ** 2) ** 0.5) if vis else None
    log(f"   known={known} ocr={ocr} (err={ocr_err}) vision={vis} (err={vis_err})")
    ok = ocr is not None and ocr_err is not None and ocr_err <= 20
    log(f"   Tesseract word-box within 20px -> {'PASS' if ok else 'FAIL'}")
    return ok


def test_e_greek(client):
    log("\n🇬🇷 TEST E — Greek OCR: Tesseract vs vision model")
    expected = "Αποθήκευση αρχείου"
    img = Image.new("RGB", (700, 200), (255, 255, 255))
    ImageDraw.Draw(img).text((20, 80), expected, fill=(0, 0, 0), font=_font(34))
    tess = read_text(img, langs="eng+ell")
    vis = client.analyze(img, "Transcribe the text in this image exactly.") or ""
    tess_acc = _token_overlap(expected, tess)
    vis_acc = _token_overlap(expected, vis)
    log(f"   Tesseract acc={tess_acc:.0f}%  vision acc={vis_acc:.0f}%")
    log(f"   tesseract={tess!r}")
    ok = tess_acc >= 70.0
    log(f"   Tesseract Greek usable -> {'PASS' if ok else 'FAIL'}")
    return ok


def test_f_dpi_click(monitors, capture, client):
    log("\n🖱️  TEST F — DPI click round-trip (moves the mouse!)")
    try:
        import tkinter as tk
        import pyautogui
    except Exception as exc:
        log(f"   SKIP — tkinter/pyautogui unavailable: {exc}")
        return None

    results = []
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(bg="white")
    canvas = tk.Canvas(root, bg="white", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    root.update()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    # Known target marker at a fixed position within the primary monitor image.
    tx, ty = int(sw * 0.6), int(sh * 0.55)
    canvas.create_oval(tx - 40, ty - 40, tx + 40, ty + 40, fill="#cc2828", outline="")
    canvas.create_text(tx, ty, text="TARGET", fill="white")
    landed = {}
    canvas.bind("<Button-1>", lambda e: landed.update(x=e.x, y=e.y))
    root.update()
    time.sleep(0.4)

    # F1 (deterministic): known relative coord -> absolute -> click. Tests pure DPI/conversion.
    abs_xy = monitors.to_absolute(tx, ty, "primary")
    if monitors.in_bounds(abs_xy[0], abs_xy[1], "primary"):
        pyautogui.click(abs_xy[0], abs_xy[1])
        root.update()
        time.sleep(0.2)
        if landed:
            err = ((landed["x"] - tx) ** 2 + (landed["y"] - ty) ** 2) ** 0.5
            log(f"   F1 deterministic: target=({tx},{ty}) landed=({landed['x']},{landed['y']}) err={err:.0f}px "
                f"-> {'PASS' if err <= 20 else 'FAIL'}")
            results.append(err <= 20)
    root.destroy()
    return all(results) if results else None


def vram_snapshot():
    import subprocess
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=15).stdout
        log("\n📊 VRAM (ollama ps):\n" + out.strip())
    except Exception as exc:
        log(f"   (ollama ps unavailable: {exc})")


def main():
    do_click = "--click" in sys.argv
    log("=" * 60)
    log("🔬 Jarvis Vision Engine — Phase-1 verification")
    log("=" * 60)
    ensure_dpi_awareness()
    monitors = MonitorMap()
    capture = ScreenCapture(monitor_map=monitors)
    client = VisionModelClient(base_url=BASE_URL, model=MODEL, timeout_sec=60.0, keep_alive="5m")
    resolve_tesseract()

    log("\n🖥️  Monitors:")
    for m in monitors.monitors:
        log(f"   #{m.index} ({m.left},{m.top}) {m.width}x{m.height} primary={m.is_primary} scale={m.scale}")

    results = {
        "A describe": test_a_describe(client, capture),
        "B OCR-en": test_b_ocr_english(),
        "C locate": test_c_locate(client),
        "E OCR-el": test_e_greek(client),
    }
    if do_click:
        results["F DPI-click"] = test_f_dpi_click(monitors, capture, client)
    else:
        log("\n🖱️  TEST F skipped (pass --click to run the live click round-trip).")

    vram_snapshot()

    log("\n" + "=" * 60)
    log("📋 SUMMARY")
    for name, ok in results.items():
        mark = "✅" if ok else ("⏭️ " if ok is None else "❌")
        log(f"   {mark} {name}: {ok}")
    log("=" * 60)

    report = ROOT / "docs" / "vision_test_report.md"
    try:
        report.write_text("# Vision Engine — Phase-1 Test Report\n\n```\n" + "\n".join(_report_lines) + "\n```\n",
                           encoding="utf-8")
        log(f"\n📝 Report written to {report}")
    except Exception as exc:
        log(f"   (could not write report: {exc})")


if __name__ == "__main__":
    main()
