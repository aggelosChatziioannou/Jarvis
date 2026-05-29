"""
WisprBridge — JARVIS-embeddable wake-word + VAD push-to-talk for Wispr Flow.
============================================================================

Adapted from the standalone ``jarvis_wispr_bridge.py``. The bridge runs
three concurrent layers over a single shared audio stream:

  LAYER A   Wake Word Detector  — openWakeWord (ONNX), "Hey Jarvis"
  LAYER B   Keyboard Controller — pynput, TAPS Ctrl+Win+Space (hands-free
                                  toggle) at start AND at stop. No keys are
                                  held, so the user's keyboard remains free
                                  during dictation.
  LAYER C   VAD Monitor         — Silero, taps off on N ms of silence

State machine
-------------
  IDLE       -> DICTATING   : wake word detected (>= threshold), OR
                              HOT_WINDOW expired AND VAD detected speech
  IDLE       -> HOT_WINDOW  : explicitly entered via :meth:`enter_hot_window`
  HOT_WINDOW -> DICTATING   : speech detected (no wake word required)
  HOT_WINDOW -> IDLE        : timer expired without speech
  DICTATING  -> IDLE        : 800ms continuous silence OR hard timeout

Transcripts arrive via the system clipboard (Wispr Flow writes them there
after its cloud round-trip). The bridge then erases the auto-typed copy
with N backspaces and dispatches the text via ``on_transcription`` callback.

Threading model
---------------
  * Audio callback runs on PortAudio's thread — never sleeps, never blocks.
  * Key press/release runs on a dedicated FIFO worker thread.
  * Clipboard polling + backspacing run on per-dictation worker threads.
  * State transitions are guarded by ``_state_lock``; key holds by
    ``_keys_lock``. Callbacks (``on_transcription`` etc.) are invoked
    from the post-dictation worker thread — the embedding application is
    responsible for marshalling back to its own threads if needed.
"""

from __future__ import annotations

import atexit
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

import numpy as np

from ..debug import debug_log


# ============================================================================
# Required-dependency imports with clean error hints
# ============================================================================

try:
    import sounddevice as sd
except ImportError as e:  # pragma: no cover - import-time only
    raise ImportError(
        "WisprBridge requires `sounddevice`. Install with: "
        "pip install sounddevice"
    ) from e

try:
    import torch
except ImportError as e:  # pragma: no cover - import-time only
    raise ImportError(
        "WisprBridge requires `torch` for Silero VAD. Install with: "
        "pip install torch"
    ) from e

try:
    from pynput.keyboard import Controller, Key
except ImportError as e:  # pragma: no cover - import-time only
    raise ImportError(
        "WisprBridge requires `pynput` for keyboard simulation. "
        "Install with: pip install pynput"
    ) from e

# openWakeWord is imported lazily inside :meth:`start` so that import-time
# failures don't break unrelated modules. ImportError is raised cleanly
# from start() if the package is missing.

# Clipboard capture is optional — degrade gracefully if pyperclip is missing.
try:
    import pyperclip  # type: ignore
    _CLIPBOARD_AVAILABLE = True
except Exception:
    pyperclip = None  # type: ignore
    _CLIPBOARD_AVAILABLE = False


# ============================================================================
# Protocol constants (not config-driven — these are fixed by the models)
# ============================================================================

SAMPLE_RATE = 16000              # openWakeWord + Silero both require 16 kHz
WAKE_FRAME_SIZE = 1280           # openWakeWord requires 1280 samples (80ms)
VAD_FRAME_SIZE = 512             # Silero v5 requires exactly 512 samples @16k
AUDIO_BLOCK_SIZE = 512           # ~32ms @16k; small for VAD responsiveness
KEY_INTER_PRESS_DELAY = 0.05     # 50ms between Ctrl and Win events
CLIPBOARD_POLL_INTERVAL = 0.2    # clipboard polling cadence
CLIPBOARD_PREVIEW_CHARS = 200    # truncate long transcripts in console output

# Per-frame wake-word cooldown (~2s at 80ms/frame)
WAKE_COOLDOWN_FRAMES = 25
# Silero speech-probability threshold (kept fixed — adjusting per-deployment
# is rarely useful and confuses the silence-duration math)
VAD_THRESHOLD = 0.5


# ============================================================================
# Defaults for config-driven values (used when the field is absent on cfg)
# ============================================================================

DEFAULT_WAKE_MODEL = "hey_jarvis_v0.1"
DEFAULT_WAKE_THRESHOLD = 0.1
DEFAULT_SILENCE_MS = 800
DEFAULT_MIN_DICTATION_SEC = 2.0
DEFAULT_MAX_DICTATION_SEC = 30
DEFAULT_CLIPBOARD_WAIT_SEC = 6.0
DEFAULT_HOT_WINDOW_SEC = 10.0
DEFAULT_SUPPRESS_AUTOTYPE = True
DEFAULT_MIC_DEVICE: Optional[Any] = None


# ============================================================================
# State enums
# ============================================================================

class State(Enum):
    IDLE = "IDLE"
    DICTATING = "DICTATING"
    HOT_WINDOW = "HOT_WINDOW"


class KeyEvent(Enum):
    PRESS = "press"
    RELEASE = "release"
    STOP = "stop"


# ============================================================================
# Bridge
# ============================================================================

