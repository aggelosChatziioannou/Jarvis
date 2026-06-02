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
from .wispr_state import WisprStateProbe


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
# Silent frames fed to openWakeWord at startup (and on unmute) so its stateful
# classifier window is primed before the first real "Hey Jarvis" — mirrors the
# PRIME_SEC warmup in _recall_check.py. ~1.5s at 80ms/frame (>=16 to fill the
# 16-embedding window).
WAKE_PRIME_FRAMES = 19
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
DEFAULT_WAKE_RMS_FLOOR = 0.0     # ungained int16 RMS trigger gate; 0.0 = off (far-field-safe; model self-rejects silence)
DEFAULT_WAKE_CONSEC_FRAMES = 2   # consecutive frames >= threshold required to fire (debounce; 1 = legacy single-frame)
DEFAULT_SILENCE_MS = 800
DEFAULT_MIN_DICTATION_SEC = 1.0
DEFAULT_MAX_DICTATION_SEC = 30
DEFAULT_CLIPBOARD_WAIT_SEC = 6.0
DEFAULT_HOT_WINDOW_SEC = 0.0     # 0 = follow-ups OFF; Wispr opens only on wake word or the lightning trigger (never auto after a reply)
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


# Map config combo-key names -> pynput Key objects. Single-character names
# (letters/digits) are passed through as literal character keys at tap time.
_COMBO_KEYS = {
    "ctrl": Key.ctrl, "control": Key.ctrl,
    "win": Key.cmd, "cmd": Key.cmd, "super": Key.cmd, "meta": Key.cmd,
    "alt": Key.alt, "option": Key.alt, "altgr": Key.alt_gr,
    "shift": Key.shift,
    "space": Key.space,
    "enter": Key.enter, "return": Key.enter,
    "tab": Key.tab,
    "esc": Key.esc, "escape": Key.esc,
}


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
        on_dictation_end: Optional[Callable[..., None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_wispr_unavailable: Optional[Callable[[], None]] = None,
        state_probe: Optional["WisprStateProbe"] = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        # ---- Callbacks (invoked from background threads) ------------------
        self.on_transcription = on_transcription
        self.on_wake = on_wake
        # Fired once per dictation when the post-dictation worker finishes.
        # Receives ``captured: bool`` (and an optional ``reason`` str) — True
        # when a clipboard transcript was captured within the wait window (i.e.
        # on_transcription also fired), False when none arrived (timeout/off).
        # The listener uses this to decide whether to re-arm or recover.
        self.on_dictation_end = on_dictation_end
        # Fired when a stop pattern ('stop', 'σταμάτα', ...) is detected
        # while JARVIS is speaking. Listener uses this to interrupt TTS.
        self.on_stop = on_stop
        # Fired when a dictation START tap could not be confirmed to have put
        # Wispr Flow into recording (closed-loop only). The listener uses this
        # to show an honest "Wispr did not start" instead of a false "listening".
        self.on_wispr_unavailable = on_wispr_unavailable

        # Injectable clock seams so the confirm-poll and the min-tap-gap are
        # testable without wall-clock waits.
        self._monotonic = monotonic
        self._sleep = sleep

        # ---- Config (read defensively — Phase B may not have populated
        # these fields yet) -------------------------------------------------
        self.cfg = cfg
        self.wake_model_name = getattr(
            cfg, "wispr_wake_model", DEFAULT_WAKE_MODEL)
        self.wake_threshold = float(getattr(
            cfg, "wispr_wake_threshold", DEFAULT_WAKE_THRESHOLD))
        # Software gain applied to the wake-detection copy of the audio ONLY
        # (never the dictation/transcript path), so a weak/distant "Hey Jarvis"
        # is amplified into openWakeWord's useful range. 1.0 = no change.
        self.wake_gain = float(getattr(cfg, "wispr_wake_gain", 1.0))
        # Below this ungained int16 RMS a wake frame is treated as silence and
        # openWakeWord is skipped (recall-safe phantom-wake guard). See
        # _process_wake.
        self._wake_rms_floor = float(getattr(
            cfg, "wispr_wake_rms_floor", DEFAULT_WAKE_RMS_FLOOR))
        # Debounce: require this many CONSECUTIVE frames at/above threshold
        # before firing, so a single noise/echo spike (e.g. the observed 0.32
        # phantom) can't trigger a wake. ``_wake_consec`` counts the current run
        # and is reset whenever the run breaks (sub-threshold frame, silence
        # gate, or leaving IDLE). 1 reproduces the legacy single-frame trigger.
        self._wake_consec_frames = max(1, int(getattr(
            cfg, "wispr_wake_consec_frames", DEFAULT_WAKE_CONSEC_FRAMES)))
        self._wake_consec = 0
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
        # Privacy: restore the user's pre-wake clipboard after dispatching the
        # transcript so the spoken text doesn't linger on the clipboard / in
        # Windows Win+V history. Default on; opt out for users who paste it.
        self.restore_clipboard = bool(getattr(cfg, "wispr_restore_clipboard", True))

        # ---- Closed-loop synchronisation + cheap guards -------------------
        # The bridge drives Wispr with a single TOGGLE hotkey and cannot, on its
        # own, know whether a tap landed. With closed-loop on we reconcile every
        # tap against Wispr's REAL recording state via ``WisprStateProbe`` (a
        # local mic-usage read), so a missed/extra tap self-corrects instead of
        # inverting the mapping for the rest of the session. Fail-open: when the
        # probe can't tell (``is_recording() -> None``) we keep the old
        # belief-only behaviour, so this is never worse than before.
        self._closed_loop = bool(getattr(cfg, "wispr_closed_loop_enabled", True))
        self._confirm_timeout_sec = float(getattr(
            cfg, "wispr_confirm_timeout_sec", 1.2))
        self._min_tap_gap_sec = float(getattr(cfg, "wispr_min_tap_gap_sec", 0.5))
        self._clipboard_grace_sec = float(getattr(
            cfg, "wispr_clipboard_grace_sec", 2.0))
        combo = getattr(cfg, "wispr_hands_free_combo", None)
        self._hands_free_combo = self._normalise_combo(combo)
        if state_probe is not None:
            self._state_probe = state_probe
        elif self._closed_loop:
            self._state_probe = WisprStateProbe()
        else:
            # Closed-loop disabled -> a probe that always says "unknown", so the
            # bridge stays on the fail-open belief-only path.
            self._state_probe = WisprStateProbe(reader=lambda: None)
        # Last toggle-tap timestamp (min-tap-gap guard).
        self._last_tap_ts = 0.0

        # Wake mic = the persisted audio-input selection (by stable endpoint id,
        # friendly name as fallback) resolved to a sounddevice index. Resolved
        # here for construction and AGAIN in start()/reconnect so a device that
        # (re)appears later is picked up. None = currently absent or unset, in
        # which case the stream falls open to the PortAudio default mic.
        self.device = self._resolve_mic_device()

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
        # OS clipboard sequence number at wake time (Windows). Lets us detect an
        # identical re-utterance (same text) because the sequence still advances.
        self._clipboard_baseline_seq: Optional[int] = None
        # Monotonic counter bumped by :meth:`abort` (HUD STOP). A post-dictation
        # worker captures the value at spawn and DROPS its transcript if the
        # counter has since advanced — so audio heard around a STOP never
        # reaches the consumer.
        self._abort_generation: int = 0

        # Audio stream
        self.audio_stream: Optional[sd.InputStream] = None

        # Two INDEPENDENT reasons wake detection may be suspended. They must
        # never share a flag: collapsing them let the post-speak resume (after
        # JARVIS talks) silently lift a user MUTE.
        #   _user_muted   — user MUTE from the control bus (pause/resume).
        #   _speak_paused — transient: JARVIS is speaking / echo-tail cooldown.
        # The audio stream stays open in both cases (instant resume); only
        # ``_process_wake`` short-circuits. In-flight dictations finish.
        self._user_muted = False
        self._speak_paused = False

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

        # Serialises reconnect() so a burst of device-change events can't race
        # the stream open/close against itself.
        self._reconnect_lock = threading.Lock()

        atexit.register(self._cleanup_atexit_wrapper)

    # ----------------------------------------------------------------------
    # Mic device resolution
    # ----------------------------------------------------------------------

    def _resolve_mic_device(self) -> Optional[Any]:
        """Resolve the wake mic to a sounddevice index from the persisted
        audio-input selection.

        Resolution order:
          1. ``cfg.audio_input_endpoint_id`` / ``cfg.audio_input_name`` (the new
             redesign keys) -> ``audio_devices.resolve_endpoint_to_sd_index(...,
             kind="input")``. When EITHER key is set we use ONLY this path: a
             ``None`` result means the chosen device is currently absent, so we
             return ``None`` (treated as no-device, ready to reconnect when it
             returns) rather than silently dropping back to the legacy device.
          2. ``cfg.wispr_mic_device`` (legacy key) is a FINAL fallback, used
             only when both new keys are empty, matched to an index on the input
             flow. Preserves old configs that never recorded an endpoint id.

        Returns ``None`` when nothing is selected or the selection is absent;
        the caller opens the stream against PortAudio's default mic in that
        case. Fail-open: any error -> ``None``.
        """
        try:
            from ..output import audio_devices
        except Exception as e:  # pragma: no cover - defensive import guard
            debug_log(
                f"_resolve_mic_device: audio_devices import failed ({e!r})",
                "voice",
            )
            return None

        endpoint_id = getattr(self.cfg, "audio_input_endpoint_id", "") or ""
        name = getattr(self.cfg, "audio_input_name", "") or ""

        try:
            if endpoint_id or name:
                idx = audio_devices.resolve_endpoint_to_sd_index(
                    endpoint_id, name, kind="input"
                )
                if idx is None:
                    debug_log(
                        "_resolve_mic_device: input device disconnected "
                        f"(id={endpoint_id!r}, name={name!r}) — no-device, "
                        "will reconnect when it returns",
                        "voice",
                    )
                else:
                    debug_log(
                        f"_resolve_mic_device: id={endpoint_id!r} "
                        f"name={name!r} -> sd index {idx}",
                        "voice",
                    )
                return idx

            # No new-key selection — fall back to the legacy device value.
            legacy = getattr(self.cfg, "wispr_mic_device", DEFAULT_MIC_DEVICE)
            if legacy is None or (isinstance(legacy, str) and legacy.strip() == ""):
                return None
            # Numeric legacy value -> use directly as an index.
            if isinstance(legacy, int) or (
                isinstance(legacy, str) and legacy.lstrip("-").isdigit()
            ):
                return int(legacy)
            idx = audio_devices.match_name_to_sd_index(str(legacy), kind="input")
            debug_log(
                f"_resolve_mic_device: legacy wispr_mic_device={legacy!r} "
                f"-> sd index {idx}",
                "voice",
            )
            return idx
        except Exception as e:  # pragma: no cover - defensive fail-open
            debug_log(f"_resolve_mic_device raised: {e!r}", "voice")
            return None

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
        # Re-resolve the mic fresh at start() so a device that (re)appeared
        # after construction is picked up. None -> the selected device is
        # currently absent (or unset); we open on the PortAudio default mic so
        # the bridge still runs and reconnects when the chosen device returns,
        # rather than crashing.
        self.device = self._resolve_mic_device()
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
            # Prime the stateful wake model BEFORE going live so the first
            # "Hey Jarvis" after boot hits a full classifier window, and so no
            # audio-callback predict() races the prime loop.
            self._prime_wake_model()
            # Reconcile against Wispr's real state before accepting wakes: if
            # Wispr was left recording (e.g. across a crash/restart), force it
            # OFF to a known IDLE so the first dictation isn't inverted.
            self._reconcile_initial_state()
            self.audio_stream.start()
        except Exception as e:
            print(f"[ERROR] Failed to open audio input stream: {e}",
                  file=sys.stderr, flush=True)
            print(
                "[HINT] Check microphone permissions and the selected input "
                "device (Audio I/O settings).",
                file=sys.stderr, flush=True,
            )
            return False

        self._started = True
        return True

    def reconnect(self) -> bool:
        """Re-resolve the wake mic and reopen the input stream if it changed.

        Called by the Core Audio device watcher (debounced) when Windows reports
        a device change, so a chosen mic that was unplugged is picked up again
        when it returns, and a removed mic falls back to the PortAudio default.
        No-op (returns False) when the bridge has not started, or when the
        resolved sounddevice index is unchanged and a stream is already open.

        Opens the NEW stream before retiring the old one, so if the reopen
        fails the existing stream keeps running. Fail-open: never raises; on any
        error the existing stream is left intact and the bridge keeps running.
        """
        if not self._started:
            return False
        with self._reconnect_lock:
            try:
                new_device = self._resolve_mic_device()
            except Exception as e:  # pragma: no cover - defensive
                debug_log(f"reconnect: resolve raised ({e!r})", "voice")
                return False
            if new_device == self.device and self.audio_stream is not None:
                return False  # selection unchanged and still open — nothing to do

            debug_log(f"reconnect: wake mic {self.device!r} -> {new_device!r}", "voice")
            old = self.audio_stream
            try:
                new_stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=AUDIO_BLOCK_SIZE,
                    device=new_device,
                    callback=self._audio_callback,
                )
                new_stream.start()
            except Exception as e:
                debug_log(
                    f"reconnect: reopen failed ({e!r}); keeping existing stream",
                    "voice",
                )
                return False

            # New stream is live — swap it in, then retire the old one.
            self.device = new_device
            self.audio_stream = new_stream
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass
                try:
                    old.close()
                except Exception:
                    pass
            debug_log(
                f"reconnect: wake mic reopened on device {new_device!r}", "voice"
            )
            return True

    def abort(self) -> None:
        """Cancel the current interaction NOW (HUD STOP button).

        Unlike :meth:`pause` (which only mutes future wakes and lets an
        in-flight dictation finish), this is the hard cancel the STOP button
        needs: it (1) bumps the abort generation so any in-flight
        post-dictation worker DROPS its transcript instead of dispatching it to
        the assistant, (2) drops any DICTATING/HOT_WINDOW state back to IDLE and
        cancels the hot-window timer, and (3) forces Wispr Flow OFF to a known
        idle. Best-effort and fail-open: never raises into the caller.
        """
        # (1) Invalidate any transcript captured around the STOP.
        with self._keys_lock:
            self._abort_generation += 1
        # (2) Leave DICTATING/HOT_WINDOW immediately.
        with self._state_lock:
            self._state = State.IDLE
        with self._hot_window_lock:
            if self._hot_window_timer is not None:
                try:
                    self._hot_window_timer.cancel()
                except Exception:
                    pass
                self._hot_window_timer = None
        self._wake_cooldown = 0
        # (3) Force Wispr recording OFF (closed-loop level-seek; fail-open).
        try:
            self._ensure_recording(False)
        except Exception as e:
            debug_log(f"abort: force-off raised: {e!r}", "voice")
        print("⏹  Aborted — Wispr stopped and current input discarded", flush=True)

    def pause(self) -> None:
        """Suspend wake-word detection on a user MUTE (control bus).

        Sets the user-mute flag, which is INDEPENDENT of the transient
        speaking-pause (``_speak_paused``) raised while JARVIS talks. The two
        must never share a flag, otherwise the post-speak resume would
        silently lift a user's mute. The audio stream stays open so we can
        resume instantly, but ``_process_wake`` short-circuits while muted. If
        currently DICTATING, we let the in-flight dictation complete naturally.
        """
        self._user_muted = True
        debug_log("WisprBridge paused (mic muted)", "voice")
        print("🔇 Wispr bridge paused — wake word ignored", flush=True)

    def resume(self) -> None:
        """Clear the user-mute flag after a previous ``pause()`` (control bus).

        Only the user MUTE is lifted here; the speaking-pause is managed
        separately by :meth:`set_speaking`.
        """
        self._user_muted = False
        # The classifier window went stale while muted (we stopped feeding the
        # model). Re-prime so the first "Hey Jarvis" after unmute hits a full
        # window instead of cold-starting.
        self._prime_wake_model()
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
        # Explicit manual trigger overrides BOTH the user mute and any
        # transient speaking-pause.
        if self._user_muted or self._speak_paused:
            self._user_muted = False
            self._speak_paused = False
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
            # Suspend wake detection while JARVIS speaks via the dedicated
            # speaking-pause flag — NOT the user-mute flag. Even with no
            # monitors/headphones, openWakeWord at a low threshold has been
            # observed firing on JARVIS's own voice through the desktop mic.
            self._speak_paused = True
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
                # Lift ONLY the speaking-pause. A user MUTE (``_user_muted``)
                # set from the control bus MUST survive JARVIS speaking — it is
                # cleared solely by UNMUTE/TRIGGER, never by this timer. This is
                # the fix for "mute stops working after Jarvis talks".
                self._speak_paused = False
                debug_log(
                    "post-speak cooldown elapsed — speaking-pause lifted",
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
        """Ensure Wispr Flow is RECORDING (closed-loop start).

        Routes through :meth:`_ensure_recording`, which reads Wispr's real
        recording state and taps the hands-free toggle only when needed,
        confirming the result. When the start cannot be confirmed, surface it
        (Wispr likely never started) rather than silently believing it did."""
        try:
            ok = self._ensure_recording(True)
        except Exception as e:
            print(f"[ERROR] Failed to start hands-free dictation: {e}",
                  file=sys.stderr, flush=True)
            with self._keys_lock:
                self._force_release_locked()
            return
        if not ok:
            self._handle_unconfirmed_start()

    def _do_release_keys(self) -> None:
        """Ensure Wispr Flow is NOT recording (closed-loop stop).

        Routes through :meth:`_ensure_recording`. Idempotent: if Wispr is
        already idle, no tap is sent."""
        try:
            self._ensure_recording(False)
        except Exception as e:
            print(f"[ERROR] Failed to stop hands-free dictation cleanly: {e}",
                  file=sys.stderr, flush=True)

    def _handle_unconfirmed_start(self) -> None:
        """A START tap could not be confirmed to have put Wispr into recording.

        Rather than sit in DICTATING with the HUD falsely showing "listening"
        while Wispr never started, revert to IDLE, allow an immediate re-trigger,
        and fire ``on_wispr_unavailable`` so the listener can show an honest
        "Wispr did not start" instead of a transcript that will never arrive."""
        debug_log(
            "ensure_recording: dictation start could not be confirmed — "
            "Wispr Flow may not have started recording; reverting to idle",
            "voice",
        )
        # Revert the optimistic DICTATING transition so we don't wait on a
        # transcript that will never come, and re-arm the wake trigger.
        self._try_enter_idle()
        self._wake_cooldown = 0
        if self.on_wispr_unavailable is not None:
            try:
                self.on_wispr_unavailable()
            except Exception as e:
                debug_log(f"on_wispr_unavailable callback raised: {e!r}", "voice")

    # ----------------------------------------------------------------------
    # Closed-loop level-seeking
    # ----------------------------------------------------------------------

    def _read_probe(self) -> Optional[bool]:
        """Wispr's real recording state, or None when it cannot be determined."""
        try:
            return self._state_probe.is_recording()
        except Exception:
            return None

    def _ensure_recording(self, target: bool) -> bool:
        """Bring Wispr Flow's recording state to ``target``, verified.

        Level-seeking, not blind toggling:
          * probe says ``None`` (unknown)  -> fall back to belief-only toggling
            (today's behaviour) so we are never worse than before.
          * observed == target             -> reconcile belief, send NO tap
            (this is the inversion-healing step).
          * observed != target             -> tap once, confirm; on failure tap
            once more and re-confirm; still failing -> return False.

        Runs on the key-worker thread (called from _do_press/_do_release), so
        the bounded confirm-poll never blocks the audio callback. Returns True
        when the target state is reached/believed, False when a needed tap could
        not be confirmed.
        """
        with self._keys_lock:
            observed = self._read_probe()
            if observed is None:
                return self._toggle_to_belief_locked(target)
            if observed == target:
                self._keys_held = target
                return True
            # Observed state differs from target -> a tap is required.
            self._emit_toggle_tap_locked()
            if self._confirm_locked(target):
                self._keys_held = target
                return True
            debug_log(
                f"ensure_recording: tap did not reach target={target}; re-tapping",
                "voice",
            )
            self._emit_toggle_tap_locked()
            if self._confirm_locked(target):
                self._keys_held = target
                return True
            debug_log(
                f"ensure_recording: could not reach target={target} after re-tap",
                "voice",
            )
            return False

    def _reconcile_initial_state(self) -> None:
        """At startup, align belief with Wispr's real state.

        If Wispr is found already recording (e.g. it was left on across a
        crash/restart, or auto-stopped logic left it inverted), force it OFF to
        a known IDLE synchronously — NOT via the key queue (the worker may not
        be draining yet) and exempt from the min-tap gap (there is no prior tap
        to gate against). Fail-open: when the probe can't tell, leave the
        construction-time belief (``_keys_held = False``) untouched."""
        observed = self._read_probe()
        if observed is None:
            return
        with self._keys_lock:
            if observed:
                self._tap_hands_free_toggle_locked()  # synchronous force-off
                self._keys_held = False
                debug_log(
                    "startup: Wispr was recording -> forced OFF to a known idle",
                    "voice",
                )
            else:
                self._keys_held = False

    def _toggle_to_belief_locked(self, target: bool) -> bool:
        """Fail-open path (probe unknown): tap iff the local belief differs.

        Mirrors the historical belief-only behaviour exactly — a single tap to
        start when not held, a single tap to stop when held — so a machine
        without an observable Wispr state behaves as it did before, plus the
        cheap guards (configurable combo, min inter-tap gap). CALLER HOLDS LOCK."""
        if target:
            if self._keys_held:
                return True
            self._emit_toggle_tap_locked()
            self._keys_held = True
            return True
        if not self._keys_held:
            return True
        self._emit_toggle_tap_locked()
        self._keys_held = False
        return True

    def _confirm_locked(self, target: bool) -> bool:
        """Poll Wispr's real state until it equals ``target`` or we time out.

        CALLER HOLDS LOCK. If the probe goes blind (returns None) for the whole
        window and never contradicts the target, we do NOT claim failure — a
        blind corrective tap could itself invert state."""
        deadline = self._monotonic() + self._confirm_timeout_sec
        saw_definite = False
        while self._monotonic() < deadline:
            obs = self._read_probe()
            if obs == target:
                return True
            if obs is not None:
                saw_definite = True
            self._sleep(0.05)
        obs = self._read_probe()
        if obs == target:
            return True
        if not saw_definite and obs is None:
            return True
        return False

    def _emit_toggle_tap_locked(self) -> None:
        """Tap the hands-free toggle, honouring the minimum inter-tap gap.

        Wispr's own docs note that starting/stopping very quickly can freeze
        Flow with the bubble stuck on 'Listening'; we enforce a minimum quiet
        interval between consecutive taps. CALLER HOLDS LOCK."""
        gap = self._min_tap_gap_sec
        if gap > 0:
            since = self._monotonic() - self._last_tap_ts
            if 0.0 <= since < gap:
                self._sleep(gap - since)
        self._tap_hands_free_toggle_locked()
        self._last_tap_ts = self._monotonic()

    def _tap_hands_free_toggle_locked(self) -> None:
        """Tap the configured hands-free chord briefly. CALLER HOLDS LOCK.

        Presses each key of ``wispr_hands_free_combo`` in order and releases in
        reverse order with tiny gaps, mimicking a human's fingers. Wispr Flow's
        keystroke detector toggles hands-free dictation on the chord. The combo
        is configurable so it can match a user's actual Wispr binding (a hard-
        coded chord that does not match makes every tap a silent no-op)."""
        keys = self._combo_keys()
        for k in keys:
            self._keyboard.press(k)
            time.sleep(KEY_INTER_PRESS_DELAY)
        for k in reversed(keys):
            self._keyboard.release(k)
            time.sleep(KEY_INTER_PRESS_DELAY)

    def _combo_keys(self) -> list:
        """Resolve the configured combo names to pynput keys/chars.

        Unknown names are dropped (with a log); if nothing resolves we fall
        back to the default Ctrl+Win+Space so a bad config can't disable taps."""
        keys: list = []
        for name in self._hands_free_combo:
            k = _COMBO_KEYS.get(name)
            if k is not None:
                keys.append(k)
            elif len(name) == 1:
                keys.append(name)  # a literal character key
            else:
                debug_log(f"unknown hands-free combo key '{name}' — skipped", "voice")
        if not keys:
            debug_log(
                "hands-free combo resolved to nothing — using default Ctrl+Win+Space",
                "voice",
            )
            return [Key.ctrl, Key.cmd, Key.space]
        return keys

    @staticmethod
    def _normalise_combo(combo: Any) -> list:
        """Lowercased list of combo key names; default Ctrl+Win+Space if invalid."""
        default = ["ctrl", "cmd", "space"]
        if not isinstance(combo, (list, tuple)) or not combo:
            return default
        names = [str(x).strip().lower() for x in combo if str(x).strip()]
        return names or default

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
            # Snapshot the OS clipboard sequence so an identical re-utterance is
            # still detectable (the text matches the baseline but the sequence
            # advances when Wispr writes).
            self._clipboard_baseline_seq = self._clipboard_seq()

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
                args=(self._clipboard_baseline, self._clipboard_baseline_seq,
                      self._abort_generation),
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

    def _post_dictation_worker(
        self,
        baseline: str,
        baseline_seq: Optional[int] = None,
        dictation_gen: Optional[int] = None,
    ) -> None:
        """
        Runs after each completed dictation. Polls the clipboard for up to
        ``clipboard_wait_sec`` + ``wispr_clipboard_grace_sec`` waiting for Wispr
        Flow to write the transcript. Dispatches via callbacks; always fires
        ``on_dictation_end(captured, reason)`` once finished.

        ``captured`` is True when a clipboard transcript was seen (and
        dispatched). ``reason`` distinguishes the no-capture causes so the
        listener can give an honest notice and triage is possible:
          * ``None``       — captured (a transcript was dispatched)
          * ``"off"``      — clipboard polling is unavailable (pyperclip missing)
          * ``"timeout"``  — watched but nothing arrived within the wait+grace
          * ``"unchanged"``— the clipboard never changed at all (sequence path)

        On a no-capture, if Wispr's real state shows it is STILL recording, we
        force it OFF to a known idle — turning the most diagnostic moment into a
        desync-recovery point rather than a silent cosmetic notice.
        """
        captured = False
        reason: Optional[str] = None

        def _aborted() -> bool:
            return dictation_gen is not None and dictation_gen != self._abort_generation

        try:
            if _aborted():
                return  # STOP fired for this turn — discard, UI already torn down
            if not self.watch_clipboard:
                # No clipboard polling — just wait long enough for Wispr Flow
                # to finish auto-typing before we erase it.
                reason = "off"
                time.sleep(self.clipboard_wait_sec)
            else:
                reason, captured = self._poll_clipboard_for_transcript(
                    baseline, baseline_seq, dictation_gen)
                if _aborted():
                    return  # STOP fired mid-poll — drop the transcript
                if not captured and not self.shutdown_event.is_set():
                    debug_log(
                        f"No transcript appeared within "
                        f"{self.clipboard_wait_sec + self._clipboard_grace_sec:.0f}s "
                        f"(reason={reason})",
                        "voice",
                    )
                    # Closed-loop recovery: a no-capture turn where Wispr is
                    # still recording means the stop never landed — force OFF.
                    if self._read_probe() is True:
                        try:
                            self._ensure_recording(False)
                            debug_log(
                                "no-capture: Wispr still recording -> forced OFF",
                                "voice",
                            )
                        except Exception as e:
                            debug_log(f"no-capture force-off raised: {e!r}", "voice")
        finally:
            if not _aborted() and self.on_dictation_end is not None:
                try:
                    self.on_dictation_end(captured, reason)
                except Exception as e:
                    debug_log(f"on_dictation_end callback raised: {e}",
                              "voice")

    def _poll_clipboard_for_transcript(
        self, baseline: str, baseline_seq: Optional[int],
        dictation_gen: Optional[int] = None,
    ) -> tuple[Optional[str], bool]:
        """Poll the clipboard until a NEW transcript appears or we time out.

        Returns ``(reason, captured)``. Detection prefers the OS clipboard
        sequence number (so an identical re-utterance is still detected) and
        falls back to an exact-text diff when the sequence is unavailable.
        """
        deadline = (time.monotonic() + self.clipboard_wait_sec
                    + self._clipboard_grace_sec)
        seq_moved = False
        while time.monotonic() < deadline:
            if self.shutdown_event.is_set():
                return None, False
            try:
                current = pyperclip.paste() or ""
            except Exception:
                time.sleep(CLIPBOARD_POLL_INTERVAL)
                continue
            cur_seq = self._clipboard_seq()
            changed = self._clipboard_changed(
                baseline, baseline_seq, current, cur_seq)
            if cur_seq is not None and baseline_seq is not None and cur_seq != baseline_seq:
                seq_moved = True
            if changed and current.strip():
                if dictation_gen is not None and dictation_gen != self._abort_generation:
                    return "aborted", False  # STOP fired — do not dispatch
                self._dispatch_transcription(current)
                return None, True
            time.sleep(CLIPBOARD_POLL_INTERVAL)
        # Timed out. Distinguish "clipboard never moved at all" (unchanged)
        # from "moved but produced nothing usable" (timeout).
        if baseline_seq is not None and not seq_moved:
            return "unchanged", False
        return "timeout", False

    @staticmethod
    def _clipboard_changed(
        baseline: str,
        baseline_seq: Optional[int],
        current: str,
        cur_seq: Optional[int],
    ) -> bool:
        """True when the clipboard has a NEW value since the wake-time baseline.

        Uses the OS clipboard sequence number when available (so an identical
        re-utterance — same text — is still detected because the sequence
        advanced), else falls back to the exact-text diff used historically."""
        if baseline_seq is not None and cur_seq is not None:
            return cur_seq != baseline_seq
        return current != baseline

    @staticmethod
    def _clipboard_seq() -> Optional[int]:
        """Windows clipboard sequence number, or None when unavailable.

        Increments on ANY clipboard change (non-destructive — we never write
        the clipboard ourselves). Fail-open on non-Windows / error."""
        try:
            import ctypes  # Windows-only path; cheap import
            return int(ctypes.windll.user32.GetClipboardSequenceNumber())
        except Exception:
            return None

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

        # Privacy: restore the pre-wake clipboard so the spoken transcript does
        # not linger on the clipboard / in Win+V history. ``text`` is already
        # captured, so nothing is lost.
        self._restore_clipboard_baseline()

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

    def _restore_clipboard_baseline(self) -> None:
        """Put the wake-time clipboard contents back after a transcript dispatch.

        Closes the retention channel where the spoken transcript would otherwise
        sit on the system clipboard (and in Win+V history). No-op when disabled,
        when clipboard access is unavailable, or on any error (fail-open)."""
        if not (self.restore_clipboard and self.watch_clipboard and pyperclip is not None):
            return
        try:
            pyperclip.copy(self._clipboard_baseline or "")
        except Exception as e:
            debug_log(f"clipboard restore failed (non-fatal): {e}", "voice")

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

    def _prime_wake_model(self) -> None:
        """Warm openWakeWord's stateful classifier window with silence.

        The model needs ~16 consecutive embeddings before it scores reliably;
        on a cold model (startup) or one gone stale while muted, the first real
        "Hey Jarvis" lands on a near-empty window and under-scores. Reset (if
        the build exposes it) then feed ``WAKE_PRIME_FRAMES`` int16-zero frames
        so the next live utterance hits a full window. Mirrors the silence
        priming in ``_recall_check.py``. Best-effort: never raises.
        """
        model = getattr(self, "wake_model", None)
        # Priming resets the stateful classifier window, so any in-progress
        # consecutive-frame run is no longer valid.
        self._wake_consec = 0
        if model is None:
            return
        try:
            reset = getattr(model, "reset", None)  # oww 0.6.0 may not expose it
            if callable(reset):
                reset()
            silent = np.zeros(WAKE_FRAME_SIZE, dtype=np.int16)
            for _ in range(WAKE_PRIME_FRAMES):
                model.predict(silent)
        except Exception as e:
            debug_log(f"wake-model prime skipped: {e!r}", "voice")

    def _process_wake(self, audio_f32: np.ndarray) -> None:
        """
        Buffer audio as int16 PCM and run openWakeWord in 1280-sample frames.

        openWakeWord is STATEFUL: its melspec→embedding→classifier window only
        advances on predict() calls and needs ~1.3s of CONTINUOUSLY-fed frames
        before it scores a real "Hey Jarvis" reliably. So we feed EVERY frame
        to the model (even silent ones) to keep that window primed. The RMS
        floor and the IDLE/cooldown/HOT_WINDOW checks gate only the *trigger
        decision* — never the model — so a quiet room still can't produce a
        phantom wake while recall stays high.

        When muted (``self._user_muted``) or while JARVIS is speaking
        (``self._speak_paused``) we drain the input buffer and don't call the
        wake model — guarantees no wake fires. The two flags are kept separate
        so a post-speak resume can't lift a user's mute. After such a gap the
        window is re-primed on resume (see :meth:`_prime_wake_model`).
        """
        if self._user_muted or self._speak_paused:
            # Drain so we don't accumulate a buffer that would replay on
            # resume — the user expects mute/pause to be silent, not delayed.
            self._wake_buf.clear()
            self._wake_consec = 0  # a pause breaks any in-progress wake run
            return

        # Apply the wake-only software gain, then clip safely to int16. This
        # boosts a distant/quiet utterance for the detector without touching the
        # VAD/transcript audio (which still uses the raw float buffer).
        pcm = np.clip(
            audio_f32 * 32767.0 * self.wake_gain, -32768, 32767
        ).astype(np.int16)
        self._wake_buf.extend(pcm.tolist())

        while len(self._wake_buf) >= WAKE_FRAME_SIZE:
            frame = np.asarray(self._wake_buf[:WAKE_FRAME_SIZE],
                               dtype=np.int16)
            del self._wake_buf[:WAKE_FRAME_SIZE]

            # Decrement cooldown each frame regardless
            if self._wake_cooldown > 0:
                self._wake_cooldown -= 1

            # Feed EVERY frame to the model. openWakeWord is STATEFUL: its
            # classifier window only advances on predict() calls and needs
            # ~1.3s of CONTINUOUS frames before it scores a real wake. Gating
            # the model on silence (as a previous build did) starved the
            # window, so the first frames of a real "Hey Jarvis" under-scored
            # (~0.125) and only climbed after several frames — missed wakes.
            try:
                predictions = self.wake_model.predict(frame)
            except Exception as e:
                print(f"[ERROR] Wake model error: {e}",
                      file=sys.stderr, flush=True)
                return

            # Trigger gate. Only consider a wake when truly idle and not in
            # cooldown. HOT_WINDOW intentionally skips the wake check — the user
            # is in a VAD-driven follow-up turn — but the model stayed fed above
            # so its window is warm for the next wake.
            with self._state_lock:
                is_idle = self._state == State.IDLE
            if not is_idle or self._wake_cooldown > 0:
                self._wake_consec = 0
                continue

            # Silence/energy gate on the TRIGGER only (never the model). A
            # near-silent frame can't be a real "Hey Jarvis", yet the
            # recall-tuned model at a low threshold could still score it as one
            # (quiet-room phantom). Normalise by wake_gain so a high software
            # gain can't defeat the gate; real speech (RMS in the thousands) is
            # untouched. A silent frame also breaks the consecutive run.
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            if rms / max(self.wake_gain, 1e-6) < self._wake_rms_floor:
                self._wake_consec = 0
                continue

            # predictions is dict {model_name: float in [0,1]}. Require
            # ``_wake_consec_frames`` CONSECUTIVE frames at/above threshold
            # before firing: a single noise/echo spike scores high on ONE frame,
            # while a real "Hey Jarvis" holds the score across many. This is the
            # debounce that kills single-frame phantoms (the observed 0.32).
            best = max(predictions.values()) if predictions else 0.0
            if best >= self.wake_threshold:
                self._wake_consec += 1
                if self._wake_consec >= self._wake_consec_frames:
                    self._wake_consec = 0
                    self._start_dictation(float(best))
            else:
                self._wake_consec = 0

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
