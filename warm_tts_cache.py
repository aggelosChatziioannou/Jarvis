"""Pre-generate TTS audio for common phrases so the first occurrence is instant.

Run this once after enabling Chatterbox voice cloning. It takes a few
minutes (each phrase ~5-15s on GPU) and saves cached audio to
~/.local/share/jarvis/tts_cache/.

Subsequent runs skip phrases already cached for the current voice prompt
configuration.

Usage:
    python warm_tts_cache.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

# Read user config to discover voice settings actually in use
CONFIG = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".config" / "jarvis" / "config.json"
cfg: dict = {}
if CONFIG.exists():
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)

VOICE_PROMPT = cfg.get("tts_chatterbox_audio_prompt") or None
EXAGGERATION = float(cfg.get("tts_chatterbox_exaggeration", 0.5))
CFG_WEIGHT = float(cfg.get("tts_chatterbox_cfg_weight", 0.5))

# Phrases worth warming: short stock responses + common Spotify/Gmail/etc.
# Add your own as you notice phrases repeating.
PHRASES = [
    # Acknowledgements
    "Done.",
    "Got it.",
    "Sure.",
    "Okay.",
    "Yes.",
    "No.",
    "Hmm.",
    "Alright.",
    "I'm on it.",
    # Negatives
    "I don't know.",
    "Sorry, I didn't catch that.",
    "I couldn't find that.",
    "That didn't work.",
    # Spotify (action acks — used by fast-path response_override)
    "Skipped.",
    "Going back.",
    "Paused.",
    "Resuming.",
    "Volume up.",
    "Volume down.",
    "Volume set.",
    # Spotify (longer fallbacks)
    "Skipped to next track.",
    "Went back to previous track.",
    "Nothing is currently playing.",
    "No Spotify device is active. Open Spotify first.",
    # Apps (action acks)
    "Opening Spotify.",
    "Closing Spotify.",
    "Opening Chrome.",
    "Closing Chrome.",
    "Opening VS Code.",
    "Opening Discord.",
    "Opening Explorer.",
    "Opening Terminal.",
    "Opening Calculator.",
    "Opened.",
    "Closed.",
    # Browser
    "Browser closed.",
    # Gmail
    "No new emails.",
    # Notes/Reminders
    "Saved.",
    "Reminder set.",
    "No reminders are due right now.",
    # General
    "Anything else?",
    "What else?",
    "Welcome back.",
    "Good morning.",
    "Good evening.",
]

import torch
import torchaudio
from chatterbox.tts import ChatterboxTTS
from jarvis.output.tts_cache import get_cache

print(f"=== TTS cache warmer ===")
print(f"Voice prompt: {VOICE_PROMPT}")
print(f"Exaggeration: {EXAGGERATION}, CFG weight: {CFG_WEIGHT}")
print(f"Phrases to warm: {len(PHRASES)}")
print()

cache = get_cache()
existing_before, _ = cache.size_info()
print(f"Cache entries before: {existing_before}")

# Identify what's not yet cached
to_warm = []
for phrase in PHRASES:
    if cache.lookup(phrase, VOICE_PROMPT, EXAGGERATION, CFG_WEIGHT) is None:
        to_warm.append(phrase)
print(f"Already cached: {len(PHRASES) - len(to_warm)} / {len(PHRASES)}")
print(f"Need to generate: {len(to_warm)}")

if not to_warm:
    print("\nAll phrases already cached. Done.")
    sys.exit(0)

print(f"\nLoading Chatterbox on {'cuda' if torch.cuda.is_available() else 'cpu'}...")
device = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()
model = ChatterboxTTS.from_pretrained(device=device)
print(f"Loaded in {time.time() - t0:.1f}s")

print(f"\nGenerating audio (this may take a few minutes)...")
overall_t0 = time.time()
for i, phrase in enumerate(to_warm, 1):
    t0 = time.time()
    try:
        wav = model.generate(
            phrase,
            audio_prompt_path=VOICE_PROMPT,
            exaggeration=EXAGGERATION,
            cfg_weight=CFG_WEIGHT,
        )
        # Save to a temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            torchaudio.save(tmp_path, wav, model.sr)
            cache.store(phrase, VOICE_PROMPT, EXAGGERATION, CFG_WEIGHT, Path(tmp_path))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        elapsed = time.time() - t0
        print(f"  [{i}/{len(to_warm)}] ({elapsed:.1f}s) '{phrase}'")
    except Exception as e:
        print(f"  [{i}/{len(to_warm)}] FAILED on '{phrase}': {e}")

total_elapsed = time.time() - overall_t0
entries_after, bytes_after = cache.size_info()
print(f"\n=== Done in {total_elapsed:.1f}s ===")
print(f"Cache entries: {existing_before} -> {entries_after}")
print(f"Cache size: {bytes_after / 1024:.0f} KB")
print(f"\nThese phrases will now play instantly when Jarvis says them.")