class WisprBridge:
    """
    JARVIS-embeddable wake-word + VAD push-to-talk bridge.

    Coordinates openWakeWord wake detection, Silero VAD silence detection,
    and pynput keyboard simulation through a single shared audio stream.
    Reports transcripts via callbacks rather than handling them internally.

    Lifecycle
    ---------
        bridge = WisprBridge(cfg, on_transcription=my_handler)
        if bridge.start():
            ...                # bridge runs in background threads
            bridge.stop()
    """

    def __init__(
        self,
        cfg: Any,
        on_transcription: Callable[[str], None],
        on_wake: Optional[Callable[[], None]] = None,
        on_dictation_end: Optional[Callable[[bool], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
    ):
        # ---- Callbacks (invoked from background threads) ------------------
        self.on_transcription = on_transcription
        self.on_wake = on_wake
        # Fired once per dictation when the post-dictation worker finishes.
        # Receives ``captured: bool`` — True when a clipboard transcript was
        # captured within the wait window (i.e. on_transcription also fired),
        # False when none arrived (timeout) or clipboard polling is off. The
        # listener uses this to decide whether to re-arm or recover.
        self.on_dictation_end = on_dictation_end
        # Fired when a stop pattern ('stop', 'σταμάτα', ...) is detected
        # while JARVIS is speaking. Listener uses this to interrupt TTS.
        self.on_stop = on_stop

        # ---- Config (read defensively — Phase B may not have populated
        # these fields yet) -------------------------------------------------
        self.cfg = cfg
        self.wake_model_name = getattr(
            cfg, "wispr_wake_model", DEFAULT_WAKE_MODEL)
        self.wake_threshold = float(getattr(
            cfg, "wispr_wake_threshold", DEFAULT_WAKE_THRESHOLD))
        self.silence_ms = int(getattr(
            cfg, "wispr_silence_ms", DEFAULT_SILENCE_MS))
        self.min_dictation_sec = float(getattr(
            cfg, "wispr_min_dictation_sec", DEFAULT_MIN_DICTATION_SEC))
        self.max_dictation_sec = float(getattr(
            cfg, "wispr_max_dictation_sec", DEFAULT_MAX_DICTATION_SEC))
        self.clipboard_wait_sec = float(getattr(
            cfg, "wispr_clipboard_wait_sec", DEFAULT_CLIPBOARD_WAIT_SEC))
        self.hot_window_sec = float(getattr(
            cfg, "wispr_hot_window_sec", DEFAULT_HOT_WINDOW_SEC))
        self.suppress_autotype = bool(getattr(
            cfg, "wispr_suppress_autotype", DEFAULT_SUPPRESS_AUTOTYPE))
        self.device = getattr(cfg, "wispr_mic_device", DEFAULT_MIC_DEVICE)

        # Clipboard watching is required (it's how we get the transcript).
        # If pyperclip isn't installed we still run — but the transcript
        # callback will never fire. We log a warning at start() in that case.
        self.watch_clipboard = _CLIPBOARD_AVAILABLE

        # ---- State machine ------------------------------------------------
        self._state = State.IDLE
        self._state_lock = threading.Lock()
        self._dictation_start = 0.0
        self.shutdown_event = threading.Event()

        # Models (loaded in start())
        self.wake_model = None
        self.vad_model = None
        self.vad_iterator = None

        # Sample buffers
        self._wake_buf: list[int] = []     # int16 samples for wake
        self._vad_buf: list[float] = []    # float32 samples for VAD

        # Wake-word cooldown (frames since last trigger)
        self._wake_cooldown = 0

        # Clipboard baseline captured at wake time
        self._clipboard_baseline: str = ""

        # Audio stream
        self.audio_stream: Optional[sd.InputStream] = None

        # Mute / pause state — set by MUTE from the control bus. When True
        # we still keep the audio stream open (so we can resume instantly)
        # but ``_process_wake`` short-circuits without ever calling the
        # wake model. In-flight dictations are allowed to complete.
        self._paused = False

        # Keyboard worker
        self._keyboard = Controller()
        self._keys_held = False
        self._keys_lock = threading.Lock()
        self._key_queue: queue.Queue = queue.Queue()
        self._key_thread: Optional[threading.Thread] = None

        # Hot-window timer + deadline (Phase E)
        self._hot_window_timer: Optional[threading.Timer] = None
        self._hot_window_lock = threading.Lock()
        self._hot_window_until: float = 0.0

        # Speaking flag (Phase F — drives stop-pattern interrupt routing).
        # Written from the TTS thread (set_speaking) and read from the
        # post-dictation worker + audio threads; guard every access with
        # ``_speaking_lock`` so reads see a consistent snapshot.
        self._jarvis_speaking = False
        self._speaking_lock = threading.Lock()

        # Post-speak resume timer — when JARVIS finishes speaking, we delay
        # re-enabling wake detection by ``_post_speak_cooldown_sec`` so the
        # tail of the TTS audio (room echo, reverb, speaker decay) can't
        # falsely trigger the wake word. Cancelled if a new TTS starts
        # during the cooldown window.
        self._post_speak_resume_timer: Optional[threading.Timer] = None
        self._post_speak_cooldown_sec: float = 0.8

        # Started flag (prevents double-start)
        self._started = False

        atexit.register(self._cleanup_atexit_wrapper)

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def start(self) -> bool:
        """
        Load models, open the audio stream, and begin background processing.

        Returns True on success, False on any failure (errors are logged).
        Safe to call only once per instance — subsequent calls are no-ops.
        """
        if self._started:
            debug_log("start() called on already-started bridge", "voice")
            return True

        # ---- Load openWakeWord -------------------------------------------
        print("[INIT] Loading openWakeWord engine...", flush=True)
        try:
            # Suppress openWakeWord's noisy import warnings on Windows
            import warnings
            warnings.filterwarnings(
                "ignore", category=UserWarning, module="openwakeword")

            import openwakeword
            from openwakeword.model import Model as OwwModel

            # Ensure model files exist locally; download on first run
            try:
                openwakeword.utils.download_models([self.wake_model_name])
            except Exception as e:
                debug_log(
                    f"Could not auto-download wake model "
                    f"({self.wake_model_name}): {e}",
                    "voice",
                )

            self.wake_model = OwwModel(
                wakeword_models=[self.wake_model_name],
                inference_framework="onnx",
            )
        except ImportError as e:
            print(f"[ERROR] openWakeWord not installed: {e}", file=sys.stderr,
                  flush=True)
            print("[HINT] Run: pip install openwakeword onnxruntime",
                  file=sys.stderr, flush=True)
            return False
        except Exception as e:
            print(f"[ERROR] Failed to load openWakeWord: {e}",
                  file=sys.stderr, flush=True)
            print(
                "[HINT] First run needs internet to download the wake model "
                "from GitHub. Check your connection.",
                file=sys.stderr, flush=True,
            )
            return False
        print(
            f"[INIT] openWakeWord ready (model={self.wake_model_name}, "
            f"threshold={self.wake_threshold})",
            flush=True,
        )

        # ---- Load Silero VAD ---------------------------------------------
        print(
            "[INIT] Loading Silero VAD (first run downloads from torch.hub)...",
            flush=True,
        )
        try:
            self.vad_model, vad_utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
                verbose=False,
            )
            VADIterator = vad_utils[3]
            self.vad_iterator = VADIterator(
                self.vad_model,
                threshold=VAD_THRESHOLD,
                sampling_rate=SAMPLE_RATE,
                min_silence_duration_ms=self.silence_ms,
                speech_pad_ms=100,
            )
        except Exception as e:
            print(f"[ERROR] Failed to load Silero VAD: {e}",
                  file=sys.stderr, flush=True)
            print(
                "[HINT] Check internet connection (first run pulls the model "
                "via torch.hub).",
                file=sys.stderr, flush=True,
            )
            return False
        print("[INIT] Silero VAD ready", flush=True)

        # ---- Warn if clipboard polling unavailable -----------------------
        if not self.watch_clipboard:
            print(
                "[WARN] pyperclip not installed — clipboard transcript "
                "capture is OFF. Wispr transcripts will not be dispatched. "
                "Run: pip install pyperclip",
                file=sys.stderr, flush=True,
            )

        # ---- Start key-worker thread -------------------------------------
        self._key_thread = threading.Thread(
            target=self._key_worker, name="WisprKeyWorker", daemon=True,
        )
        self._key_thread.start()

        # ---- Open audio stream -------------------------------------------
        print("[IDLE] Listening for 'Hey Jarvis'...", flush=True)
        try:
            self.audio_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=AUDIO_BLOCK_SIZE,
                device=self.device,
                callback=self._audio_callback,
            )
            self.audio_stream.start()
        except Exception as e:
            print(f"[ERROR] Failed to open audio input stream: {e}",
                  file=sys.stderr, flush=True)
            print(
                "[HINT] Check microphone permissions and device index "
                "(wispr_mic_device in config).",
                file=sys.stderr, flush=True,
            )
            return False

        self._started = True
        return True

    def pause(self) -> None:
        """Suspend wake-word detection (used by MUTE from the control bus).

        The audio stream stays open so we can resume instantly, but
        ``_process_wake`` short-circuits while paused. If currently
        DICTATING, we let the in-flight dictation complete naturally —
        we don't abort mid-utterance because that would leave Wispr Flow
        recording.
        """
        self._paused = True
        debug_log("WisprBridge paused (mic muted)", "voice")
        print("🔇 Wispr bridge paused — wake word ignored", flush=True)

    def resume(self) -> None:
        """Re-enable wake-word detection after a previous ``pause()``."""
        self._paused = False
        debug_log("WisprBridge resumed (mic unmuted)", "voice")
        print("🔊 Wispr bridge resumed — listening for 'Hey Jarvis'", flush=True)

    def trigger_now(self) -> bool:
        """Bypass wake detection and tap the hands-free shortcut now.

        Called by the lightning-bolt trigger button on the HUD. Returns
        True if dictation was started, False if a dictation was already
        in progress (caller decides whether to ignore or queue).
        """
        with self._state_lock:
            if self._state == State.DICTATING:
                debug_log("trigger_now: already DICTATING, ignoring", "voice")
                return False
        # Auto-unpause if muted — explicit trigger overrides mute.
        if self._paused:
            self.resume()
        print("⚡ Manual trigger via HUD — tapping hands-free shortcut",
              flush=True)
        self._start_dictation(score=1.0)
        return True

    def stop(self) -> None:
        """
        Shut down audio stream, release any held keys, and join worker
        threads. Idempotent — safe to call multiple times.
        """
        self.shutdown_event.set()

        # Cancel any pending hot-window timer
        with self._hot_window_lock:
            if self._hot_window_timer is not None:
                try:
                    self._hot_window_timer.cancel()
                except Exception:
                    pass
                self._hot_window_timer = None

        # Force-release any held keys
        try:
            with self._keys_lock:
                if self._keys_held:
                    self._force_release_locked()
                    print("[KEYS] Force-released Ctrl + Win + Space on cleanup",
                          flush=True)
        except Exception as e:
            print(f"[CLEANUP] Error releasing keys: {e}", file=sys.stderr,
                  flush=True)

        # Signal key worker to exit
        try:
            self._key_queue.put_nowait(KeyEvent.STOP)
        except Exception:
            pass

        # Close audio stream
        if self.audio_stream is not None:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None

        # Let GC handle the model
        self.wake_model = None

        # Join key worker
        if self._key_thread is not None and self._key_thread.is_alive():
            self._key_thread.join(timeout=1.0)

        self._started = False

    def enter_hot_window(self, duration_sec: Optional[float] = None) -> None:
        """
        Open a follow-up window during which the user can speak without
        repeating the wake word. Wake-word matching is bypassed; the next
        speech-onset detected by VAD will trigger dictation.

        Behaviour:
          * IDLE         -> HOT_WINDOW  (open a fresh window)
          * HOT_WINDOW   -> HOT_WINDOW  (extend / reset the existing timer)
          * DICTATING    -> no-op       (don't interrupt in-flight dictation)

        Config gate: when ``cfg.wispr_hot_window_sec == 0`` the feature is
        disabled and this method returns immediately.

        Args:
            duration_sec: How long the hot window stays open. Defaults to
                ``cfg.wispr_hot_window_sec``.
        """
        if duration_sec is None:
            duration_sec = self.hot_window_sec

        # Config-driven kill-switch: 0 disables follow-ups entirely.
        if duration_sec is None or duration_sec <= 0:
            debug_log(
                "enter_hot_window: disabled (wispr_hot_window_sec <= 0)",
                "voice",
            )
            return

        with self._state_lock:
            # Never interrupt an in-flight dictation. Re-entering from an
            # existing HOT_WINDOW is fine — we'll reset the timer below.
            if self._state == State.DICTATING:
                debug_log(
                    f"enter_hot_window ignored — state={self._state.value}",
                    "voice",
                )
                return
            previous_state = self._state
            self._state = State.HOT_WINDOW
            self._hot_window_until = time.monotonic() + float(duration_sec)

        if previous_state == State.HOT_WINDOW:
            print(
                f"🔥 Hot window extended for {duration_sec:.1f}s — "
                f"say a follow-up without 'Hey Jarvis'",
                flush=True,
            )
        else:
            print(
                f"🔥 Hot window active for {duration_sec:.1f}s — "
                f"say a follow-up without 'Hey Jarvis'",
                flush=True,
            )

        # Reset VAD so a stale "end" event doesn't immediately fire
        try:
            if self.vad_iterator is not None:
                self.vad_iterator.reset_states()
        except Exception as e:
            debug_log(f"VAD reset failed entering hot window: {e}", "voice")
        self._vad_buf.clear()

        # Cancel any previous timer and schedule a fresh one
        with self._hot_window_lock:
            if self._hot_window_timer is not None:
                try:
                    self._hot_window_timer.cancel()
                except Exception:
                    pass
            timer = threading.Timer(duration_sec, self._hot_window_expired)
            timer.name = "WisprHotWindowTimer"
            timer.daemon = True
            self._hot_window_timer = timer
            timer.start()

    def set_speaking(self, speaking: bool) -> None:
        """
        Record whether JARVIS itself is currently playing TTS.

        When True:
          - Record the flag (drives stop-pattern interrupt routing in
            :meth:`_dispatch_transcription`).
          - **Pause wake detection** so the bridge cannot trigger on JARVIS's
            own voice coming back through the microphone — the most common
            cause of phantom wakes ("after TTS ends a tune starts even though
            I never said Hey Jarvis").
          - Cancel any pending post-speak resume timer (a new TTS overrode
            the previous one).
          - Open a hot window so the user can interrupt mid-speech with a
            stop pattern — no-op when ``wispr_hot_window_sec <= 0``.

        When False:
          - Record the flag.
          - **Schedule a delayed resume** of wake detection (default 0.8s)
            so the tail of the TTS audio (room echo, reverb, speaker decay)
            can't falsely trigger the wake word immediately after the last
            sample plays.

        Thread-safe: callable from the TTS engaged/ended callbacks (which
        fire from the audio worker thread).
        """
        with self._speaking_lock:
            self._jarvis_speaking = bool(speaking)
            speaking_now = self._jarvis_speaking
        debug_log(f"set_speaking({speaking_now})", "voice")

        # Cancel any pending resume timer regardless of new state. If the
        # new state is True we don't want a stale resume to fire; if False
        # we'll schedule a fresh one below.
        if self._post_speak_resume_timer is not None:
            try:
                self._post_speak_resume_timer.cancel()
            except Exception:
                pass
            self._post_speak_resume_timer = None

        if speaking_now:
            # Suspend wake detection while JARVIS speaks. Even if the user
            # has no monitors/headphones with active output, openWakeWord
            # at threshold 0.1 has been observed firing on JARVIS's own
            # voice coming through the desktop mic.
            try:
                self.pause()
            except Exception as e:
                debug_log(f"pause failed inside set_speaking: {e!r}", "voice")
            try:
                self.enter_hot_window()
            except Exception as e:
                debug_log(
                    f"enter_hot_window failed inside set_speaking: {e!r}",
                    "voice",
                )
        else:
            # JARVIS just stopped speaking. Resume wake detection after a
            # short cooldown so the echo tail doesn't false-trigger the
            # wake model the instant playback ends.
            def _resume_after_cooldown():
                # Re-check the flag — a new TTS may have arrived during
                # the timer window. Read under the lock for a consistent
                # snapshot against a concurrent set_speaking write.
                with self._speaking_lock:
                    still_speaking = self._jarvis_speaking
                if still_speaking:
                    return
                try:
                    self.resume()
                except Exception as e:
                    debug_log(
                        f"resume failed inside post-speak cooldown: {e!r}",
                        "voice",
                    )

            self._post_speak_resume_timer = threading.Timer(
                self._post_speak_cooldown_sec, _resume_after_cooldown,
            )
            self._post_speak_resume_timer.daemon = True
            self._post_speak_resume_timer.start()
            debug_log(
                f"post-speak resume scheduled in {self._post_speak_cooldown_sec}s",
                "voice",
            )

    # ----------------------------------------------------------------------
    # Hot-window helpers
    # ----------------------------------------------------------------------

    def _hot_window_expired(self) -> None:
        """Timer callback — drop back to IDLE if no speech arrived."""
        with self._state_lock:
            if self._state != State.HOT_WINDOW:
                # Already transitioned elsewhere (e.g. into DICTATING).
                return
            self._state = State.IDLE
        with self._hot_window_lock:
            self._hot_window_timer = None
        print("[HOT] Hot-window expired — back to idle", flush=True)

    # ----------------------------------------------------------------------
    # Stop-pattern detection (Phase F)
    # ----------------------------------------------------------------------
    # Class-level — compiled once at import time. Matches an entire short
    # utterance whose ONLY content is an interrupt keyword (optionally
    # preceded by "Hey Jarvis"). EN: stop, quiet, shut up, enough.
    # EL: σταμάτα, σώπα, αρκετά, ησυχία (accented + unaccented variants).
    _STOP_PATTERN = re.compile(
        r"^(?:hey\s+jarvis[,\s]+)?"
        r"(?:stop|σταμάτα|σταματα|σώπα|σωπα|αρκετά|αρκετα|ησυχία|ησυχια|"
        r"quiet|shut\s+up|enough)"
        r"[\s.!?]*$",
        re.IGNORECASE,
    )

    def _matches_stop_pattern(self, text: str) -> bool:
        """Return True iff ``text`` is a pure stop/interrupt command.

        Conservative on purpose — we only match short utterances that are
        ENTIRELY a stop keyword (optionally prefixed by "Hey Jarvis").
        Anything longer (e.g. "stop the music and play something else")
        falls through to the normal transcription path so the cascade can
        handle the richer intent.
        """
        return bool(self._STOP_PATTERN.match((text or "").strip()))

    # ----------------------------------------------------------------------
    # Keyboard worker
    # ----------------------------------------------------------------------

    def _key_worker(self) -> None:
        while True:
            try:
                event = self._key_queue.get(timeout=0.2)
            except queue.Empty:
                if self.shutdown_event.is_set():
                    return
                continue

            if event is KeyEvent.STOP:
                return
            if event is KeyEvent.PRESS:
                self._do_press_keys()
            elif event is KeyEvent.RELEASE:
                self._do_release_keys()

    def _do_press_keys(self) -> None:
        """Start Wispr Flow's hands-free dictation by tapping Ctrl+Win+Space
        (the hands-free toggle shortcut). The keys are released immediately
        — Wispr Flow stays in hands-free mode until we tap the same combo
        again. ``_keys_held`` is reused as a "hands-free active" sentinel
        to prevent double-tapping (which would cancel mid-dictation)."""
        with self._keys_lock:
            if self._keys_held:
                return  # already in hands-free mode
            try:
                self._tap_hands_free_toggle_locked()
                self._keys_held = True  # sentinel — hands-free is now active
                debug_log("Tapped Ctrl+Win+Space (started hands-free dictation)", "voice")
            except Exception as e:
                print(f"[ERROR] Failed to start hands-free dictation: {e}",
                      file=sys.stderr, flush=True)
                self._force_release_locked()

    def _do_release_keys(self) -> None:
        """Stop Wispr Flow's hands-free dictation by tapping Ctrl+Win+Space
        a second time. Idempotent — if dictation was never started (defensive),
        the tap is skipped."""
        with self._keys_lock:
            if not self._keys_held:
                return  # nothing to stop
            try:
                self._tap_hands_free_toggle_locked()
                debug_log("Tapped Ctrl+Win+Space (stopped hands-free dictation)", "voice")
            except Exception as e:
                print(f"[ERROR] Failed to stop hands-free dictation cleanly: {e}",
                      file=sys.stderr, flush=True)
            finally:
                self._keys_held = False

    def _tap_hands_free_toggle_locked(self) -> None:
        """Tap Ctrl+Win+Space briefly. CALLER MUST HOLD ``self._keys_lock``.

        We press in the order Ctrl → Win → Space and release in the reverse
        order (Space → Win → Ctrl) with tiny gaps, mimicking what a human's
        fingers would do. Wispr Flow's keystroke detector listens for the
        Space press inside an active Ctrl+Win modifier combo and toggles
        hands-free dictation on/off in response.
        """
        self._keyboard.press(Key.ctrl)
        time.sleep(KEY_INTER_PRESS_DELAY)
        self._keyboard.press(Key.cmd)
        time.sleep(KEY_INTER_PRESS_DELAY)
        self._keyboard.press(Key.space)
        time.sleep(KEY_INTER_PRESS_DELAY)
        self._keyboard.release(Key.space)
        time.sleep(KEY_INTER_PRESS_DELAY)
        self._keyboard.release(Key.cmd)
        time.sleep(KEY_INTER_PRESS_DELAY)
        self._keyboard.release(Key.ctrl)

    def _force_release_locked(self) -> None:
        """Defensive cleanup. With tap-and-release semantics nothing should
        be held, but we defensively release Ctrl/Win/Space in case a tap
        was interrupted mid-flight, AND if we were in hands-free mode we
        tap one more time to toggle it off so we don't leave Wispr Flow
        recording silently after a crash."""
        for k in (Key.space, Key.cmd, Key.ctrl):
            try:
                self._keyboard.release(k)
            except Exception:
                pass
        if self._keys_held:
            try:
                self._tap_hands_free_toggle_locked()
            except Exception:
                pass
        self._keys_held = False

    # ----------------------------------------------------------------------
    # State transitions
    # ----------------------------------------------------------------------

    def _try_enter_dictating(self) -> Optional[State]:
        """
        Move into DICTATING from either IDLE or HOT_WINDOW. Cancels any
        active hot-window timer.

        Returns the PREVIOUS state on a successful transition (so callers
        can distinguish a fresh wake-trigger from a hot-window follow-up),
        or None if no transition occurred.
        """
        with self._state_lock:
            if self._state not in (State.IDLE, State.HOT_WINDOW):
                return None
            previous = self._state
            self._state = State.DICTATING
            self._dictation_start = time.monotonic()
        # Drop the hot-window timer since we transitioned into dictation.
        with self._hot_window_lock:
            if self._hot_window_timer is not None:
                try:
                    self._hot_window_timer.cancel()
                except Exception:
                    pass
                self._hot_window_timer = None
        return previous

    def _try_enter_idle(self) -> bool:
        with self._state_lock:
            if self._state != State.DICTATING:
                return False
            self._state = State.IDLE
            return True

    def _start_dictation(self, score: float) -> None:
        previous_state = self._try_enter_dictating()
        if previous_state is None:
            return
        if previous_state == State.HOT_WINDOW:
            print(
                f"🎙️  Hot follow-up triggered (vad_score={score:.2f}) — "
                f"starting dictation",
                flush=True,
            )
        else:
            print(
                f"[WAKE] 'Hey Jarvis' triggered (score={score:.2f}) — "
                f"starting dictation",
                flush=True,
            )

        # Tell JARVIS to start thinking-UI as early as possible
        if self.on_wake is not None:
            try:
                self.on_wake()
            except Exception as e:
                debug_log(f"on_wake callback raised: {e}", "voice")

        try:
            self.vad_iterator.reset_states()
        except Exception as e:
            debug_log(f"VAD reset failed: {e}", "voice")
        self._vad_buf.clear()

        # Snapshot the clipboard so the watcher knows what was there BEFORE
        # Wispr Flow writes the new transcription.
        if self.watch_clipboard:
            try:
                self._clipboard_baseline = pyperclip.paste() or ""
            except Exception as e:
                debug_log(f"Could not read clipboard baseline: {e}", "voice")
                self._clipboard_baseline = ""

        # Apply cooldown so the same trigger doesn't fire repeatedly
        self._wake_cooldown = WAKE_COOLDOWN_FRAMES
        self._key_queue.put(KeyEvent.PRESS)

    def _stop_dictation(self, reason: str) -> None:
        if not self._try_enter_idle():
            return
        self._key_queue.put(KeyEvent.RELEASE)
        self._wake_cooldown = 0  # allow immediate re-trigger
        if reason == "silence":
            print(f"[VAD] {self.silence_ms}ms silence — releasing keys",
                  flush=True)
        elif reason == "timeout":
            print(
                f"[TIMEOUT] Max dictation duration "
                f"({self.max_dictation_sec:.0f}s) reached — releasing keys",
                flush=True,
            )
        elif reason == "shutdown":
            print("[EXIT] Shutting down — releasing keys", flush=True)
        else:
            print(f"[STOP] Releasing keys (reason: {reason})", flush=True)

        # Spawn the post-dictation worker (clipboard polling + dispatch).
        # We always spawn on natural endings, even without clipboard, so
        # the on_dictation_end callback still fires after the wait.
        if reason in ("silence", "timeout"):
            threading.Thread(
                target=self._post_dictation_worker,
                args=(self._clipboard_baseline,),
                name="WisprPostDictationWorker",
                daemon=True,
            ).start()
        print("[IDLE] Listening for 'Hey Jarvis'...", flush=True)

        # Phase E: every successful dictation extends the hot window so
        # follow-up turns don't need a fresh wake word. Gated by
        # ``cfg.wispr_hot_window_sec`` — 0 disables the feature.
        if reason in ("silence", "timeout") and self.hot_window_sec > 0:
            try:
                self.enter_hot_window()
            except Exception as e:
                debug_log(
                    f"enter_hot_window after dictation failed: {e!r}",
                    "voice",
                )

    # ----------------------------------------------------------------------
    # Transcription capture (via clipboard) + dispatch
    # ----------------------------------------------------------------------

    def _post_dictation_worker(self, baseline: str) -> None:
        """
        Runs after each completed dictation. Polls the clipboard for up to
        ``self.clipboard_wait_sec`` waiting for Wispr Flow to write the
        transcript. Dispatches via callbacks; always fires
        ``on_dictation_end(captured)`` once finished — ``captured`` is True
        when a clipboard transcript was seen (and dispatched), False when
        none arrived within the wait window or clipboard polling is off.
        """
        captured = False
        try:
            if self.watch_clipboard:
                deadline = time.monotonic() + self.clipboard_wait_sec
                while time.monotonic() < deadline:
                    if self.shutdown_event.is_set():
                        return
                    try:
                        current = pyperclip.paste() or ""
                    except Exception:
                        time.sleep(CLIPBOARD_POLL_INTERVAL)
                        continue
                    if current != baseline and current.strip():
                        self._dispatch_transcription(current)
                        captured = True
                        break
                    time.sleep(CLIPBOARD_POLL_INTERVAL)
                if not captured and not self.shutdown_event.is_set():
                    debug_log(
                        f"No transcript appeared within "
                        f"{self.clipboard_wait_sec:.0f}s",
                        "voice",
                    )
            else:
                # No clipboard polling — just wait long enough for Wispr Flow
                # to finish auto-typing before we erase it.
                time.sleep(self.clipboard_wait_sec)
        finally:
            if self.on_dictation_end is not None:
                try:
                    self.on_dictation_end(captured)
                except Exception as e:
                    debug_log(f"on_dictation_end callback raised: {e}",
                              "voice")

    def _dispatch_transcription(self, text: str) -> None:
        """
        Called once per dictation when a new clipboard value is detected.
        Logs a [HEARD] preview, erases the auto-typed copy (if configured),
        then invokes the user-supplied on_transcription callback.

        Phase F: when JARVIS is currently speaking AND the transcript is
        an interrupt-only command (e.g. "stop", "σταμάτα"), fire
        :attr:`on_stop` BEFORE the regular transcription callback so the
        listener can tear down the in-flight TTS as quickly as possible.
        ``on_transcription`` is then called either way — the listener is
        free to early-return when reset_everything() has just fired.
        """
        preview = text.strip()
        if len(preview) > CLIPBOARD_PREVIEW_CHARS:
            preview = preview[:CLIPBOARD_PREVIEW_CHARS].rstrip() + "..."
        print(f'[HEARD] "{preview}"', flush=True)

        if self.suppress_autotype:
            self._erase_autotyped_text(text)

        # Phase F: route stop-keywords through on_stop while speaking.
        # Snapshot the speaking flag under the lock — it's written from the
        # TTS thread while this runs on the post-dictation worker thread.
        with self._speaking_lock:
            speaking_now = self._jarvis_speaking
        is_stop = self._matches_stop_pattern(text)
        if speaking_now and is_stop:
            print("⏹  Stop pattern detected during TTS — interrupting", flush=True)
            if self.on_stop is not None:
                try:
                    self.on_stop()
                except Exception as e:
                    print(
                        f"[ERROR] on_stop callback raised: {e}",
                        file=sys.stderr, flush=True,
                    )

        # Invoke the JARVIS-side handler last so the user sees the
        # auto-typed text gone before any downstream UI updates fire.
        # The listener decides whether to interrupt-only or
        # interrupt-and-process (e.g. for "Hey Jarvis, stop and play X").
        try:
            self.on_transcription(text)
        except Exception as e:
            print(f"[ERROR] on_transcription callback raised: {e}",
                  file=sys.stderr, flush=True)

    def _erase_autotyped_text(self, text: str) -> None:
        """
        Send Backspace N times to delete what Wispr Flow just auto-typed
        into whichever app the user had focused. The transcription is still
        preserved in the clipboard and the [HEARD] log, so nothing is lost.

        Data-loss guard: if the transcript is longer than
        ``cfg.wispr_erase_max_chars`` (default 300) we SKIP erasing entirely.
        Spraying hundreds of backspaces into whatever window happens to hold
        focus risks shredding the user's content if focus has moved away from
        Wispr Flow's insertion point — better to leave the auto-typed copy in
        place than to delete the wrong thing.
        """
        n = len(text)
        if n == 0:
            return
        max_chars = int(getattr(self.cfg, "wispr_erase_max_chars", 300))
        if n > max_chars:
            debug_log(
                f"Skipping auto-type erase: {n} chars exceeds cap "
                f"({max_chars}) — refusing to spray backspaces into a "
                f"possibly-wrong window",
                "voice",
            )
            return
        try:
            for _ in range(n):
                self._keyboard.press(Key.backspace)
                self._keyboard.release(Key.backspace)
                # tiny pause so apps don't drop keys under burst
                time.sleep(0.003)
            debug_log(f"Erased {n} auto-typed character(s)", "voice")
        except Exception as e:
            debug_log(f"Failed to erase auto-typed text: {e}", "voice")

    # ----------------------------------------------------------------------
    # Audio processing
    # ----------------------------------------------------------------------

    def _process_wake(self, audio_f32: np.ndarray) -> None:
        """
        Buffer audio as int16 PCM and run openWakeWord in 1280-sample frames.

        While in HOT_WINDOW state we skip the wake-model entirely — the
        VAD path is the one allowed to trigger dictation.

        When ``self._paused`` is True (MUTE from the control bus) we
        drain the input buffer but don't call the wake model — saves CPU
        AND guarantees no wake fires while muted.
        """
        if self._paused:
            # Drain so we don't accumulate a buffer that would replay on
            # resume — the user expects mute to be silent, not delayed.
            self._wake_buf.clear()
            return

        pcm = np.clip(audio_f32 * 32767.0, -32768, 32767).astype(np.int16)
        self._wake_buf.extend(pcm.tolist())

        while len(self._wake_buf) >= WAKE_FRAME_SIZE:
            frame = np.asarray(self._wake_buf[:WAKE_FRAME_SIZE],
                               dtype=np.int16)
            del self._wake_buf[:WAKE_FRAME_SIZE]

            # Decrement cooldown each frame regardless
            if self._wake_cooldown > 0:
                self._wake_cooldown -= 1

            try:
                predictions = self.wake_model.predict(frame)
            except Exception as e:
                print(f"[ERROR] Wake model error: {e}",
                      file=sys.stderr, flush=True)
                return

            # Only consider triggers when truly idle and not in cooldown.
            # HOT_WINDOW intentionally skips the wake check — the user is
            # in a follow-up turn.
            with self._state_lock:
                is_idle = self._state == State.IDLE
            if not is_idle or self._wake_cooldown > 0:
                continue

            # predictions is dict {model_name: float in [0,1]}
            for _model_name, score in predictions.items():
                if score >= self.wake_threshold:
                    self._start_dictation(float(score))
                    break  # only trigger once per frame

    def _process_vad(self, audio_f32: np.ndarray) -> None:
        """
        Feed Silero VAD. In DICTATING state we look for an "end" event
        (the trailing-silence boundary) to release the keys. In HOT_WINDOW
        state we look for a "start" event (speech onset) to begin dictation
        without a wake word.
        """
        self._vad_buf.extend(audio_f32.tolist())

        while len(self._vad_buf) >= VAD_FRAME_SIZE:
            window = self._vad_buf[:VAD_FRAME_SIZE]
            del self._vad_buf[:VAD_FRAME_SIZE]

            tensor = torch.tensor(window, dtype=torch.float32)
            try:
                event = self.vad_iterator(tensor, return_seconds=True)
            except Exception as e:
                print(f"[ERROR] VAD processing error: {e}",
                      file=sys.stderr, flush=True)
                continue

            if event is None:
                continue

            # Snapshot current state for branching
            with self._state_lock:
                current_state = self._state

            if current_state == State.HOT_WINDOW:
                # Hot-window: any speech onset triggers dictation directly.
                if "start" in event:
                    # Instant barge-in: if JARVIS is mid-speech, tear down
                    # TTS at speech onset rather than waiting for Wispr's
                    # cloud + clipboard round-trip (seconds of latency).
                    # We still proceed into dictation so the user's actual
                    # words are captured.
                    with self._speaking_lock:
                        speaking_now = self._jarvis_speaking
                    barge_in = bool(
                        getattr(self.cfg, "wispr_barge_in_interrupt", True))
                    if speaking_now and barge_in and self.on_stop is not None:
                        print("⏹  Speech onset during TTS — barging in",
                              flush=True)
                        try:
                            self.on_stop()
                        except Exception as e:
                            # Never let a callback crash the audio thread.
                            debug_log(
                                f"on_stop (barge-in) raised: {e!r}", "voice")
                    print("[HOT] Speech detected in hot-window — "
                          "starting dictation", flush=True)
                    self._start_dictation(score=1.0)
                    return
            elif current_state == State.DICTATING:
                if "end" in event:
                    # Suppress early VAD-end events so the user has time to
                    # actually start speaking after the wake word.
                    elapsed = time.monotonic() - self._dictation_start
                    if elapsed < self.min_dictation_sec:
                        continue
                    self._stop_dictation(reason="silence")
                    return

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if self.shutdown_event.is_set():
            return

        if status:
            if not (status.input_overflow or status.input_underflow):
                debug_log(f"Audio stream status: {status}", "voice")

        if indata.ndim > 1:
            audio = np.ascontiguousarray(indata[:, 0], dtype=np.float32)
        else:
            audio = np.ascontiguousarray(indata, dtype=np.float32).flatten()

        # Always feed wake-word detector (HOT_WINDOW state short-circuits
        # the trigger check inside _process_wake itself).
        self._process_wake(audio)

        with self._state_lock:
            current_state = self._state
            elapsed = (time.monotonic() - self._dictation_start
                       if current_state == State.DICTATING else 0.0)

        if current_state == State.DICTATING:
            if elapsed >= self.max_dictation_sec:
                self._stop_dictation(reason="timeout")
            else:
                self._process_vad(audio)
        elif current_state == State.HOT_WINDOW:
            # Drive VAD so we can detect speech-onset without a wake word.
            self._process_vad(audio)

    # ----------------------------------------------------------------------
    # Cleanup hook
    # ----------------------------------------------------------------------

    def _cleanup_atexit_wrapper(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
