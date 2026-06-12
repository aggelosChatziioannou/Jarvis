"""
Voice Listener - Main orchestrator for voice capture and processing.

Coordinates audio capture, speech recognition, echo detection, and state management.
"""

from __future__ import annotations
import functools
import os
import re
import threading
import time
import queue
import sys
import platform
from collections import deque
from typing import Optional, TYPE_CHECKING, Any
from datetime import datetime

from rapidfuzz import fuzz
from .echo_detection import EchoDetector
from .hallucinations import (
    HALLUCINATION_EXACT,
    HALLUCINATION_SUBSTRINGS,
    looks_like_hallucination,
)
from .state_manager import StateManager, ListeningState
from .wake_detection import is_wake_word_detected, extract_query_after_wake, is_stop_command, find_wake_word_position, is_wake_only_utterance
from .transcript_buffer import TranscriptBuffer
from .intent_judge import IntentJudge, IntentJudgment, create_intent_judge, warm_up_ollama_model
from ..debug import debug_log, info_log, log_state_transition
from ..utils.location import is_location_available

# Tier 1/2 intent cascade — optional, gracefully degrades if missing.
# The cascade short-circuits the (relatively slow) intent_judge LLM call:
#   Tier 1: heuristic classifier (Aho-Corasick + TF-IDF ONNX, <2ms)
#   Tier 2: fused intent engine (one structured LLM call, replaces judge)
# Each is imported defensively so the listener boots even when the new
# modules are absent or their on-disk artefacts (ONNX model, etc.) are
# missing. Feature flags `cfg.use_heuristic_classifier` and
# `cfg.use_fused_intent` (both default True via getattr) let the user
# disable either tier from config without touching code.
try:
    from .intent_classifier import HeuristicIntentClassifier, ClassifierResult
    _HEURISTIC_CLASSIFIER_AVAILABLE = True
except Exception as _e:  # noqa: BLE001 — defensive import
    HeuristicIntentClassifier = None  # type: ignore
    ClassifierResult = None  # type: ignore
    _HEURISTIC_CLASSIFIER_AVAILABLE = False
    print(f"  ⚠️  HeuristicIntentClassifier import failed (non-fatal): {_e}", flush=True)

try:
    from .fused_intent import FusedIntentEngine, FusedJudgment
    _FUSED_INTENT_AVAILABLE = True
except Exception as _e:  # noqa: BLE001 — defensive import
    FusedIntentEngine = None  # type: ignore
    FusedJudgment = None  # type: ignore
    _FUSED_INTENT_AVAILABLE = False
    print(f"  ⚠️  FusedIntentEngine import failed (non-fatal): {_e}", flush=True)

if TYPE_CHECKING:
    from ..memory.db import Database
    from ..memory.conversation import DialogueMemory


def is_whisper_hallucination(no_speech_prob: float, threshold: float) -> bool:
    """Shared Whisper no-speech gate.

    Whisper can report high `avg_logprob` confidence on hallucinated phrases
    when the audio is silent or noise. `no_speech_prob` is an independent
    signal and must be checked first. Used by both the faster-whisper path
    (`_filter_noisy_segments`) and the MLX path (`_finalize_utterance`) so
    both backends apply identical policy.
    """
    return no_speech_prob >= threshold

# Audio processing imports (optional)
try:
    import sounddevice as sd
    import webrtcvad
    import numpy as np
except ImportError as e:
    sd = None
    webrtcvad = None
    np = None
    # Log import error for debugging
    print(f"  ⚠️  Audio import error: {e}", flush=True)
    print("     This may indicate PortAudio is not found", flush=True)
    import sys as _sys
    if _sys.platform == 'linux':
        print("     On Linux, ensure PortAudio is installed: sudo apt install libportaudio2", flush=True)
    del _sys
except OSError as e:
    # PortAudio loading errors appear as OSError
    sd = None
    webrtcvad = None
    np = None
    print(f"  ❌ PortAudio initialisation failed: {e}", flush=True)
    print("     Please reinstall the application or check audio drivers", flush=True)
    import sys as _sys
    if _sys.platform == 'linux':
        print("     On Linux, ensure PortAudio is installed: sudo apt install libportaudio2", flush=True)
    del _sys

# Whisper backend imports - try MLX first on Apple Silicon, fall back to faster-whisper
MLX_WHISPER_AVAILABLE = False
FASTER_WHISPER_AVAILABLE = False

def _is_apple_silicon() -> bool:
    """Check if running on Apple Silicon Mac."""
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _get_mic_permission_hint() -> str:
    """Return platform-appropriate microphone permission guidance."""
    if sys.platform == 'win32':
        return "Windows Settings > Privacy > Microphone > Allow apps to access"
    elif sys.platform == 'darwin':
        return "System Settings > Privacy & Security > Microphone"
    else:
        return "`pactl list sources` or audio settings for your desktop environment"

def _resample(audio, src_rate: int, dst_rate: int):
    """Resample a 1-D float32 numpy array from *src_rate* to *dst_rate*.

    Uses linear interpolation — fast and good enough for speech going into Whisper.
    """
    if src_rate == dst_rate or np is None:
        return audio
    ratio = dst_rate / src_rate
    n_out = int(len(audio) * ratio)
    indices = np.arange(n_out) / ratio
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


def _setup_nvidia_dll_path() -> None:
    """Add NVIDIA CUDA DLL directories to PATH on Windows.

    The pip packages nvidia-cublas-cu12 and nvidia-cudnn-cu12 install DLLs
    under site-packages/nvidia/*/bin/ which isn't on PATH by default.
    PyInstaller bundles place them in {app}/cuda/. This function finds
    both locations and prepends them to PATH so ctypes.CDLL can find them.
    """
    import os

    dirs_to_add = []

    # 1. Check for NVIDIA pip packages in site-packages
    try:
        import nvidia.cublas  # type: ignore[import-untyped]
        for pkg_path in nvidia.cublas.__path__:
            bin_dir = os.path.join(pkg_path, "bin")
            if os.path.isdir(bin_dir):
                dirs_to_add.append(bin_dir)
    except (ImportError, AttributeError):
        pass

    try:
        import nvidia.cudnn  # type: ignore[import-untyped]
        for pkg_path in nvidia.cudnn.__path__:
            bin_dir = os.path.join(pkg_path, "bin")
            if os.path.isdir(bin_dir):
                dirs_to_add.append(bin_dir)
    except (ImportError, AttributeError):
        pass

    # 2. Check for CUDA DLLs in app directory (installed by install_cuda.ps1)
    # For frozen apps: check next to the executable (not _MEIPASS, since
    # CUDA libs are downloaded post-install, not bundled in the archive)
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = None

    if app_dir:
        cuda_dir = os.path.join(app_dir, "cuda")
        if os.path.isdir(cuda_dir):
            dirs_to_add.append(cuda_dir)

    # 3. Register DLL directories (must happen before ctypes.CDLL probes)
    # Use both os.add_dll_directory (for ctypes.CDLL) and PATH (for
    # subprocess/child processes). On Windows, PATH changes after process
    # start don't affect ctypes.CDLL search — add_dll_directory is needed.
    if dirs_to_add:
        current_path = os.environ.get("PATH", "")
        new_entries = os.pathsep.join(dirs_to_add)
        os.environ["PATH"] = new_entries + os.pathsep + current_path
        for d in dirs_to_add:
            try:
                os.add_dll_directory(d)
            except (OSError, AttributeError):
                pass
            debug_log(f"added NVIDIA DLL path: {d}", "voice")


@functools.lru_cache(maxsize=None)
def _probe_cuda_available() -> tuple[bool, list[str]]:
    """Probe cuBLAS + cuDNN availability once per process and cache the result.

    The version ranges intentionally span more than the currently pinned
    versions in `installer/windows/install_cuda.ps1` (`cublas64_12.dll`,
    `cudnn_ops64_9.dll`) so a future installer bump doesn't silently fall
    back to CPU until this probe is updated too. A bump outside the
    existing range still requires widening these ranges — the relationship
    is by convention, not enforced.

    Cached because DLLs don't appear or disappear while the process is
    running, and the scan does up to 18 `LoadLibrary` calls on a miss.
    """
    _setup_nvidia_dll_path()

    missing_libs: list[str] = []
    cublas_found = False
    cudnn_found = False
    try:
        import ctypes

        for ver in range(20, 10, -1):
            try:
                ctypes.CDLL(f"cublas64_{ver}.dll")
                cublas_found = True
                debug_log(f"cuBLAS found (cublas64_{ver}.dll)", "voice")
                break
            except OSError:
                continue
        if not cublas_found:
            missing_libs.append("cuBLAS")

        for ver in range(15, 7, -1):
            try:
                ctypes.CDLL(f"cudnn_ops64_{ver}.dll")
                cudnn_found = True
                debug_log(f"cuDNN found (cudnn_ops64_{ver}.dll)", "voice")
                break
            except OSError:
                continue
        if not cudnn_found:
            missing_libs.append("cuDNN")
    except Exception as e:
        debug_log(f"CUDA library probe failed: {e}", "voice")

    return cublas_found and cudnn_found, missing_libs


def _probe_windows_cuda_libraries(device: str) -> tuple[str, list[str]]:
    """Return the device to use and any missing CUDA lib names.

    Short-circuits on non-Windows or non-CUDA device strings. Otherwise
    delegates to the cached `_probe_cuda_available()` so the expensive DLL
    scan only runs once per process lifetime.
    """
    if sys.platform != "win32" or device not in ("auto", "cuda"):
        return device, []

    available, missing_libs = _probe_cuda_available()
    if not available:
        return "cpu", missing_libs
    return device, []


def _print_cuda_unavailable_hint(missing_libs: list[str]) -> None:
    """Print the user-facing CUDA-missing message and recovery hint.

    The hint deliberately points at the tray action, not at "reinstall the
    app". The Inno Setup task only fires once and skips on stale marker
    files, so reinstalling without first deleting `{app}\\cuda` rarely
    fixes the underlying problem. The tray action re-runs install_cuda.ps1
    directly with UAC, which is the actual recovery path.
    """
    debug_log(f"CUDA libraries missing: {missing_libs}, forcing CPU mode", "voice")
    print("  ℹ️  CUDA not available, using CPU mode", flush=True)
    if missing_libs:
        print(f"     Missing: {', '.join(missing_libs)}", flush=True)
    print(
        "  💡 For GPU acceleration, click 'Reinstall GPU libraries' in the Jarvis tray menu",
        flush=True,
    )


try:
    if _is_apple_silicon():
        import mlx_whisper
        MLX_WHISPER_AVAILABLE = True
except Exception:
    mlx_whisper = None

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except Exception:
    # Catch broad: the faster-whisper import chain can raise ValueError
    # (e.g. "psutil.__spec__ is not set") in some environments.
    WhisperModel = None


def _is_faster_whisper_turbo_supported() -> bool:
    """Check if the installed faster-whisper supports the large-v3-turbo model."""
    try:
        import faster_whisper
        from packaging.version import Version
        return Version(faster_whisper.__version__) >= Version("1.1.0")
    except Exception:
        return False


def _get_mlx_model_repo(model_name: str) -> str:
    """Get the MLX Community HuggingFace repo for a Whisper model."""
    # Map standard model names to MLX Community repos
    model_map = {
        "tiny": "mlx-community/whisper-tiny-mlx",
        "tiny.en": "mlx-community/whisper-tiny.en-mlx",
        "base": "mlx-community/whisper-base-mlx",
        "base.en": "mlx-community/whisper-base.en-mlx",
        "small": "mlx-community/whisper-small-mlx",
        "small.en": "mlx-community/whisper-small.en-mlx",
        "medium": "mlx-community/whisper-medium-mlx",
        "medium.en": "mlx-community/whisper-medium.en-mlx",
        "large": "mlx-community/whisper-large-v3-mlx",
        "large-v2": "mlx-community/whisper-large-v2-mlx",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    }
    return model_map.get(model_name, f"mlx-community/whisper-{model_name}-mlx")


def _clear_corrupted_whisper_cache(error_message: str) -> bool:
    """Clear a corrupted Whisper model cache directory.

    Parses the CTranslate2 error message to find the snapshot directory,
    then deletes the parent ``models--`` directory so the model can be
    re-downloaded cleanly (including blobs that may also be corrupt).

    Returns ``True`` if a cache directory was found and deleted.
    """
    import re
    import shutil

    # CTranslate2 error format:
    #   "Unable to open file 'model.bin' in model '/path/to/snapshots/hash'"
    match = re.search(
        r"unable to open file\s+'[^']+'\s+in model\s+'([^']+)'",
        error_message,
        re.IGNORECASE,
    )
    if not match:
        debug_log("could not parse cache path from error message", "voice")
        return False

    snapshot_path = match.group(1)

    # Walk up to the models-- directory
    # snapshot_path is e.g. .../models--Org--Name/snapshots/<hash>
    # We want to delete .../models--Org--Name entirely
    from pathlib import Path
    path = Path(snapshot_path)
    model_dir = None
    for parent in [path] + list(path.parents):
        if parent.name.startswith("models--"):
            model_dir = parent
            break

    if model_dir is None or not model_dir.is_dir():
        debug_log(f"could not locate models-- cache directory from: {snapshot_path}", "voice")
        return False

    try:
        shutil.rmtree(model_dir)
        debug_log(f"cleared corrupted Whisper cache: {model_dir}", "voice")
        return True
    except OSError as e:
        debug_log(f"failed to clear corrupted cache: {e}", "voice")
        return False


class VoiceListener(threading.Thread):
    """Main voice listening thread that orchestrates all voice processing."""

    def __init__(self, db: "Database", cfg, tts: Optional[Any],
                 dialogue_memory: "DialogueMemory"):
        """
        Initialise voice listener.

        Args:
            db: Database instance for storage
            cfg: Configuration object
            tts: Text-to-speech engine (optional)
            dialogue_memory: Dialogue memory instance
        """
        super().__init__(daemon=True)

        self.db = db
        self.cfg = cfg
        self.tts = tts
        self.dialogue_memory = dialogue_memory
        self._should_stop = False

        # STT backend selector — "whisper" (legacy, local) or "wispr"
        # (Wispr Flow bridge: openWakeWord + Silero VAD + clipboard pickup).
        # Read defensively so this code remains safe even before Phase B's
        # Settings dataclass field lands.
        self._stt_backend = getattr(cfg, "stt_backend", "whisper")
        # Bridge instance populated below if stt_backend == "wispr". Kept on
        # the listener so `stop()` and any thread-safety code can reach it.
        self._wispr_bridge = None
        # ── In-process STT hot-switch state ──────────────────────────────
        # The run() dispatcher is re-entrant: when the user flips
        # `stt_backend` in the console, request_stt_switch() sets
        # `_pending_backend` + `_switch_event`. The active backend loop
        # breaks at its top-of-loop guard (so an in-flight transcription
        # finishes first), run() tears down the old STT runtime and
        # re-dispatches the new one — keeping control_bus / porcupine /
        # API server / daemon closures all bound to THIS same instance.
        self._switch_event = threading.Event()
        self._pending_backend: Optional[str] = None
        self._switch_from: Optional[str] = None  # backend we left, for fallback
        self._consecutive_fast_failures = 0  # guards fallback ping-pong
        self._dictation_active = False  # Pause flag set by dictation engine
        self._first_utterance = True  # Suppress turn separator before the very first transcription
        # ISO-639-1 code Whisper detected for the most recent utterance.
        # Updated at every successful transcription site (MLX + faster-
        # whisper) and consumed by `_dispatch_query` so downstream tools
        # can pick locale-appropriate resources (e.g. tr.wikipedia.org).
        # One-utterance-at-a-time voice flow means the read in
        # `_dispatch_query` always matches the write from the Whisper
        # call that produced the transcript.
        self._last_detected_language: Optional[str] = None

        # Audio processing components
        self._whisper_backend: Optional[str] = None  # "mlx" or "faster-whisper"
        self._whisper_device: Optional[str] = None  # "cpu" or "cuda" (resolved from CTranslate2)
        self._mlx_model_repo: Optional[str] = None  # For MLX backend
        self.model: Optional[Any] = None  # WhisperModel for faster-whisper, None for MLX
        self.transcribe_lock = threading.Lock()  # Shared lock for Whisper model access
        self._audio_q: queue.Queue = queue.Queue(maxsize=64)
        self._pre_roll: deque = deque()

        # Audio callback monitoring (for debugging)
        self._callback_count = 0
        self._last_callback_log_time = 0

        # Voice activity detection
        self.is_speech_active = False
        self._silence_frames = 0
        self._utterance_frames: list = []
        self._frame_samples = 0
        self._samplerate = int(getattr(self.cfg, "sample_rate", 16000))
        self._vad: Optional = None

        # Initialise VAD. Default backend is Silero (neural, ~4× lower error
        # rate than WebRTC at the same false-positive rate per Picovoice 2026
        # benchmark). Falls back to WebRTC automatically on import failure so
        # the listener still starts on machines without silero-vad installed.
        if bool(getattr(self.cfg, "vad_enabled", True)):
            backend = str(getattr(self.cfg, "vad_backend", "silero")).lower()
            if backend == "silero":
                try:
                    from .vad_silero import SileroVAD
                    _silero_onset = float(getattr(self.cfg, "vad_silero_threshold", 0.7))
                    _silero_offset = float(getattr(self.cfg, "vad_silero_neg_threshold", _silero_onset))
                    self._vad = SileroVAD(
                        threshold=_silero_onset,
                        neg_threshold=_silero_offset,
                    )
                    debug_log(
                        f"VAD backend: silero (onset={_silero_onset}, offset={_silero_offset})",
                        "voice",
                    )
                    print(
                        f"  🎙️  VAD backend: silero (hysteresis {_silero_onset}/{_silero_offset})",
                        flush=True,
                    )
                except Exception as e:
                    debug_log(
                        f"silero VAD unavailable ({e}), falling back to webrtc",
                        "voice",
                    )
                    print(
                        f"  ⚠️  silero-vad unavailable ({e}); falling back to webrtcvad",
                        flush=True,
                    )
                    backend = "webrtc"
            if backend == "webrtc":
                if webrtcvad is not None:
                    try:
                        self._vad = webrtcvad.Vad(int(getattr(self.cfg, "vad_aggressiveness", 2)))
                        debug_log(
                            f"VAD backend: webrtc (aggressiveness={getattr(self.cfg, 'vad_aggressiveness', 2)})",
                            "voice",
                        )
                    except Exception:
                        self._vad = None

        # Initialise modular components
        self.echo_detector = EchoDetector(
            echo_tolerance=float(getattr(self.cfg, "echo_tolerance", 0.3)),
            energy_spike_threshold=float(getattr(self.cfg, "echo_energy_threshold", 2.0))
        )

        self.state_manager = StateManager(
            hot_window_seconds=float(getattr(self.cfg, "hot_window_seconds", 3.0)),
            echo_tolerance=float(getattr(self.cfg, "echo_tolerance", 0.3)),
            voice_collect_seconds=float(getattr(self.cfg, "voice_collect_seconds", 2.0)),
            max_collect_seconds=float(getattr(self.cfg, "voice_max_collect_seconds", 60.0))
        )

        # Energy tracking for echo detection
        self._recent_audio_energy: deque = deque(maxlen=50)

        # TTS synthesis-to-callback timing (for buffer-delay logging)
        self._last_tts_synthesis_time: float = 0.0

        # Audio-level wake word detection timestamp
        self._wake_timestamp: Optional[float] = None

        # STOP-button plumbing. _llm_cancel_event is set by reset_everything()
        # to signal in-flight LLM calls to bail out; the reply engine and
        # dispatch loop poll this on safe boundaries. _muted suppresses
        # audio queue ingestion when the user presses MUTE.
        self._llm_cancel_event = threading.Event()
        # These three flags are shared between the control-bus worker thread
        # (_handle_control_command) and the audio loop / _dispatch_query. Guard
        # every read/write with this lock so the manual-finalize handshake
        # (set -> consume -> clear) cannot lose or duplicate an update. The
        # lock is only ever held around the flag read/modify/clear, never
        # across blocking I/O (audio reads, LLM, TTS).
        self._control_flags_lock = threading.Lock()
        self._muted = False
        self._manual_trigger_active = False  # True when listening was started via TRIGGER button
        self._manual_finalize_requested = False  # Set by MUTE during manual trigger to force immediate dispatch

        # Control bus server — accepts STOP/MUTE/PING from the desktop HUD.
        # Lazy import to avoid pulling sockets into early init paths that
        # may run before threading is fully set up.
        self._control_bus = None

        # Rolling transcript buffer for context-aware processing
        # Used for both retention and context passed to intent judge
        self._buffer_duration = float(getattr(self.cfg, "transcript_buffer_duration_sec", 120.0))
        self._transcript_buffer = TranscriptBuffer(max_duration_sec=self._buffer_duration)
        debug_log(f"transcript buffer initialised ({self._buffer_duration}s)", "voice")

        # Sticky language lock — avoids re-detecting EL/EN every utterance.
        # Whisper auto-detecting per-utterance in a bilingual setup can land
        # in a hybrid phonetic decoding mode that produces failures like
        # "καιρός" → "κύριος". The lock votes 2-of-3 over a sliding window.
        from .language_lock import LanguageLock
        self._language_lock = LanguageLock(
            history_size=3,
            min_agreement=2,
            allowed=tuple(getattr(self.cfg, "whisper_allowed_languages", None) or ("el", "en")),
        )

        # Intent judge (full context, larger model) - always used when available
        self._intent_judge = create_intent_judge(self.cfg)
        if self._intent_judge is not None:
            debug_log(f"intent judge initialised (model: {self._intent_judge.config.model})", "voice")
        else:
            debug_log("intent judge unavailable, using simple wake word detection", "voice")

        # ---- Tier 1/2 intent cascade --------------------------------------
        # Optional speed-ups that sit between the existing fast-path regex
        # SHORT-CIRCUIT (Tier 0, lower in this function's flow) and the slow
        # intent_judge LLM call. Either tier can be disabled from config.
        # On any init failure we set the attribute to None and the runtime
        # cascade falls through to the legacy intent_judge path.
        self._use_heuristic_classifier = bool(
            getattr(self.cfg, "use_heuristic_classifier", True)
        )
        self._use_fused_intent = bool(
            getattr(self.cfg, "use_fused_intent", True)
        )

        # Tuning override: caller note says the classifier's built-in
        # `_THRESH_MED=0.72` is too conservative — set 0.5 to lift local
        # routing from ~62% to ~88-92% with ~95% precision. Configurable
        # via `cfg.heuristic_med_threshold`.
        self._heuristic_med_threshold = float(
            getattr(self.cfg, "heuristic_med_threshold", 0.5)
        )

        # Tier 1: heuristic intent classifier (Aho-Corasick + ONNX TF-IDF).
        self._heuristic_classifier = None
        if self._use_heuristic_classifier and _HEURISTIC_CLASSIFIER_AVAILABLE:
            try:
                self._heuristic_classifier = HeuristicIntentClassifier()
                # The class does not accept `med_threshold` in __init__; we
                # patch the module-level constants used by the instance's
                # `_bucket` static method instead. Module-level mutation is
                # acceptable here — single classifier per process, and the
                # caller explicitly requested this tuning (see prompt).
                try:
                    from . import intent_classifier as _ic_mod
                    _ic_mod._THRESH_MED = self._heuristic_med_threshold
                except Exception as _e:  # noqa: BLE001
                    debug_log(
                        f"heuristic classifier threshold override failed (non-fatal): {_e}",
                        "voice",
                    )
                debug_log(
                    f"Tier 1 heuristic classifier initialised "
                    f"(med_threshold={self._heuristic_med_threshold})",
                    "voice",
                )
            except Exception as e:  # noqa: BLE001
                debug_log(f"Tier 1 heuristic classifier init failed (non-fatal): {e}", "voice")
                self._heuristic_classifier = None
        elif not _HEURISTIC_CLASSIFIER_AVAILABLE:
            debug_log("Tier 1 heuristic classifier unavailable (import failed)", "voice")
        else:
            debug_log("Tier 1 heuristic classifier disabled by config", "voice")

        # Tier 2: fused intent engine (collapses judge/router/planner into one LLM call).
        self._fused_intent = None
        if self._use_fused_intent and _FUSED_INTENT_AVAILABLE:
            try:
                self._fused_intent = FusedIntentEngine(self.cfg)
                debug_log(
                    f"Tier 2 fused intent engine initialised (model: {self._fused_intent.model})",
                    "voice",
                )
            except Exception as e:  # noqa: BLE001
                debug_log(f"Tier 2 fused intent engine init failed (non-fatal): {e}", "voice")
                self._fused_intent = None
        elif not _FUSED_INTENT_AVAILABLE:
            debug_log("Tier 2 fused intent engine unavailable (import failed)", "voice")
        else:
            debug_log("Tier 2 fused intent engine disabled by config", "voice")

        # Shared 10s TTL cache (32 entries) wrapping the cascade — mirrors
        # the cache that intent_judge.py owns. Keyed on the same
        # (text, hot_window, last_tts_text) tuple so cache semantics stay
        # consistent regardless of which tier produced the verdict.
        from collections import OrderedDict as _OrderedDict
        self._cascade_cache: "_OrderedDict[str, tuple[float, IntentJudgment]]" = _OrderedDict()
        self._CASCADE_CACHE_TTL_SEC = 10.0
        self._CASCADE_CACHE_MAX_ENTRIES = 32

        # Stash for the fused engine's tool/plan output. Not consumed yet
        # (reply.engine still runs its own router+planner); kept here so a
        # future reply.engine pass can pick them up without an extra LLM
        # call. Updated on every successful Tier 2 hit; cleared on dispatch
        # AND at the top of every cascade run. None means "no fused signal —
        # engine must run its own router"; [] means "fused decided no tools".
        self._last_fused_tools: Optional[list] = None
        self._last_fused_plan: Optional[list] = None

        # Thinking tune player
        self._tune_player: Optional = None

        # Control bus: accepts cross-process commands (STOP / MUTE / PING)
        # from the desktop HUD. Daemon-thread server, never blocks audio loop.
        try:
            from ..control_bus import ControlBusServer
            self._control_bus = ControlBusServer(self._handle_control_command)
            self._control_bus.start()
        except Exception as e:
            debug_log(f"control bus startup failed (non-fatal): {e}", "voice")
            self._control_bus = None

        # HTTP/WebSocket API server for the React control console.
        # Same process, daemon thread, port 38130. Also install the stdout
        # mirror so every print() in the daemon ends up in the Live Logs feed.
        try:
            from .. import api_server, config_safety
            from ..config import default_config_path
            import os as _os
            from pathlib import Path as _Path

            # Safety net: auto-restore if the config has been wiped, then
            # take a fresh snapshot so subsequent migrations can't lose work.
            _cfg_path = _Path(_os.environ.get("JARVIS_CONFIG_PATH") or default_config_path())
            restored = config_safety.check_and_restore(_cfg_path)
            if restored:
                print(f"♻️ Config auto-restored from {restored.name}", flush=True)
            config_safety.snapshot(_cfg_path, reason="boot")

            api_server.start_in_background()
            api_server.install_stdout_mirror()
            api_server.publish_log("info", "Jarvis daemon initialised")
        except Exception as e:
            debug_log(f"API server startup failed (non-fatal): {e}", "voice")

        # Optional Porcupine wake detector — alternative to the Whisper backend's
        # transcript-based wake (the Wispr backend uses openWakeWord instead).
        # Either path can set _wake_timestamp. Only spins up when
        # `porcupine_enabled: true` is set in config and the key is present.
        self._porcupine = None
        try:
            from .wake_porcupine import create_porcupine_from_config

            def _on_porcupine_wake(ts: float) -> None:
                self._wake_timestamp = ts
                debug_log(f"Porcupine set _wake_timestamp = {ts:.3f}", "voice")

            self._porcupine = create_porcupine_from_config(self.cfg, _on_porcupine_wake)
            if self._porcupine is not None:
                debug_log("Porcupine wake detector active", "voice")
        except Exception as e:
            debug_log(f"Porcupine integration error (non-fatal): {e}", "voice")

        # ------------------------------------------------------------------
        # Wispr backend wiring (Phase C)
        # ------------------------------------------------------------------
        # When the user has selected the Wispr Flow backend we instantiate
        # the bridge here so the heavy import (openWakeWord, Silero) does
        # not happen at module load. Models load inside `bridge.start()`,
        # which we invoke from `run()` so the load happens off the main
        # init path (matches the Whisper-on-run model).
        if self._stt_backend == "wispr":
            self._ensure_wispr_bridge(from_init=True)

    def stop(self) -> None:
        """Stop the voice listener."""
        self._should_stop = True
        if self._porcupine is not None:
            try:
                self._porcupine.stop()
            except Exception as e:
                debug_log(f"Porcupine stop error: {e}", "voice")
        if self._control_bus is not None:
            try:
                self._control_bus.stop()
            except Exception as e:
                debug_log(f"control bus stop error: {e}", "voice")
        # Phase C: tear down the Wispr bridge (audio stream + key worker
        # + hot-window timer). Idempotent — see WisprBridge.stop().
        if self._wispr_bridge is not None:
            try:
                self._wispr_bridge.stop()
            except Exception as e:
                debug_log(f"WisprBridge stop error: {e}", "voice")

    def reconnect_audio(self) -> bool:
        """Re-resolve + reopen the wake mic after a Core Audio device change.

        Routed from the device watcher's debounced callback. Delegates to the
        Wispr bridge (the only backend that owns a wake-mic stream); a no-op in
        whisper mode. Fail-open: never raises. Returns True only if a stream was
        actually reopened.
        """
        bridge = self._wispr_bridge
        if bridge is None:
            return False
        try:
            return bool(bridge.reconnect())
        except Exception as e:  # pragma: no cover - defensive
            debug_log(f"reconnect_audio: bridge.reconnect raised ({e!r})", "voice")
            return False

    # ── In-process STT backend hot-switch ────────────────────────────────

    def _ensure_wispr_bridge(self, from_init: bool = False) -> bool:
        """(Re)create the Wispr bridge if needed. Returns True if usable.

        Called from ``__init__`` (when stt_backend == "wispr") and from
        ``_run_wispr_backend`` so a whisper→wispr hot-switch builds a fresh
        bridge (teardown nulls it). The heavy imports (openWakeWord, Silero)
        happen here, not at module load. On failure during init we fall back
        to whisper; on failure during a live switch we report False and let
        run()'s dispatcher revert to the previous backend.
        """
        if self._wispr_bridge is not None:
            return True
        try:
            from .wispr_bridge import WisprBridge
            self._wispr_bridge = WisprBridge(
                self.cfg,
                on_transcription=self.feed_transcript,
                on_wake=self._on_wispr_wake,
                on_dictation_end=self._on_wispr_dictation_end,
                on_stop=self._handle_wispr_stop,
                on_wispr_unavailable=self._on_wispr_unavailable,
            )
            debug_log("WisprBridge instantiated (start deferred to run())", "voice")
            return True
        except Exception as e:
            debug_log(f"WisprBridge instantiation failed: {e}", "voice")
            print(f"  ⚠️  WisprBridge unavailable ({e})", flush=True)
            self._wispr_bridge = None
            if from_init:
                # Init-time fallback: degrade to local Whisper so the daemon
                # still comes up with a working STT path.
                self._stt_backend = "whisper"
            return False

    def _teardown_stt_runtime(self, backend: str) -> None:
        """Release the resources owned by ``backend`` before re-dispatching.

        Whisper → drop the model reference and free CUDA memory (so a switch
        to Wispr returns VRAM to a co-resident LLM). Wispr → stop the bridge
        and null it so the next whisper→wispr switch builds a fresh one.
        Never raises — teardown must not wedge the dispatcher.
        """
        try:
            if backend == "wispr":
                if self._wispr_bridge is not None:
                    try:
                        self._wispr_bridge.stop()
                    except Exception as e:
                        debug_log(f"teardown: wispr bridge stop error ({e!r})", "voice")
                    self._wispr_bridge = None
            else:
                self.model = None
                self._whisper_backend = None
                try:
                    import gc
                    gc.collect()
                    import torch  # local import: optional dep
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
        except Exception as e:  # pragma: no cover - defensive
            debug_log(f"_teardown_stt_runtime({backend}) raised: {e!r}", "voice")

    def request_stt_switch(self, new_backend: str) -> bool:
        """Ask the listener to switch STT backend in-process. Thread-safe.

        Returns True if a switch was scheduled, False if it was a no-op /
        invalid. The actual swap happens on the listener thread the next time
        the active backend loop checks its top-of-loop guard — so any
        in-flight transcription completes before the backend is torn down.
        """
        new_backend = (new_backend or "").strip().lower()
        if new_backend not in ("whisper", "wispr"):
            debug_log(f"request_stt_switch: ignoring invalid backend {new_backend!r}", "voice")
            return False
        if new_backend == self._stt_backend and not self._switch_event.is_set():
            return False
        self._pending_backend = new_backend
        self._switch_event.set()
        debug_log(f"request_stt_switch: scheduled switch → {new_backend}", "voice")
        return True

    def _consume_manual_finalize(self) -> bool:
        """Atomically read-and-clear the manual-finalize handshake.

        Returns True if a manual finalize was pending (and clears it, plus the
        manual-trigger flag) so the audio loop can dispatch exactly once. The
        lock is held only around the flag read/clear, never across the
        subsequent finalize/dispatch work.
        """
        with self._control_flags_lock:
            requested = self._manual_finalize_requested
            if requested:
                self._manual_finalize_requested = False
                self._manual_trigger_active = False
            return requested

    def _handle_control_command(self, command: str) -> Optional[str]:
        """Dispatch a single control-bus command. Runs on a bus worker thread."""
        cmd = command.strip().upper()
        if cmd == "PING":
            return "PONG"
        if cmd == "STOP":
            self.reset_everything()
            return "OK STOP"
        if cmd == "MUTE":
            # If listening was manually triggered, treat mute as "I'm done
            # speaking". Resolve the new flag state under the lock, then drop
            # the lock before any I/O (UI publish, bridge pause/resume).
            with self._control_flags_lock:
                manual_finalize = (
                    self._manual_trigger_active and self.state_manager.is_collecting()
                )
                if manual_finalize:
                    self._manual_finalize_requested = True
                    self._muted = True
                else:
                    self._muted = not self._muted
                muted = self._muted
            if manual_finalize:
                print("🔇 Mic muted + manual finalize requested via control bus", flush=True)
            else:
                print(f"🔇 Mic {'muted' if muted else 'unmuted'} via control bus", flush=True)
            # Sync mute state to React UI
            try:
                from .. import api_server
                api_server.publish_state(isMuted=muted)
            except Exception:
                pass
            # Wispr backend: propagate mute to the bridge so wake detection
            # actually stops (mic stays open but wake model never fires).
            if self._stt_backend == "wispr" and self._wispr_bridge is not None:
                try:
                    if muted:
                        self._wispr_bridge.pause()
                    else:
                        self._wispr_bridge.resume()
                except Exception as e:
                    debug_log(f"bridge.pause/resume failed: {e!r}", "voice")
            return f"OK MUTED={muted}"
        if cmd == "UNMUTE":
            with self._control_flags_lock:
                self._muted = False
            print("🔊 Mic unmuted via control bus", flush=True)
            # Sync mute state to React UI
            try:
                from .. import api_server
                api_server.publish_state(isMuted=False)
            except Exception:
                pass
            # Wispr backend: resume wake detection.
            if self._stt_backend == "wispr" and self._wispr_bridge is not None:
                try:
                    self._wispr_bridge.resume()
                except Exception as e:
                    debug_log(f"bridge.resume failed: {e!r}", "voice")
            return "OK UNMUTED"
        if cmd == "TRIGGER":
            # Wispr backend: tap the hands-free shortcut directly, bypassing
            # wake detection. The bridge handles state + key worker queuing.
            if self._stt_backend == "wispr" and self._wispr_bridge is not None:
                try:
                    ok = self._wispr_bridge.trigger_now()
                except Exception as e:
                    debug_log(f"bridge.trigger_now failed: {e!r}", "voice")
                    return f"ERROR bridge.trigger_now: {e}"
                # Ensure UI knows we're unmuted (Trigger auto-unmutes)
                with self._control_flags_lock:
                    was_muted = self._muted
                    if was_muted:
                        self._muted = False
                if was_muted:
                    try:
                        from .. import api_server
                        api_server.publish_state(isMuted=False)
                    except Exception:
                        pass
                return "OK TRIGGER" if ok else "OK ALREADY_DICTATING"
            # Whisper backend: legacy collection-state trigger.
            if self.state_manager.is_collecting():
                return "OK ALREADY_COLLECTING"
            with self._control_flags_lock:
                self._manual_trigger_active = True
                self._manual_finalize_requested = False
                was_muted = self._muted
                if was_muted:
                    self._muted = False
            self._wake_timestamp = None
            self.state_manager.cancel_hot_window_activation()
            self._clear_audio_buffers()
            self._start_collection("")
            self._start_thinking_tune()
            # Ensure UI knows we're unmuted (Trigger Now auto-unmutes)
            if was_muted:
                try:
                    from .. import api_server
                    api_server.publish_state(isMuted=False)
                except Exception:
                    pass
            debug_log("manual trigger activated", "voice")
            print("⚡ Manual trigger — listening now", flush=True)
            return "OK TRIGGER"
        debug_log(f"control bus: unknown command '{cmd}'", "voice")
        return f"ERROR unknown command '{cmd}'"

    def reset_everything(self) -> None:
        """STOP-button entry point.

        Interrupts the currently-playing TTS, asks any in-flight LLM call to
        unwind on its next polling boundary, clears dialogue memory and wake
        state, drains audio buffers, and stops the thinking tune. Safe to
        call repeatedly and from any thread.
        """
        print("⏹  STOP — TTS interrupted, LLM cancelled, memory cleared", flush=True)
        # Open the post-abort suppression window FIRST, so even if a step below
        # raises, a late transcript captured around this STOP is still dropped by
        # feed_transcript. A fresh wake (_on_wispr_wake) clears the window.
        try:
            suppress_sec = float(getattr(self.cfg, "wispr_post_abort_suppress_sec", 1.5))
        except (TypeError, ValueError):
            suppress_sec = 1.5
        self._post_abort_suppress_until = time.monotonic() + max(0.0, suppress_sec)
        # TTS interrupt
        try:
            if self.tts is not None:
                self.tts.interrupt()
        except Exception as e:
            debug_log(f"reset_everything: tts interrupt failed: {e}", "voice")
        # Signal LLM cancellation. The reply engine + control loops poll
        # this between turns and on long operations.
        try:
            self._llm_cancel_event.set()
        except Exception:
            pass
        # Clear dialogue context (best-effort — the memory object may or may
        # not expose .clear(); we try common variants).
        if self.dialogue_memory is not None:
            for method_name in ("clear", "reset", "wipe"):
                fn = getattr(self.dialogue_memory, method_name, None)
                if callable(fn):
                    try:
                        fn()
                        break
                    except Exception:
                        continue
        # Wake + hot window
        self._wake_timestamp = None
        try:
            self.state_manager.cancel_hot_window_activation()
        except Exception:
            pass
        # Audio buffers + thinking tune
        try:
            self._clear_audio_buffers()
        except Exception:
            pass
        try:
            self._stop_thinking_tune()
        except Exception:
            pass
        self.state_manager.stop()
        self._stop_thinking_tune()
        with self._control_flags_lock:
            self._manual_trigger_active = False
            self._manual_finalize_requested = False
        # Phase F: drop the speaking flag on the Wispr bridge (if any) so
        # subsequent stop-keywords aren't routed through on_stop after the
        # interrupt has already torn down the TTS.
        try:
            self._set_bridge_speaking(False)
        except Exception:
            pass
        # STOP must also cancel the Wispr side: force recording OFF and discard
        # any transcript captured around the STOP so it never reaches the
        # assistant (the LLM cancel only unwinds at reply-engine boundaries).
        bridge = getattr(self, "_wispr_bridge", None)
        if bridge is not None:
            try:
                bridge.abort()
            except Exception as e:
                debug_log(f"reset_everything: wispr abort failed: {e}", "voice")

    # ------------------------------------------------------------------
    # Query publishing helpers (sync UI text display with WebSocket state)
    # ------------------------------------------------------------------
    def _publish_query(self) -> None:
        """Broadcast the current pending query to the React UI via WebSocket."""
        try:
            from .. import api_server
            api_server.publish_state(query=self.state_manager.get_pending_query())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tier 1 / Tier 2 intent cascade
    # ------------------------------------------------------------------
    # Replaces the single intent_judge LLM call with a three-tier cascade:
    #   Tier 0 — fast-path regex SHORT-CIRCUIT (already inline above; <1ms).
    #   Tier 1 — heuristic classifier (Aho-Corasick + ONNX, <2ms, ~88%).
    #   Tier 2 — fused intent engine (one structured LLM call, ~3-5s).
    # Each tier either produces a verdict (returned as an IntentJudgment so
    # the existing downstream wake-word / echo / hot-window plumbing keeps
    # working unchanged) or escalates to the next. The legacy intent_judge
    # remains the final fallback when every new tier is disabled or fails.
    # ------------------------------------------------------------------

    def _cascade_cache_key(
        self,
        current_text: str,
        in_hot_window: bool,
        last_tts_text: str,
    ) -> str:
        """MD5 of (text, hot_window, last_tts_text) — matches intent_judge.py
        cache key shape so semantics are identical across producers."""
        import hashlib as _hashlib
        raw = f"{current_text}|{int(bool(in_hot_window))}|{last_tts_text or ''}"
        return _hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()

    def _cascade_cache_get(self, key: str) -> Optional["IntentJudgment"]:
        entry = self._cascade_cache.get(key)
        if entry is None:
            return None
        ts, judgment = entry
        if time.time() - ts >= self._CASCADE_CACHE_TTL_SEC:
            self._cascade_cache.pop(key, None)
            return None
        # Refresh recency so popular keys survive eviction.
        self._cascade_cache.move_to_end(key)
        return judgment

    def _cascade_cache_put(self, key: str, judgment: "IntentJudgment") -> None:
        self._cascade_cache[key] = (time.time(), judgment)
        self._cascade_cache.move_to_end(key)
        while len(self._cascade_cache) > self._CASCADE_CACHE_MAX_ENTRIES:
            self._cascade_cache.popitem(last=False)

    def _fused_to_judgment(
        self,
        fused: "FusedJudgment",
        text_lower: str,
        in_hot_window: bool,
    ) -> "IntentJudgment":
        """Adapt a FusedJudgment into the IntentJudgment shape expected by the
        existing downstream logic. We stash tools/plan on the listener so a
        future reply.engine refactor can pick them up without re-routing.
        """
        # Intent mapping: 'stop' is the only one with explicit stop semantics;
        # 'directed' / 'query' / 'clarification' all funnel into "directed".
        # Confidence buckets are preserved (high/med/low).
        is_stop = (fused.intent == "stop")
        directed = fused.intent in ("directed", "query", "stop", "clarification")

        # Stash the fused output for the engine's fast path. A DEGRADED
        # judgment (timeout / parse failure) must pass None, not []: an empty
        # list means "the model decided no tools", which makes the engine skip
        # its own router — locking a fused miss into a wrong "I can't do that"
        # reply. None lets the legacy router+planner run instead.
        if getattr(fused, "degraded", False):
            self._last_fused_tools = None
            self._last_fused_plan = None
        else:
            self._last_fused_tools = list(fused.tools or [])
            self._last_fused_plan = list(fused.plan or [])

        return IntentJudgment(
            directed=directed,
            query=text_lower,  # fused engine doesn't extract a cleaned query;
                               # use the raw text — the same as judge fallback path.
            stop=is_stop,
            confidence=fused.confidence if fused.confidence in ("high", "medium", "low") else
                       ("high" if fused.confidence == "high" else
                        "medium" if fused.confidence == "med" else "low"),
            reasoning=f"fused:{fused.intent}/{fused.confidence} {fused.explanation}"[:200],
            raw_response=fused.llm_raw,
        )

    def _classifier_to_judgment(
        self,
        result: "ClassifierResult",
        text_lower: str,
    ) -> "IntentJudgment":
        """Adapt a ClassifierResult into IntentJudgment. The classifier returns
        a domain intent label (e.g. 'spotify_play') not the directed/stop axis,
        so we treat any med-or-better classification as 'directed' with the
        raw text as the query — same as the high-confidence judge fallback."""
        return IntentJudgment(
            directed=True,
            query=text_lower,
            stop=(result.intent == "stop"),
            confidence=result.confidence if result.confidence in ("high", "medium", "low") else
                       ("medium" if result.confidence == "med" else result.confidence),
            reasoning=f"heuristic:{result.intent}/{result.tier}/score={result.score:.2f}",
            raw_response="",
        )

    def _run_intent_cascade(
        self,
        *,
        text_lower: str,
        could_be_hot_window: bool,
        last_tts_text: str,
    ) -> tuple[Optional["IntentJudgment"], str]:
        """Run Tier 1 → Tier 2 cascade. Returns (judgment, source_tag).

        source_tag is one of:
          'cache' / 'tier1_high' / 'tier1_med' / 'tier2' / 'fallback'
        'fallback' means every cascade tier was unavailable/failed — caller
        should run the legacy intent_judge as the final safety net.

        Never raises; on any exception falls through to 'fallback'.
        """
        # Every classification starts with a CLEAN fused stash; only a real
        # Tier 2 judgment may populate it. Without this, a Tier 1 / cache hit
        # leaves the previous value behind — the boot-time [] then reads as
        # "the model decided no tools", the engine skips its router, and the
        # first window command after a restart gets a confabulated refusal.
        self._last_fused_tools = None
        self._last_fused_plan = None

        # Cache lookup first — same shape as intent_judge's cache so the two
        # systems don't compete on duplicate (text, hot_window, tts) tuples.
        cache_key = self._cascade_cache_key(text_lower, could_be_hot_window, last_tts_text)
        cached = self._cascade_cache_get(cache_key)
        if cached is not None:
            debug_log(
                f"⚡ Cascade cache hit: directed={cached.directed} stop={cached.stop} "
                f"conf={cached.confidence}",
                "voice",
            )
            return cached, "cache"

        # ---- Tier 1: heuristic classifier --------------------------------
        if self._heuristic_classifier is not None:
            try:
                t_start = time.time()
                result = self._heuristic_classifier.classify(text_lower)
                elapsed_ms = (time.time() - t_start) * 1000.0
                debug_log(
                    f"Tier 1 heuristic: intent={result.intent} conf={result.confidence} "
                    f"score={result.score:.2f} tier={result.tier} ({elapsed_ms:.1f}ms)",
                    "voice",
                )

                # Tool-implying intents must NOT short-circuit Tier 2: the
                # heuristic answers "was Jarvis addressed?" but cannot pick
                # tools or arguments. Accepting them here sent variations like
                # "Open Spotify on the left side" straight to the engine with
                # no fused routing — and the wrong tools got picked. Plain
                # commands ("άνοιξε spotify") are already 0ms via the Tier 0
                # fast-path regexes, so deferring costs nothing common.
                # time_current/time_date are NOT in this list: the heuristic
                # misfired conf=high on unrelated queries ("how is NVDA doing
                # today?", "ποια apps είναι ανοιχτά") because of the bare
                # time-ish token ("today"/"now"), which skipped the fused
                # router and sent them down the legacy path with wrong args.
                # Real time questions are already served at 0ms by the Tier 0
                # regex fast-path, so deferring time intents costs nothing.
                _tier1_local = result.intent in (
                    "general_chat", "clarification", "stop",
                )
                _can_defer = self._fused_intent is not None and not _tier1_local

                # Aho-Corasick + high confidence → fast-path equivalent.
                if result.tier == "aho_corasick" and result.confidence == "high":
                    if _can_defer:
                        debug_log(
                            f"Tier 1 {result.intent} (high) needs tool routing "
                            f"— deferring to Tier 2 fused",
                            "voice",
                        )
                    else:
                        print(
                            f"  ⚡ Tier 1 heuristic: {result.intent} "
                            f"(conf=high, {elapsed_ms:.1f}ms)",
                            flush=True,
                        )
                        judgment = self._classifier_to_judgment(result, text_lower)
                        self._cascade_cache_put(cache_key, judgment)
                        return judgment, "tier1_high"

                # Med confidence (with the lowered 0.5 threshold) → accept
                # locally, skip LLM. Treat as directed with raw text as query.
                if result.confidence == "med" and not _can_defer:
                    print(
                        f"  ⚡ Tier 1 heuristic: {result.intent} "
                        f"(conf=med, {elapsed_ms:.1f}ms)",
                        flush=True,
                    )
                    judgment = self._classifier_to_judgment(result, text_lower)
                    self._cascade_cache_put(cache_key, judgment)
                    return judgment, "tier1_med"

                # Low confidence — fall through to Tier 2.
            except Exception as e:  # noqa: BLE001
                debug_log(f"Tier 1 heuristic classifier error (non-fatal): {e}", "voice")
                # Fall through to Tier 2.

        # ---- Tier 2: fused intent engine ---------------------------------
        if self._fused_intent is not None:
            try:
                t_start = time.time()
                # Pull current language from the rolling detector. Default to 'en'.
                lang_hint = (getattr(self, "_last_detected_language", "") or "en").lower()
                language = "el" if lang_hint.startswith("el") else "en"

                # If a forgetMemory deletion is awaiting confirmation, tell the
                # router so it reliably classifies this turn as assent/refusal in
                # any language. This keeps a refusal ("no, keep it") from routing
                # to forgetMemory at all (which would otherwise risk a delete via
                # the tool's subject-match), and an assent to forgetMemory.
                _pending_confirmation = None
                try:
                    from ..tools.builtin.forget_memory import has_fresh_pending as _fm_pending
                    if _fm_pending():
                        _pending_confirmation = "forgetMemory"
                except Exception:
                    _pending_confirmation = None

                fused = self._fused_intent.classify_route_plan(
                    transcript=text_lower,
                    in_hot_window=could_be_hot_window,
                    language=language,
                    last_tts_text=last_tts_text or None,
                    pending_confirmation=_pending_confirmation,
                )
                elapsed_s = time.time() - t_start
                print(
                    f"  🧠 Tier 2 fused intent: {fused.intent} ({elapsed_s:.2f}s)",
                    flush=True,
                )
                debug_log(
                    f"Tier 2 fused: intent={fused.intent} conf={fused.confidence} "
                    f"tools={len(fused.tools)} plan_len={len(fused.plan)} "
                    f"({elapsed_s*1000:.0f}ms)",
                    "voice",
                )
                judgment = self._fused_to_judgment(fused, text_lower, could_be_hot_window)
                self._cascade_cache_put(cache_key, judgment)
                return judgment, "tier2"
            except Exception as e:  # noqa: BLE001
                debug_log(f"Tier 2 fused intent error (non-fatal): {e}", "voice")
                # Fall through to legacy fallback.

        # ---- Fallback ----------------------------------------------------
        return None, "fallback"

    def _start_collection(self, text: str) -> None:
        """Wrap state_manager.start_collection + publish query to UI.

        Wispr-flow short-circuit: when ``_process_transcript`` ran with
        ``source="wispr"`` it sets ``self._wispr_current_source`` to
        ``"wispr"`` for the lifetime of that call. In that case, the
        transcript is ALREADY complete (Wispr Flow finalised the
        utterance externally — no more partials will arrive via the
        audio callback to trigger the silence-timeout finalize). We
        publish state for UI visibility, then dispatch immediately to
        the reply engine and clear the collection so the next utterance
        isn't accidentally appended to this one.
        """
        self.state_manager.start_collection(text)
        self._publish_query()
        if getattr(self, "_wispr_current_source", None) == "wispr" and text.strip():
            debug_log(
                "Wispr short-circuit: dispatching immediately (skipping "
                "silence-timeout collection wait)",
                "voice",
            )
            # Clear the collection BEFORE dispatch so state_manager is
            # ready for the next utterance. Capture pending text first.
            try:
                pending = self.state_manager.clear_collection() or text
            except Exception:
                pending = text
            self._dispatch_query(pending)

    def _add_to_collection(self, text: str) -> None:
        """Wrap state_manager.add_to_collection + publish query to UI."""
        self.state_manager.add_to_collection(text)
        self._publish_query()

    def _start_thinking_tune(self) -> None:
        """Start the thinking tune when processing a query."""
        if (self.cfg.tune_enabled and
            self._tune_player is None and
            (self.tts is None or not self.tts.is_speaking())):
            from ..output.tune_player import TunePlayer
            self._tune_player = TunePlayer(enabled=True)
            self._tune_player.start_tune()

    def _stop_thinking_tune(self) -> None:
        """Stop the thinking tune and revert face state to IDLE."""
        if self._tune_player is not None:
            self._tune_player.stop_tune()
            self._tune_player = None
            try:
                from desktop_app.face_widget import get_jarvis_state, JarvisState
                get_jarvis_state().set_state(JarvisState.IDLE)
            except ImportError:
                pass
            except Exception:
                pass

    def _is_thinking_tune_active(self) -> bool:
        """Check if thinking tune is currently active."""
        return self._tune_player is not None and self._tune_player.is_playing()

    def _set_face_state_listening(self) -> None:
        """Set the desktop face widget to LISTENING state."""
        try:
            from desktop_app.face_widget import get_jarvis_state, JarvisState
            get_jarvis_state().set_state(JarvisState.LISTENING)
        except ImportError:
            pass
        except Exception as e:
            debug_log(f"failed to set face state to LISTENING: {e}", "voice")

    def _set_face_state_idle(self) -> None:
        """Reset the desktop face widget to IDLE after a rejected/ignored utterance.

        On the Wispr path ``_on_wispr_wake`` shows LISTENING but starts no
        thinking tune, so ``_stop_thinking_tune``'s IDLE reset (guarded by
        ``tune_player is not None``) is skipped and the orb stays stuck on
        LISTENING. Resetting here unsticks it. Skips while Jarvis is speaking so
        it never clobbers the SPEAKING state mid-reply.
        """
        try:
            if self.tts is not None and self.tts.is_speaking():
                return
            from desktop_app.face_widget import get_jarvis_state, JarvisState
            get_jarvis_state().set_state(JarvisState.IDLE)
        except ImportError:
            pass
        except Exception as e:
            debug_log(f"failed to set face state to IDLE: {e}", "voice")

    def track_tts_start(self, tts_text: str) -> None:
        """Called when TTS starts speaking."""
        if self.tts and self.tts.enabled:
            # Calculate baseline energy from recent audio samples
            baseline_energy = 0.0045  # default
            if self._recent_audio_energy:
                baseline_energy = sum(self._recent_audio_energy) / len(self._recent_audio_energy)

            self.echo_detector.track_tts_start(tts_text, baseline_energy)

    def _log_tts_summary(self, text: str) -> None:
        """Emit a single summary line for completed TTS and log any buffer delay."""
        from ..debug import info_log
        duration = self.echo_detector._tts_exact_duration if self.echo_detector else None
        chars = len(text) if text else 0
        preview = text[:60] + "..." if text and len(text) > 60 else (text or "")
        duration_str = f", TTS: {duration:.1f}s" if duration else ""
        info_log(f'🗣️ SPEAKING → "{preview}" ({chars} chars{duration_str}) ✓')

        # Log buffer delay: time from synthesis completion to callback firing
        if self._last_tts_synthesis_time > 0:
            buffer_delay = time.time() - self._last_tts_synthesis_time
            if buffer_delay > 0.5:
                info_log(f"⏳ TTS buffered: {buffer_delay:.1f}s → callback fired")
            self._last_tts_synthesis_time = 0.0

    def activate_hot_window(self) -> None:
        """Activate hot window after TTS completion."""
        # Track TTS finish time for echo detection
        self.echo_detector.track_tts_finish()

        if not self.cfg.hot_window_enabled:
            debug_log("hot window disabled in config, skipping", "voice")
            return

        # Schedule delayed hot window activation
        self.state_manager.schedule_hot_window_activation(self.cfg.voice_debug)

    def _acknowledge_wake_only(self, text_lower: str) -> None:
        """Bare wake word: speak a quick ack and open a listening window.

        NOT a reply-engine turn — the whole point is to be instant and to
        keep the floor open for the user's actual command. The window uses
        ``activate_hot_window_now`` (custom duration, independent of the
        post-reply ``hot_window_enabled`` flag: the user explicitly summoned
        the assistant, so it must listen).
        """
        self._wake_timestamp = None
        self._stop_thinking_tune()
        try:
            self._transcript_buffer.mark_segment_processed(text_lower)
        except Exception:
            pass
        self._clear_audio_buffers()

        ack = str(getattr(self.cfg, "wake_ack_text", "Yes, Boss?") or "Yes, Boss?")
        window_sec = float(getattr(self.cfg, "wake_ack_window_sec", 8.0) or 8.0)
        info_log(f"👂 Wake acknowledged → listening {window_sec:.0f}s for the command")
        if self.tts:
            try:
                self.tts.speak(ack)
            except Exception as e:
                debug_log(f"wake ack TTS failed (non-fatal): {e}", "voice")
        self.state_manager.activate_hot_window_now(window_sec)

    def _process_transcript(self, text: str, utterance_energy: float = 0.0, utterance_start_time: float = 0.0, utterance_end_time: float = 0.0, source: str = "whisper") -> None:
        """
        Process a transcript from speech recognition.

        Args:
            text: Transcribed text from audio
            utterance_energy: Pre-calculated energy from the utterance frames
            source: "whisper" for the local Whisper path (wake word lives IN
                the text, so we reset and let the wake-check re-set it) or
                "wispr" for the Wispr Flow bridge (openWakeWord validated the
                wake EXTERNALLY before PTT started, so the text never contains
                the wake word — we synthesise a wake_timestamp instead).
        """
        if not text or not text.strip():
            # Check for timeouts
            if self.state_manager.check_collection_timeout():
                query = self.state_manager.clear_collection()
                if query.strip():
                    self._dispatch_query(query)

            # Check hot window expiry
            self.state_manager.check_hot_window_expiry(self.cfg.voice_debug)
            return

        text_lower = text.strip().lower()

        # Reset wake timestamp — it must reflect only the current utterance.
        # If this utterance contains a wake word, the early-beep check below
        # will set it. Without this reset, a prior rejected wake-worded
        # utterance would vouch for subsequent unrelated utterances via the
        # `_wake_timestamp is not None` guard in the intent-judge accept path.
        #
        # EXCEPTION: when source == "wispr", openWakeWord already validated
        # the wake word out-of-band (the bridge wouldn't have PTT'd without
        # a wake detection or a hot-follow-up speech-onset event). The text
        # itself never contains the wake word, so the in-text wake-check at
        # line ~1873 would fail and the cascade would reject. Instead, we
        # synthesise a fresh wake_timestamp from the utterance time so the
        # `has_engagement_signal` gate accepts the transcript.
        if source == "wispr":
            self._wake_timestamp = utterance_start_time or time.time()
            debug_log(
                f"_process_transcript source=wispr → wake_timestamp synthesised "
                f"({self._wake_timestamp:.2f})",
                "voice",
            )
        else:
            self._wake_timestamp = None

        # Set the current-source flag so _start_collection (which is called
        # from many places downstream after intent acceptance) knows to
        # short-circuit and dispatch immediately instead of waiting for a
        # silence-timeout collection finalize that will never fire (Wispr
        # already produced the COMPLETE utterance — no more partials will
        # arrive via the audio callback to trigger collection-timeout).
        # Cleared in the finally block below so subsequent non-wispr
        # invocations behave normally.
        self._wispr_current_source = source

        start_time_str = datetime.fromtimestamp(utterance_start_time).strftime('%H:%M:%S.%f')[:-4] if utterance_start_time > 0 else "N/A"
        end_time_str = datetime.fromtimestamp(utterance_end_time).strftime('%H:%M:%S.%f')[:-4] if utterance_end_time > 0 else "N/A"
        debug_log(f"heard: '{text}' (utterance from {start_time_str} to {end_time_str})", "voice")

        # Track if this input was received during TTS (for logging purposes)
        received_during_tts = self.tts and self.tts.is_speaking()

        # --- Early echo check + early beep ---
        # Check for echo BEFORE starting beep and BEFORE intent judge.
        # This prevents: false beeps on echo, intent judge blocking the audio
        # loop for seconds on echo, and hot window extending from echo resets.
        if not received_during_tts and not self._is_thinking_tune_active():
            in_hot_window = self.state_manager.was_speech_during_hot_window(
                utterance_start_time, utterance_end_time
            )
            if in_hot_window:
                # Fuzzy echo check — instant, no intent judge needed.
                # Only catches pure echo (transcript ≈ TTS text). Mixed
                # echo+speech chunks (user spoke over echo) go to the
                # intent judge which can extract the user's speech.
                last_tts_text = self.echo_detector._last_tts_text or ""
                if last_tts_text:
                    echo_score = fuzz.partial_ratio(
                        text_lower, last_tts_text.lower()
                    )
                    tts_words = len(last_tts_text.split())
                    text_words = len(text_lower.split())
                    is_pure_echo = (
                        echo_score >= 70
                        and text_words <= max(tts_words * 1.3, tts_words + 3)
                    )
                    if is_pure_echo:
                        # Before rejecting, try to salvage user speech appended
                        # after the echo prefix. Whisper commonly merges the tail
                        # of TTS echo with the user's follow-up into a single
                        # transcript; without salvage, the user's real speech
                        # would be dropped before the intent judge ever sees it.
                        # Try exact-word cleanup first (cheapest, most precise),
                        # then fall back to the rightmost-boundary scan which
                        # handles Whisper mis-transcriptions at the echo/speech
                        # join ("explores" → "laws") that exact matching can't.
                        salvaged = self.echo_detector.cleanup_leading_echo(text_lower)
                        if salvaged == text_lower:
                            salvaged_alt = self.echo_detector.salvage_after_echo_tail(text_lower)
                            if salvaged_alt:
                                salvaged = salvaged_alt
                        # Require ≥ min_salvage_words to avoid treating Whisper's
                        # echo-tail hallucinations ("…regions like Steneti") as
                        # genuine user speech. The threshold lives on the echo
                        # detector so every salvage site shares one policy.
                        min_words = self.echo_detector.min_salvage_words
                        if (salvaged != text_lower
                                and len(salvaged.split()) >= min_words):
                            debug_log(
                                f"salvaged user speech from hot-window echo+speech "
                                f"chunk: '{salvaged}'",
                                "voice",
                            )
                            print(
                                f"  ✂️ Stripped echo prefix, kept: \"{salvaged[:60]}"
                                f"{'...' if len(salvaged) > 60 else ''}\"",
                                flush=True,
                            )
                            self._transcript_buffer.update_last_segment_text(salvaged)
                            # text_lower now carries the salvaged query — the rest
                            # of _process_transcript reads from this variable.
                            text_lower = salvaged
                        else:
                            debug_log(f"🔇 Early echo rejection (score={echo_score}): \"{text_lower}\"", "voice")
                            print(f"  🔇 Heard (echo): \"{text_lower[:50]}{'...' if len(text_lower) > 50 else ''}\"", flush=True)
                            return

                # Non-echo (or salvaged) in hot window — start beep
                self._start_thinking_tune()
                self._set_face_state_listening()
                debug_log("early beep: hot window active", "voice")
            else:
                # Not in hot window — check for wake word
                wake_word = getattr(self.cfg, "wake_word", "jarvis")
                aliases = list(set(getattr(self.cfg, "wake_aliases", [])) | {wake_word})
                fuzzy_ratio = float(getattr(self.cfg, "wake_fuzzy_ratio", 0.78))
                if is_wake_word_detected(text_lower, wake_word, aliases, fuzzy_ratio):
                    self._wake_timestamp = utterance_start_time
                    self._start_thinking_tune()
                    self._set_face_state_listening()
                    debug_log("early beep: wake word detected", "voice")

                    # STRICT-PREFIX RULE (cold-start only): anything BEFORE the
                    # first wake-word occurrence is discarded. The user wants
                    # "Jarvis" to be the first meaningful token; without this,
                    # "I just ate a big monk chervish jarvis" would send the
                    # food sentence as a query. Hot window follows-ups are not
                    # affected (they live in the `if` branch above).
                    pos, mlen = find_wake_word_position(
                        text_lower, wake_word, aliases, fuzzy_ratio,
                    )
                    if pos > 0:
                        discarded = text_lower[:pos].rstrip()
                        truncated = text_lower[pos + mlen:].lstrip(" ,.;:!?").strip()
                        print(
                            f"  🗑️  Discarded prefix before wake word: \"{discarded}\"",
                            flush=True,
                        )
                        debug_log(
                            f"strict-prefix: kept '{truncated}' (was '{text_lower}')",
                            "voice",
                        )
                        text_lower = truncated
                        self._transcript_buffer.update_last_segment_text(text_lower)
                    elif pos == 0:
                        # Wake word at the very start — strip it so the rest of
                        # the pipeline sees only the query portion.
                        after = text_lower[mlen:].lstrip(" ,.;:!?").strip()
                        if after:
                            debug_log(
                                f"strict-prefix: stripped leading wake word; kept '{after}'",
                                "voice",
                            )
                            text_lower = after
                            self._transcript_buffer.update_last_segment_text(text_lower)

        # Echo rejection & stop commands — only while TTS is actively playing.
        # After TTS finishes, the intent judge handles everything (echo detection,
        # hot window follow-ups, etc.) using full transcript context + last TTS text.
        if self.tts and self.tts.enabled and self.tts.is_speaking():
            # Stop command detection (fast, text-based)
            stop_commands = getattr(self.cfg, "stop_commands", ["stop", "quiet", "shush", "silence", "enough", "shut up"])
            if is_stop_command(text_lower, stop_commands):
                debug_log(f"stop command detected during TTS: {text_lower} (energy: {utterance_energy:.4f})", "voice")
                self.tts.interrupt()
                try:
                    while not self._audio_q.empty():
                        self._audio_q.get_nowait()
                except Exception:
                    pass
                return

            # Echo rejection during active TTS
            should_reject = self.echo_detector.should_reject_as_echo(
                text_lower, utterance_energy, True,
                getattr(self.cfg, 'tts_rate', 200), utterance_start_time
            )
            if should_reject:
                # Try to salvage user speech appended after echo
                salvaged = self.echo_detector.cleanup_leading_echo_during_tts(
                    text_lower,
                    getattr(self.cfg, 'tts_rate', 200),
                    utterance_start_time,
                )
                min_words = self.echo_detector.min_salvage_words
                if (salvaged and salvaged.strip() and salvaged != text_lower
                        and len(salvaged.split()) >= min_words):
                    debug_log(f"salvaged user speech from echo during TTS: '{salvaged}'", "voice")
                    self._transcript_buffer.update_last_segment_text(salvaged)
                    text_lower = salvaged
                else:
                    debug_log(f"echo rejected during TTS: '{text_lower[:50]}'", "echo")
                    print(f"  🔇 Heard (echo): \"{text_lower[:50]}{'...' if len(text_lower) > 50 else ''}\"", flush=True)
                    return

        # Salvage user speech from merged echo+speech chunks.
        # When Whisper delivers a single transcript containing TTS echo followed by
        # user speech (e.g. "I can only provide... Well you can search for it"), the
        # echo portion was captured during TTS but the transcript arrives after TTS
        # finishes. Try to strip the leading echo and use just the user's speech.
        # Skip entirely if there's no prior TTS — nothing to match against.
        last_tts_text_for_salvage = self.echo_detector._last_tts_text or ""
        last_tts_finish = self.echo_detector._last_tts_finish_time or 0.0
        # Use echo_tolerance as buffer — speaker/mic latency means the utterance
        # may start slightly after TTS finish yet still contain the echo.
        echo_tol = self.echo_detector.echo_tolerance
        if (last_tts_text_for_salvage and last_tts_finish > 0
                and utterance_start_time > 0
                and utterance_start_time < last_tts_finish + echo_tol):
            salvaged = self.echo_detector._salvage_suffix_from_echo(
                text_lower,
                getattr(self.cfg, 'tts_rate', 200),
                utterance_start_time,
            )
            # If the prefix-based salvage fails or truncates too aggressively
            # (Whisper-mangled echo boundary → exact cleanup misses; fuzzy
            # prefix iteration prefers shortest suffix), fall through to the
            # rightmost-boundary scan which recovers the full follow-up.
            boundary_salvaged = self.echo_detector.salvage_after_echo_tail(text_lower)
            if boundary_salvaged and (
                salvaged is None or salvaged == text_lower
                or len(boundary_salvaged.split()) > len(salvaged.split())
            ):
                salvaged = boundary_salvaged
            min_words = self.echo_detector.min_salvage_words
            if (salvaged and salvaged.strip() and salvaged != text_lower
                    and len(salvaged.split()) >= min_words):
                debug_log(f"salvaged user speech from merged echo+speech chunk: '{salvaged}'", "voice")
                self._transcript_buffer.update_last_segment_text(salvaged)
                text_lower = salvaged

        # Check hot window expiry
        self.state_manager.check_hot_window_expiry(self.cfg.voice_debug)

        # Intent judge — the single decision-maker for all post-TTS input.
        # Gets full transcript context, last TTS text, and hot window state.
        # Handles: echo detection, wake word queries, hot window follow-ups.
        # During active TTS, skip short utterances (<=3 words) as those are
        # handled by stop command detection above.
        is_speaking_now = self.tts and self.tts.is_speaking()
        intent_judgment = None

        # Determine if this could be a hot window follow-up.
        # Only use formal hot window state — no time-based grace period.
        # The state manager already handles the timing (echo_tolerance
        # delay before activation, hot_window_seconds before expiry).
        # A generous grace period caused false hot window claims after
        # the user had already seen "Returning to wake word mode".
        could_be_hot_window = self.state_manager.was_speech_during_hot_window(
            utterance_start_time, utterance_end_time
        )

        # Use the upgraded intent judge if available (with full transcript context)
        # Allow during TTS for longer utterances (>3 words) that might be user responses
        word_count = len(text_lower.split())
        skip_intent_judge_during_tts = is_speaking_now and word_count <= 3

        # Gate the intent judge on an engagement signal. Without this check the
        # judge was called on every ambient utterance, blocking the audio loop
        # for up to `timeout_sec` on each background chatter — which could
        # cascade into UI freezes when many utterances queued up during a slow
        # or loaded Ollama. The judge adds value only when one of:
        #   1. A wake word was detected in the current utterance
        #   2. We are in (or pending) a hot window following TTS
        #   3. TTS is currently speaking (intent judge can catch responses / stops
        #      that the fast text-based stop command check missed)
        has_engagement_signal = (
            self._wake_timestamp is not None
            or could_be_hot_window
            or is_speaking_now
        )

        # FAST-PATH SHORT-CIRCUIT: when the user explicitly addresses the
        # assistant (wake word detected) AND the transcript matches a
        # registered pattern, skip the intent judge entirely and dispatch
        # the query directly. The intent judge call itself takes ~1-2s
        # with qwen3.5:9b — bypassing it makes action commands
        # ("next song", "παύση") feel genuinely instant.
        #
        # Excluded for hot-window follow-ups: per listening.spec.md the
        # judge is the canonical extractor for hot-window speech — it
        # strips fillers ("uh okay what's the weather…") and resolves
        # references ("what about this/that…") that the regex patterns
        # see only as literal tokens.
        if (
            has_engagement_signal
            and not could_be_hot_window
            and not is_speaking_now
            and not skip_intent_judge_during_tts
        ):
            try:
                from .fast_paths import match as _fp_match_early

                # Strip leading wake-word so the pattern can match the action
                # portion of the utterance (e.g. "hey jarvis next song" →
                # "next song"). Uses the same position-aware helper as the
                # strict-prefix rule above so we cover all ~80 configured
                # aliases plus fuzzy matches, not just a hardcoded handful.
                # Recompute the wake config locally — the strict-prefix block
                # may have been skipped (e.g. thinking tune already active from
                # a previous utterance) which would leave wake_word undefined.
                _wake_word = getattr(self.cfg, "wake_word", "jarvis")
                _aliases = list(set(getattr(self.cfg, "wake_aliases", [])) | {_wake_word})
                _fuzzy_ratio = float(getattr(self.cfg, "wake_fuzzy_ratio", 0.78))
                _stripped = text_lower
                _pos, _mlen = find_wake_word_position(
                    _stripped, _wake_word, _aliases, _fuzzy_ratio,
                )
                if _pos >= 0:
                    _after = _stripped[_pos + _mlen:].lstrip(" ,.;:!?")
                    if _after:
                        _stripped = _after

                # WAKE-ONLY SHORT-CIRCUIT: a bare "Hey Jarvis." means the
                # user paused for an acknowledgement. Dispatching it as a
                # query burned a fused call + a rambling chat reply (~20s of
                # TTS), and the actual command — spoken right after — arrived
                # with no wake signal active and was dropped. Ack instantly
                # and open a listening window for the command instead.
                if is_wake_only_utterance(text_lower, _wake_word, _aliases, _fuzzy_ratio):
                    self._acknowledge_wake_only(text_lower)
                    return

                _early_match = _fp_match_early(_stripped)
                if _early_match is not None:
                    print(
                        f"  ⚡ Fast-path SHORT-CIRCUIT (skipping intent judge): "
                        f"{_early_match.mcp_server}.{_early_match.tool_name}",
                        flush=True,
                    )
                    debug_log(
                        f"fast-path short-circuit: bypassing intent judge for '{_stripped}'",
                        "voice",
                    )
                    # Clear wake state so we don't double-fire
                    self._wake_timestamp = None
                    # Dispatch through the normal path which has the parallel
                    # action+voice plumbing already wired up.
                    self._dispatch_query(_stripped)
                    return
            except Exception as _e:
                debug_log(f"fast-path short-circuit failed (non-fatal): {_e}", "voice")

        if not has_engagement_signal:
            debug_log(
                f"skipping intent judge — no wake word, no hot window, no TTS "
                f"(ambient: \"{text_lower[:40]}{'...' if len(text_lower) > 40 else ''}\")",
                "voice",
            )

        if (
            not skip_intent_judge_during_tts
            and has_engagement_signal
            and self._intent_judge is not None
            and self._intent_judge.available
        ):
            # Get recent transcript segments for context (full buffer)
            context_segments = self._transcript_buffer.get_last_seconds(self._buffer_duration)

            # Get TTS context for echo detection
            last_tts_text = self.echo_detector._last_tts_text or ""
            last_tts_finish_time = self.echo_detector._last_tts_finish_time or 0.0

            # Tier 1 / Tier 2 cascade — tries the cheap heuristic classifier
            # first, then the fused intent engine. Falls through to the
            # legacy intent_judge LLM call when both tiers are
            # disabled/unavailable or both error out. Source tag is logged
            # for visibility into which tier actually produced the verdict.
            intent_judgment = None
            cascade_source = "fallback"
            try:
                intent_judgment, cascade_source = self._run_intent_cascade(
                    text_lower=text_lower,
                    could_be_hot_window=could_be_hot_window,
                    last_tts_text=last_tts_text,
                )
            except Exception as _casc_e:  # noqa: BLE001 — full safety net
                debug_log(
                    f"intent cascade raised (non-fatal, falling back to judge): {_casc_e}",
                    "voice",
                )
                intent_judgment = None
                cascade_source = "fallback"

            if intent_judgment is None:
                # Legacy intent_judge — runs when the cascade was unavailable
                # or returned no result. Preserves all original behavior.
                intent_judgment = self._intent_judge.judge(
                    segments=context_segments,
                    wake_timestamp=self._wake_timestamp,
                    last_tts_text=last_tts_text,
                    last_tts_finish_time=last_tts_finish_time,
                    in_hot_window=could_be_hot_window,
                    current_text=text_lower,
                )
                if intent_judgment is not None:
                    debug_log(
                        f"intent cascade ({cascade_source}) → judge produced verdict "
                        f"(directed={intent_judgment.directed})",
                        "voice",
                    )

            if intent_judgment is not None:
                # Log intent judge decision for user visibility
                mode_str = "hot window" if could_be_hot_window else "wake word"
                if intent_judgment.directed:
                    print(f"  🧠 Intent ({mode_str}): directed → \"{intent_judgment.query or text_lower}\"", flush=True)
                else:
                    print(f"  🧠 Intent ({mode_str}): not directed ({intent_judgment.reasoning})", flush=True)
            else:
                reason = self._intent_judge.last_failure_reason or "no segments or unavailable"
                print(f"  🧠 Intent judge: unavailable ({reason})", flush=True)
                debug_log(f"intent judge returned None — falling back ({reason})", "voice")
                # Hot window fallback: if the early echo check already cleared
                # this text, accept it even without the judge's verdict.
                if could_be_hot_window:
                    last_tts_text_fb = self.echo_detector._last_tts_text or ""
                    is_pure_echo = False
                    if last_tts_text_fb:
                        echo_score = fuzz.partial_ratio(
                            text_lower, last_tts_text_fb.lower()
                        )
                        tts_words = len(last_tts_text_fb.split())
                        text_words = len(text_lower.split())
                        is_pure_echo = (
                            echo_score >= 70
                            and text_words <= max(tts_words * 1.3, tts_words + 3)
                        )
                    if not is_pure_echo:
                        print(f"  🧠 Intent fallback: accepting hot window speech", flush=True)
                        debug_log(f"✅ Hot window fallback (judge unavailable): \"{text_lower}\"", "voice")
                        self.state_manager.cancel_hot_window_activation()
                        self._transcript_buffer.mark_segment_processed(text_lower)
                        self._clear_audio_buffers()
                        self._start_collection(text_lower)
                        self._start_thinking_tune()
                        try:
                            print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                        except Exception:
                            pass
                        return

            if intent_judgment is not None:
                # If judge says stop command, interrupt TTS
                if intent_judgment.stop and self.tts and self.tts.is_speaking():
                    debug_log(f"🛑 Intent judge detected stop command", "voice")
                    self.tts.interrupt()
                    return

                # If directed with query, process it
                if intent_judgment.directed and intent_judgment.query:
                    # In wake word mode, verify the wake word is actually present
                    # The LLM sometimes hallucinates wake words that don't exist
                    if not could_be_hot_window:
                        wake_word = getattr(self.cfg, "wake_word", "jarvis")
                        aliases = list(set(getattr(self.cfg, "wake_aliases", [])) | {wake_word})
                        has_wake_word = self._wake_timestamp is not None or is_wake_word_detected(
                            text_lower, wake_word, aliases
                        )
                        if not has_wake_word:
                            print(f"  🧠 Intent override: no wake word found, ignoring", flush=True)
                            debug_log(
                                f"⚠️ Intent judge said directed but no wake word found in '{text_lower[:50]}...' "
                                f"(reasoning: {intent_judgment.reasoning})",
                                "voice"
                            )
                            # Don't accept - fall through to wake word check
                        else:
                            debug_log(f"✅ Intent judge accepted ({intent_judgment.confidence}): \"{intent_judgment.query}\"", "voice")
                            self.state_manager.cancel_hot_window_activation()
                            self._transcript_buffer.mark_segment_processed(text_lower)
                            self._clear_audio_buffers()
                            self._start_collection(intent_judgment.query)
                            self._start_thinking_tune()
                            try:
                                print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                            except Exception:
                                pass
                            return
                    else:
                        # Hot window mode - no wake word needed, but check for echo.
                        # The mic can pick up Jarvis's own TTS output and Whisper
                        # transcribes it as user speech. Check fuzzy similarity.
                        # Only reject PURE echo — if the heard text is significantly
                        # longer than TTS, it contains user speech mixed with echo
                        # and the intent judge's extraction should be used instead.
                        if last_tts_text:
                            echo_score = fuzz.partial_ratio(
                                text_lower, last_tts_text.lower()
                            )
                            tts_words = len(last_tts_text.split())
                            text_words = len(text_lower.split())
                            is_pure_echo = (
                                echo_score >= 70
                                and text_words <= max(tts_words * 1.3, tts_words + 3)
                            )
                            if is_pure_echo:
                                # Also check judge's extracted query — if it matches
                                # TTS too, it's genuinely pure echo. If the query is
                                # different, the judge extracted real user speech.
                                query_echo_score = fuzz.partial_ratio(
                                    intent_judgment.query.lower(),
                                    last_tts_text.lower()
                                )
                                if query_echo_score >= 70:
                                    debug_log(f"🔇 Echo in hot window (directed, score={echo_score}): \"{text_lower}\"", "voice")
                                    print(f"  🔇 Heard (echo): \"{text_lower[:50]}{'...' if len(text_lower) > 50 else ''}\"", flush=True)
                                    self._stop_thinking_tune()
                                    return
                                else:
                                    debug_log(
                                        f"echo in text (score={echo_score}) but judge extracted "
                                        f"non-echo query: \"{intent_judgment.query}\"", "voice"
                                    )

                        # The intent judge is explicitly designed to prune echo
                        # and extract the actual user query — always prefer its
                        # output when present. Falling back to raw heard text
                        # leaks partially-salvaged echo fragments into tool
                        # calls (e.g. "…amount now? okay, what is his best
                        # song?" reaching webSearch verbatim). If the judge
                        # returns an empty query (rare), fall back to raw text.
                        judge_query = (intent_judgment.query or "").strip()
                        hot_query = judge_query or text_lower
                        if judge_query and judge_query.lower() != text_lower:
                            debug_log(
                                f"using judge query over heard text: "
                                f"\"{judge_query}\" (heard: \"{text_lower[:80]}\")",
                                "voice",
                            )
                        debug_log(f"✅ Intent judge accepted ({intent_judgment.confidence}): \"{hot_query}\"", "voice")
                        self.state_manager.cancel_hot_window_activation()
                        self._transcript_buffer.mark_segment_processed(text_lower)
                        self._clear_audio_buffers()

                        self._start_collection(hot_query)

                        # Start thinking tune and show processing message
                        self._start_thinking_tune()
                        try:
                            print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                        except Exception:
                            pass
                        return

                # If directed with high confidence but no extracted query, use actual text
                # Per spec: "Hot window input should reflect what the user actually said"
                # This handles cases where intent judge correctly identifies directed speech
                # but fails to extract/synthesize a query (e.g., conversational follow-ups)
                if intent_judgment.directed and intent_judgment.confidence == "high":
                    # In wake word mode, verify the wake word is actually present
                    if not could_be_hot_window:
                        wake_word = getattr(self.cfg, "wake_word", "jarvis")
                        aliases = list(set(getattr(self.cfg, "wake_aliases", [])) | {wake_word})
                        has_wake_word = self._wake_timestamp is not None or is_wake_word_detected(
                            text_lower, wake_word, aliases
                        )
                        if not has_wake_word:
                            print(f"  🧠 Intent override: no wake word found, ignoring", flush=True)
                            debug_log(
                                f"⚠️ Intent judge said directed (no query) but no wake word in '{text_lower[:50]}...'",
                                "voice"
                            )
                            # Fall through to wake word check
                        else:
                            debug_log(f"✅ Intent judge accepted (directed, high confidence, using actual text): \"{text_lower}\"", "voice")
                            self.state_manager.cancel_hot_window_activation()
                            self._transcript_buffer.mark_segment_processed(text_lower)
                            self._clear_audio_buffers()
                            self._start_collection(text_lower)
                            self._start_thinking_tune()
                            try:
                                print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                            except Exception:
                                pass
                            return
                    else:
                        # Hot window — echo check before accepting
                        # Only reject pure echo (similar word count to TTS)
                        if last_tts_text:
                            echo_score = fuzz.partial_ratio(
                                text_lower, last_tts_text.lower()
                            )
                            tts_words = len(last_tts_text.split())
                            text_words = len(text_lower.split())
                            is_pure_echo = (
                                echo_score >= 70
                                and text_words <= max(tts_words * 1.3, tts_words + 3)
                            )
                            if is_pure_echo:
                                debug_log(f"🔇 Echo in hot window (directed/no-query, score={echo_score}): \"{text_lower}\"", "voice")
                                print(f"  🔇 Heard (echo): \"{text_lower[:50]}{'...' if len(text_lower) > 50 else ''}\"", flush=True)
                                self._stop_thinking_tune()
                                return

                        debug_log(f"✅ Intent judge accepted (directed, high confidence, using actual text): \"{text_lower}\"", "voice")
                        self.state_manager.cancel_hot_window_activation()
                        self._transcript_buffer.mark_segment_processed(text_lower)
                        self._clear_audio_buffers()
                        self._start_collection(text_lower)
                        self._start_thinking_tune()
                        try:
                            print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                        except Exception:
                            pass
                        return

                # If not directed with high confidence, check reasoning before rejecting
                if not intent_judgment.directed and intent_judgment.confidence == "high":
                    # Surgical fix: If intent judge claims "echo" but echo system already cleared
                    # this utterance (we reached here, meaning Priority 2 didn't reject), don't
                    # trust the LLM's echo reasoning - fall through to wake word detection instead.
                    # The echo system does actual text similarity matching; the LLM sometimes
                    # hallucinates echo matches that don't exist.
                    reasoning_lower = (intent_judgment.reasoning or "").lower()
                    if "echo" in reasoning_lower:
                        debug_log(
                            f"⚠️ Intent judge claimed echo but echo system cleared - "
                            f"checking if near hot window: \"{text_lower}\"",
                            "voice"
                        )
                        # Check if utterance started shortly after hot window expired
                        # This catches cases where user started speaking just as hot window expired
                        # Use a 2-second grace period after the 3-second hot window
                        hot_window_grace = 2.0
                        last_tts_finish = self.echo_detector._last_tts_finish_time or 0.0
                        hot_window_end = last_tts_finish + self.state_manager.hot_window_seconds
                        time_after_hot_window = utterance_start_time - hot_window_end if utterance_start_time > 0 and hot_window_end > 0 else float('inf')

                        if 0 <= time_after_hot_window < hot_window_grace:
                            # Utterance started within grace period after hot window
                            debug_log(
                                f"✅ Accepting as directed: started {time_after_hot_window:.2f}s after hot window expired",
                                "voice"
                            )
                            self.state_manager.cancel_hot_window_activation()

                            # Mark the current segment as processed to prevent re-extraction
                            self._transcript_buffer.mark_segment_processed(text_lower)

                            self._clear_audio_buffers()
                            self._start_collection(text_lower)
                            self._start_thinking_tune()
                            try:
                                print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                            except Exception:
                                pass
                            return

                        # Check could_be_hot_window (handles overlap: utterance
                        # started during TTS but extended into hot window span).
                        # The grace period above only checks utterance_start_time
                        # which is negative for overlapping utterances.
                        if could_be_hot_window:
                            # Verify it's not pure echo before overriding
                            echo_score = 0
                            is_pure_echo = False
                            if last_tts_text:
                                echo_score = fuzz.partial_ratio(
                                    text_lower, last_tts_text.lower()
                                )
                                tts_words = len(last_tts_text.split())
                                text_words = len(text_lower.split())
                                is_pure_echo = (
                                    echo_score >= 70
                                    and text_words <= max(tts_words * 1.3, tts_words + 3)
                                )
                            if is_pure_echo:
                                debug_log(f"🔇 Echo in hot window (echo reasoning confirmed, score={echo_score}): \"{text_lower}\"", "voice")
                                self._stop_thinking_tune()
                                return
                            # Mixed echo+speech — override the echo reasoning
                            print(f"  🧠 Intent override: accepting hot window speech (mixed echo+speech)", flush=True)
                            debug_log(
                                f"⚡ Overriding echo reasoning in hot window "
                                f"(echo_score={echo_score}, text longer than TTS): "
                                f"\"{text_lower}\"",
                                "voice"
                            )
                            self.state_manager.cancel_hot_window_activation()
                            self._transcript_buffer.mark_segment_processed(text_lower)
                            self._clear_audio_buffers()
                            self._start_collection(text_lower)
                            self._start_thinking_tune()
                            try:
                                print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                            except Exception:
                                pass
                            return

                        # Otherwise fall through to wake word detection
                        debug_log(f"⏭️ Not near hot window ({time_after_hot_window:.2f}s after), falling through to wake word check", "voice")
                        # Continue to wake word detection below
                    else:
                        # Check if text is pure echo of TTS output
                        echo_score = 0
                        is_pure_echo = False
                        if last_tts_text:
                            echo_score = fuzz.partial_ratio(
                                text_lower, last_tts_text.lower()
                            )
                            tts_words = len(last_tts_text.split())
                            text_words = len(text_lower.split())
                            is_pure_echo = (
                                echo_score >= 70
                                and text_words <= max(tts_words * 1.3, tts_words + 3)
                            )

                        if could_be_hot_window and is_pure_echo:
                            # Confirmed pure echo — early check should have caught
                            # this, but handle as safety net.
                            debug_log(f"🔇 Echo in hot window (score={echo_score}): \"{text_lower}\"", "voice")
                            self._stop_thinking_tune()
                            return

                        if could_be_hot_window:
                            # Hot window + non-echo speech → user is talking to us.
                            # Override the intent judge rejection — small models
                            # sometimes reject valid follow-ups like "don't you
                            # already know that?" as not directed.
                            print(f"  🧠 Intent override: accepting hot window speech", flush=True)
                            debug_log(
                                f"⚡ Overriding intent judge in hot window "
                                f"(echo_score={echo_score}, reasoning={intent_judgment.reasoning}): "
                                f"\"{text_lower}\"",
                                "voice"
                            )
                            self.state_manager.cancel_hot_window_activation()
                            self._transcript_buffer.mark_segment_processed(text_lower)
                            self._clear_audio_buffers()
                            self._start_collection(text_lower)
                            self._start_thinking_tune()
                            try:
                                print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
                            except Exception:
                                pass
                            return

                        # Outside hot window — trust rejection
                        debug_log(f"🚫 Intent judge rejected (not directed, high confidence): \"{text_lower}\"", "voice")
                        self._stop_thinking_tune()
                        self._set_face_state_idle()  # unstick a Wispr-wake LISTENING orb
                        return
                else:
                    # For inconclusive results, fall through to wake word detection
                    debug_log(f"⏭️ Intent judge inconclusive ({intent_judgment.confidence}), checking wake word", "voice")

        # Priority 4: Wake word detection (fallback when intent judge unavailable/inconclusive)
        wake_word = getattr(self.cfg, "wake_word", "jarvis")
        aliases = set(getattr(self.cfg, "wake_aliases", [])) | {wake_word}
        fuzzy_ratio = float(getattr(self.cfg, "wake_fuzzy_ratio", 0.78))

        wake_detected = is_wake_word_detected(text_lower, wake_word, list(aliases), fuzzy_ratio)
        debug_log(f"wake word check: '{wake_word}' in '{text_lower}' → {wake_detected}", "voice")

        if wake_detected:
            # Cancel any pending hot window activation when new query starts
            self.state_manager.cancel_hot_window_activation()

            # Mark the current segment as processed to prevent re-extraction
            self._transcript_buffer.mark_segment_processed(text_lower)

            # Clear audio buffers to prevent concatenation issues
            self._clear_audio_buffers()

            query_fragment = extract_query_after_wake(text_lower, wake_word, list(aliases))
            self._start_collection(query_fragment)

            # Start thinking tune and show processing message
            self._start_thinking_tune()
            try:
                print(f"\n✨ Working on it: {self.state_manager.get_pending_query()}")
            except Exception:
                pass
            return

        # Priority 5: Collection mode handling
        if self.state_manager.is_collecting():
            self._add_to_collection(text_lower)
            return

        # Priority 6: Non-wake input (ignore)
        # Provide clear debug info about why input was ignored
        intent_info = ""
        if intent_judgment is not None:
            intent_info = f", intent={intent_judgment.directed}/{intent_judgment.confidence}"

        # Stop any early-started beep since we're not processing this input
        self._stop_thinking_tune()
        self._set_face_state_idle()  # unstick a Wispr-wake LISTENING orb (skips while speaking)

        if received_during_tts:
            # User spoke during TTS but it wasn't a stop command - this is likely a response
            # to a TTS question that arrived before hot window activated
            debug_log(f"input ignored (during TTS, not a stop command{intent_info}): {text_lower}", "voice")
            try:
                print(f"  ⏳ Heard during TTS (waiting for hot window): \"{text_lower[:50]}{'...' if len(text_lower) > 50 else ''}\"", flush=True)
            except Exception:
                pass
        else:
            debug_log(f"input ignored (no wake word{intent_info}): {text_lower}", "voice")

    def _dispatch_query(self, query: str) -> None:
        """
        Dispatch a complete query to the reply engine.

        Args:
            query: Complete user query to process
        """
        debug_log(f"dispatching query: '{query}'", "voice")

        # Safety net: a wake-only "query" must never reach the reply engine,
        # whichever tier extracted it (judge, fused, wake fallback). The
        # early short-circuit in the cascade catches most; this catches the
        # rest (e.g. the judge echoing "hey jarvis." as the query).
        _wake_word = getattr(self.cfg, "wake_word", "jarvis")
        _aliases = list(set(getattr(self.cfg, "wake_aliases", [])) | {_wake_word})
        if is_wake_only_utterance((query or "").strip().lower(), _wake_word, _aliases):
            self._acknowledge_wake_only((query or "").strip().lower())
            return

        # Manual trigger mode ends once the query is dispatched
        with self._control_flags_lock:
            self._manual_trigger_active = False
            self._manual_finalize_requested = False

        # Clear audio buffers to prevent stale audio from next query
        self._clear_audio_buffers()

        # Set face state to THINKING
        try:
            from desktop_app.face_widget import get_jarvis_state, JarvisState
            state_manager = get_jarvis_state()
            state_manager.set_state(JarvisState.THINKING)
            log_state_transition("THINKING", "dispatch_query")
        except Exception as e:
            debug_log(f"failed to set face state to THINKING: {e}", "voice")

        # EASTER EGG: "daddy's home" / "μπαμπάς γύρισε" — start background
        # music + cinematic greeting in parallel. Sync is guaranteed: music
        # starts immediately, speech starts AT LEAST 3 seconds later, and
        # only after the LLM has produced a greeting (or a fallback fires).
        if self._try_easter_egg_daddys_home(query):
            return

        # Processing has begun: start the thinking tune HERE (not at wake/
        # listening time). It is a PROCESSING indicator. The fast path below
        # stops it immediately for quick replies; the engine path keeps it
        # until TTS playback starts (_on_playback_started -> _stop_thinking_tune).
        self._start_thinking_tune()

        # FAST-PATH: try direct MCP routing for common phrases.
        # Skips intent judge + chat LLM entirely (~5x latency reduction).
        # See src/jarvis/listening/fast_paths.py for the pattern registry.
        fast_reply = self._try_fast_path(query)
        if fast_reply is not None:
            self._stop_thinking_tune()
            if fast_reply and self.tts and self.tts.enabled:
                def _fp_tts_complete():
                    import time as _time
                    debug_log(f"fast-path TTS completion at {_time.time():.3f}", "voice")
                    self.activate_hot_window()

                def _fp_duration_known(duration: float):
                    debug_log(f"fast-path TTS exact duration: {duration:.2f}s", "voice")
                    if self.echo_detector:
                        self.echo_detector._tts_exact_duration = duration
                    self._last_tts_synthesis_time = time.time()

                def _fp_tts_complete():
                    self._log_tts_summary(fast_reply)
                    self.activate_hot_window()

                def _fp_playback_started() -> None:
                    # Silence the thinking pad the instant audio engages (it is
                    # also stopped before synthesis); guards against the pad
                    # lingering under / after the reply.
                    self._stop_thinking_tune()
                    # Mirror the main-path: set Wispr speaking flag so stop
                    # keywords interrupt instead of routing through cascade.
                    self._set_bridge_speaking(True)

                self.track_tts_start(fast_reply)
                debug_log(f"starting TTS for fast-path reply ({len(fast_reply)} chars)", "voice")
                self.tts.speak(
                    fast_reply,
                    completion_callback=_fp_tts_complete,
                    duration_callback=_fp_duration_known,
                    playback_started_callback=_fp_playback_started,
                    playback_ended_callback=self._on_playback_ended,
                )
            return

        # Import reply engine
        from ..reply.engine import run_reply_engine

        # Process the query (keep thinking tune playing during processing).
        # Forward the pre-computed fused tools/plan stashed by the Tier-2
        # intent cascade so the engine can skip its internal router +
        # planner LLM calls (~5-7s each). These may be None/empty, which is
        # fine — the engine falls back to routing internally. Clear them
        # afterwards so they never leak into the next query's dispatch.
        fused_tools = self._last_fused_tools
        fused_plan = self._last_fused_plan
        self._last_fused_tools = None
        self._last_fused_plan = None
        # Clear any stale STOP/barge-in signal from a previous turn BEFORE
        # starting this reply, then hand the engine the same event so a STOP
        # arriving DURING this reply aborts it at a turn/tool boundary. Without
        # the clear, a STOP left set from the prior turn would cancel this
        # fresh reply on its very first boundary check.
        self._llm_cancel_event.clear()
        try:
            reply = run_reply_engine(
                self.db, self.cfg, None, query, self.dialogue_memory,
                language=self._last_detected_language,
                fused_tools=fused_tools,
                fused_plan=fused_plan,
                cancel_event=self._llm_cancel_event,
            )
        except Exception as e:
            # Log the error visibly - this should never happen silently
            print(f"\n  ❌ Reply engine error: {e}", flush=True)
            debug_log(f"reply engine exception: {e}", "voice")
            self._stop_thinking_tune()
            # Provide user feedback via TTS
            if self.tts and self.tts.enabled:
                self.tts.speak("Sorry, I encountered an error processing your request.")
            return

        # Handle TTS with proper callbacks
        if reply and self.tts and self.tts.enabled:
            # Stop thinking tune when TTS starts
            self._stop_thinking_tune()

            # TTS completion callback for hot window
            def _on_tts_complete():
                self._log_tts_summary(reply)
                self.activate_hot_window()

            # Duration callback to update echo detector with exact timing (Piper only)
            def _on_duration_known(duration: float):
                debug_log(f"TTS exact duration: {duration:.2f}s", "voice")
                if self.echo_detector:
                    self.echo_detector._tts_exact_duration = duration
                self._last_tts_synthesis_time = time.time()

            # Track TTS start for echo detection with actual text. The
            # `track_tts_start` here is the EARLY marker (synthesis about to
            # begin); the echo detector's _tts_start_time will be REFRESHED
            # to the real play-start moment via `_on_playback_started`
            # below, so the echo-offset math lines up with what the user
            # actually hears.
            self.track_tts_start(reply)
            debug_log(f"starting TTS for reply ({len(reply)} chars)", "voice")

            def _on_playback_started() -> None:
                # Silence the thinking pad the instant audio engages (also
                # stopped before synthesis); guards against it lingering under /
                # after the reply.
                self._stop_thinking_tune()
                # Reset the echo detector's tts_start_time to NOW — i.e. the
                # moment pygame engaged audio. The synthesis-to-play gap is
                # 5-7s and was throwing the echo segment-offset off by the
                # same amount, causing "is_echo? No — text doesn't match
                # segment" false negatives.
                if self.echo_detector:
                    self.echo_detector._tts_start_time = time.time()
                    debug_log("echo detector tts_start_time refreshed at play-engage", "voice")
                # Phase F: tell the Wispr bridge JARVIS is now speaking.
                # While the flag is True, a "stop"/"σταμάτα" utterance is
                # routed through on_stop (interrupting TTS) instead of the
                # normal cascade.
                self._set_bridge_speaking(True)

            self.tts.speak(reply, completion_callback=_on_tts_complete,
                          duration_callback=_on_duration_known,
                          playback_started_callback=_on_playback_started,
                          playback_ended_callback=self._on_playback_ended)
        else:
            debug_log(f"no TTS output: reply={bool(reply)}, tts={bool(self.tts)}, enabled={getattr(self.tts, 'enabled', False) if self.tts else False}", "voice")
            # Stop thinking tune if no TTS response
            self._stop_thinking_tune()

    def _try_easter_egg_daddys_home(self, query: str) -> bool:
        """Iron Man "JARVIS, daddy's home" trigger.

        Plays The Clash music underneath a cinematic greeting. Synchronisation
        guarantee: the speech starts no earlier than 3 seconds after the
        music does AND no earlier than the LLM has finished generating the
        greeting. If the LLM takes longer than 3 s, we still don't speak
        until the text is ready (no half-baked output). If it's faster, we
        wait the remaining time so the music has a chance to set the mood.

        Returns True if the easter egg fired (caller should not run normal
        dispatch); False to fall through.
        """
        import re as _re
        # Trigger phrases (English + Greek). Matches both "daddy" and "dad",
        # with or without apostrophe-s, "is", "has come", etc.
        triggers = [
            r"\b(?:daddy|dad|papa)(?:'?s| is| has)?\s+(?:home|back)\b",
            r"\b(?:papa|daddy|dad)\s+home\b",
            r"\bμπαμπ[άα]ς\s+(?:γύρισε|γυρισε|είναι\s+σπίτι|ειναι\s+σπιτι|ηρθε|ήρθε)\b",
            r"\b(?:ο\s+)?μπαμπ[άα]ς\s+(?:ήρθε|ηρθε|γύρισε|γυρισε)\b",
        ]
        if not any(_re.search(p, query, _re.IGNORECASE | _re.UNICODE) for p in triggers):
            return False

        print("  🎬 Easter egg: daddy's home — cueing music + cinematic greeting", flush=True)
        debug_log("easter egg: daddy's home fired", "voice")

        # Resolve the music asset path (relative to repo root)
        from pathlib import Path as _Path
        asset_path = _Path(__file__).resolve().parents[3] / "assets" / "daddys_home.wav"
        if not asset_path.exists():
            print(f"  ⚠ Easter egg asset missing: {asset_path}", flush=True)
            return False

        # Kick off music IMMEDIATELY (sounddevice, parallel to TTS later).
        # Music starts at a prominent level so the intro feels cinematic,
        # then ducks when TTS begins so Jarvis's voice cuts through cleanly.
        self._stop_thinking_tune()  # silence the regular thinking pad
        try:
            from ..output.audio_overlay import get_overlay
            overlay = get_overlay()
            overlay.play(str(asset_path), volume=0.55, fade_in_sec=0.4)
        except Exception as e:
            debug_log(f"easter egg: overlay start failed: {e}", "voice")
            return False

        # Start LLM greeting generation in a background thread; we'll join
        # before speaking, with a hard cap so a stuck LLM can't lock things up.
        import threading as _th
        import time as _time
        greeting_text: dict = {"value": None}
        greeting_done = _th.Event()

        def _gen_greeting() -> None:
            try:
                greeting_text["value"] = self._compose_daddys_home_greeting()
            except Exception as _e:
                debug_log(f"easter egg: greeting gen error: {_e}", "voice")
                greeting_text["value"] = self._fallback_daddys_home_greeting()
            finally:
                greeting_done.set()

        _th.Thread(target=_gen_greeting, daemon=True, name="DaddysHomeGreeting").start()

        # Sync: wait until BOTH conditions hold
        #   (a) at least 3 seconds elapsed since music start
        #   (b) greeting text is ready (or 10s hard deadline)
        music_start = _time.time()
        MIN_DELAY = 3.0
        HARD_DEADLINE = 10.0
        greeting_done.wait(timeout=HARD_DEADLINE)
        elapsed = _time.time() - music_start
        if elapsed < MIN_DELAY:
            _time.sleep(MIN_DELAY - elapsed)

        text = greeting_text["value"] or self._fallback_daddys_home_greeting()
        debug_log(f"easter egg: speaking ({len(text)} chars) over music", "voice")

        # Speak the greeting (music keeps playing underneath via sounddevice).
        if self.tts and self.tts.enabled:
            # Duck music so the voice sits on top
            overlay.duck(ratio=0.45, fade_sec=0.3)

            def _on_done() -> None:
                # Bring music back up, then fade out gracefully after a tail
                try:
                    overlay.unduck(fade_sec=1.5)
                except Exception:
                    pass
                try:
                    _th.Timer(4.0, lambda: overlay.stop(fade_out_sec=2.5)).start()
                except Exception:
                    pass
                self.activate_hot_window()

            self.track_tts_start(text)
            self.tts.speak(
                text,
                completion_callback=_on_done,
                playback_started_callback=lambda: self._set_bridge_speaking(True),
                playback_ended_callback=self._on_playback_ended,
                volume=1.15,
            )
        else:
            # No TTS — let music play out, then fade out gracefully
            _th.Timer(8.0, lambda: overlay.stop(fade_out_sec=2.5)).start()
        return True

    def _compose_daddys_home_greeting(self) -> str:
        """Build a cinematic Iron Man-style intro greeting via direct LLM call.

        Pulls today's weather (OpenWeather) and today's calendar events
        (Google Calendar MCP) and feeds them as context. Asks qwen3.5:9b
        for a short, dry-witty JARVIS reply. If the calendar comes back
        empty, the prompt tells the model to riff on having a free day —
        no awkward "there are zero events" lines.
        """
        import datetime as _dt
        import requests as _requests

        now = _dt.datetime.now()
        day_str = now.strftime("%A, %B %d at %I:%M %p").lstrip("0")

        # ----- weather ----------------------------------------------------
        weather_blurb = ""
        try:
            import os as _os
            from pathlib import Path as _Path
            from dotenv import dotenv_values
            env = dotenv_values(_Path("C:/Users/aggel/Jarvis/mcps/.env"))
            ow_key = env.get("OPENWEATHER_API_KEY") or _os.environ.get("OPENWEATHER_API_KEY")
            if ow_key:
                r = _requests.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": "Ioannina,GR", "appid": ow_key, "units": "metric", "lang": "en"},
                    timeout=4,
                )
                if r.ok:
                    d = r.json()
                    weather_blurb = (
                        f"{d['main']['temp']:.0f}°C with "
                        f"{d['weather'][0]['description']}"
                    )
        except Exception:
            pass

        # ----- calendar (today's events via Calendar MCP) ------------------
        calendar_summary = ""
        calendar_empty = False
        try:
            mcps_cfg = getattr(self.cfg, "mcps", {}) or {}
            cal_cfg = mcps_cfg.get("calendar")
            if cal_cfg:
                from ..tools.external.mcp_runtime import get_runtime
                from .fast_paths import extract_mcp_text
                runtime = get_runtime()
                result = runtime.invoke(
                    server_name="calendar",
                    server_cfg=cal_cfg,
                    tool_name="list_events_today",
                    arguments={},
                    timeout=6.0,
                )
                cal_text = (extract_mcp_text(result) or "").strip()
                lower_cal = cal_text.lower()
                if (
                    not cal_text
                    or "no more events" in lower_cal
                    or "no events" in lower_cal
                    or "calendar lookup failed" in lower_cal
                ):
                    calendar_empty = True
                else:
                    # Keep it short — pass the first 350 chars as context
                    calendar_summary = cal_text[:350]
        except Exception as e:
            debug_log(f"daddy's home calendar fetch failed: {e}", "voice")
            calendar_empty = True

        # ----- Build the greeting -----------------------------------------
        # The OPENER is always a classic JARVIS line (verbatim from the
        # Iron Man films). The BODY is LLM-generated to riff on the date,
        # weather, and calendar — picked up fresh each invocation.
        import random as _random
        openers = (
            "Welcome back, Sir.",
            "Welcome home, Sir.",
            "At your service, Sir.",
            "It is a pleasure to see you again, Sir.",
            "Good to have you back, Sir.",
        )
        opener = _random.choice(openers)

        if calendar_empty:
            calendar_block = (
                "Calendar: The user has NO events scheduled today. Allude to "
                "this lightheartedly — phrases like 'your schedule is "
                "delightfully empty', 'plenty of free time on your hands', or "
                "'the day is yours to squander as you please'. Do NOT say 'no "
                "events' literally."
            )
        else:
            calendar_block = (
                "Today's calendar (mention naturally, paraphrase — do NOT read "
                "verbatim):\n" + calendar_summary
            )

        prompt = (
            "You are JARVIS, Tony Stark's AI butler from Iron Man. The user "
            "(addressed as 'Sir') just walked in and triggered the 'daddy's "
            "home' line. Write the BODY of a greeting (2 sentences, max 45 "
            "words). Dry-witty, deadpan, British-butler register. Mention "
            "the time/day naturally, the weather only if relevant, and the "
            "calendar info per instructions below. DO NOT start with a "
            "greeting word — the opener is already handled. DO NOT use stage "
            "directions, quotes, or 'Sir' again at the start. Begin with the "
            "date or a wry observation.\n\n"
            f"Current local time: {day_str}.\n"
            f"Weather in Ioannina: {weather_blurb or 'unknown'}.\n"
            f"{calendar_block}\n\n"
            "Body (continues after 'Welcome back, Sir.'):"
        )

        try:
            ollama_url = getattr(self.cfg, "ollama_base_url", "http://127.0.0.1:11434")
            model = getattr(self.cfg, "ollama_chat_model", "qwen3.5:9b")
            r = _requests.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 110},
                },
                timeout=12,
            )
            r.raise_for_status()
            body = (r.json().get("response") or "").strip()
            # Clean any wrapping quotes/asterisks
            body = body.strip("\"'*` \n")
            # Strip leading "Sir," / "Welcome back" if the model ignored instructions
            body = _re.sub(r"^(welcome\s+(back|home)[,.]?\s*sir[,.]?\s*|sir[,.]?\s+)", "", body, flags=_re.IGNORECASE)
            if body:
                return f"{opener} {body}"
        except Exception as e:
            debug_log(f"daddy's home LLM call failed: {e}", "voice")
        return self._fallback_daddys_home_greeting(opener_override=opener)

    def _fallback_daddys_home_greeting(self, opener_override: Optional[str] = None) -> str:
        """Deterministic fallback if LLM is unreachable. Always works.

        Opener is always a verbatim JARVIS line from the Iron Man films.
        Body mentions the current day/time and a witty empty-schedule line.
        """
        import datetime as _dt
        import random as _random
        now = _dt.datetime.now()
        time_str = now.strftime("%I:%M %p").lstrip("0")
        day = now.strftime("%A, %B %d").lstrip("0")
        openers = (
            "Welcome back, Sir.",
            "Welcome home, Sir.",
            "At your service, Sir.",
            "It is a pleasure to see you again, Sir.",
            "Good to have you back, Sir.",
        )
        opener = opener_override or _random.choice(openers)
        bodies = (
            f"It is {time_str} on {day}, and your schedule is delightfully empty. Do try not to break anything important.",
            f"The hour is {time_str}, {day}. Nothing on the agenda today — the world, briefly, is yours.",
            f"Currently {time_str} on {day}. You have plenty of free time on your hands, which is either a blessing or a warning.",
            f"{day}, {time_str}. The lab missed you, Sir, though the calendar remains, as ever, your problem to fill.",
        )
        return f"{opener} {_random.choice(bodies)}"

    def _try_fast_path(self, query: str) -> Optional[str]:
        """Try fast-path matching: route common phrases directly to MCPs.

        Two modes:

        1. ACTION (response_override set) — dispatch the MCP call in a
           background thread and IMMEDIATELY return the override text
           (typically a pre-cached short ack like "Skipped."). The user
           hears the ack within ~50ms while the action happens in parallel.

        2. QUERY (no override) — call MCP synchronously, return its dynamic
           response text (e.g., "Currently playing X by Y…"). Used for
           commands that need to report data.

        Returns the spoken response text on match, or None to fall through
        to the full reply engine.
        """
        try:
            from .fast_paths import match as _fp_match, extract_mcp_text
        except Exception as e:
            debug_log(f"fast-path import failed: {e}", "voice")
            return None

        fp = _fp_match(query)
        if fp is None:
            return None

        # Local pseudo-server handled in-process — no MCP roundtrip, no LLM.
        # Used for trivial dynamic queries (time / date) and "stop"/"cancel"
        # acknowledgments where the full pipeline is pure overhead.
        if fp.mcp_server == "_local":
            local_reply = self._handle_local_fast_path(fp)
            if local_reply is not None:
                print(
                    f"  ⚡ Fast-path [LOCAL]: {fp.tool_name} → \"{local_reply[:60]}\"",
                    flush=True,
                )
                return local_reply
            # Local handler said it can't serve this — fall through.

        mcps_cfg = getattr(self.cfg, "mcps", {}) or {}
        server_cfg = mcps_cfg.get(fp.mcp_server)
        if not server_cfg:
            debug_log(
                f"fast-path: MCP server '{fp.mcp_server}' not configured — falling back",
                "voice",
            )
            return None

        mode = "ACTION" if fp.action_only else "QUERY"
        print(
            f"  ⚡ Fast-path [{mode}]: {fp.mcp_server}.{fp.tool_name}({fp.arguments})",
            flush=True,
        )
        debug_log(
            f"fast-path {mode} invoking {fp.mcp_server}.{fp.tool_name}({fp.arguments})",
            "voice",
        )

        # ACTION mode: fire-and-forget the MCP call; voice ack is immediate.
        if fp.action_only and fp.response_override:
            import threading as _threading

            def _invoke_async() -> None:
                try:
                    from ..tools.external.mcp_runtime import get_runtime
                    runtime = get_runtime()
                    result = runtime.invoke(
                        server_name=fp.mcp_server,
                        server_cfg=server_cfg,
                        tool_name=fp.tool_name,
                        arguments=fp.arguments,
                        timeout=15.0,
                    )
                    text = extract_mcp_text(result)
                    debug_log(f"fast-path async result: {text[:120]}", "voice")
                    # The instant ack (response_override, e.g. "Skipped.")
                    # optimistically assumed success. If the tool actually
                    # reported a failure, correct the record out loud so we
                    # never falsely claim success when nothing happened.
                    low = text.lower()
                    if any(k in low for k in (
                        "no spotify device", "no active device", "open spotify",
                        "nothing is", "failed", "error",
                    )):
                        try:
                            self.tts.speak(text)
                        except Exception:
                            pass
                except Exception as e:
                    # anyio TaskGroups wrap the real cause in an ExceptionGroup;
                    # unwrap it so the log shows WHAT failed (not just
                    # "unhandled errors in a TaskGroup").
                    inner = getattr(e, "exceptions", None)
                    detail = "; ".join(repr(x) for x in inner) if inner else repr(e)
                    debug_log(f"fast-path async invocation failed: {detail}", "voice")
                    print(f"  ❌ Fast-path async error: {detail}", flush=True)
                    try:
                        self.tts.speak("Sorry, that didn't go through.")
                    except Exception:
                        pass

            _threading.Thread(
                target=_invoke_async, daemon=True, name=f"FastPath-{fp.mcp_server}"
            ).start()
            return fp.response_override

        # QUERY mode: synchronous, return MCP's dynamic response.
        try:
            from ..tools.external.mcp_runtime import get_runtime
            runtime = get_runtime()
            result = runtime.invoke(
                server_name=fp.mcp_server,
                server_cfg=server_cfg,
                tool_name=fp.tool_name,
                arguments=fp.arguments,
                timeout=15.0,
            )
            text = extract_mcp_text(result)
            debug_log(f"fast-path response: {text[:120]}", "voice")
            return text
        except Exception as e:
            debug_log(f"fast-path invocation failed: {e}", "voice")
            print(f"  ❌ Fast-path error, falling back to LLM: {e}", flush=True)
            return None

    def _handle_local_fast_path(self, fp) -> Optional[str]:
        """Resolve a `_local` fast-path match in-process. No MCP, no LLM.

        Returns the spoken reply, or None to signal "fall through to LLM".
        Tools handled:
          * time_now   — current local time, formatted by language preference
          * date_today — today's date
          * noop       — for short "stop"/"cancel" acks (response_override
            handled by the caller; we just return that override if present)
        """
        try:
            from datetime import datetime
            tool = (fp.tool_name or "").lower()

            # Greek when the daemon's last detected language is Greek; English
            # otherwise. Defaults to English when the listener hasn't seen any
            # ASR yet (cold start).
            lang = (getattr(self, "_last_detected_language", "") or "en").lower()
            is_greek = lang.startswith("el")

            if tool == "time_now":
                now = datetime.now()
                if is_greek:
                    # 24h format reads more naturally in Greek voice.
                    return f"Η ώρα είναι {now.strftime('%H:%M')}."
                # English: 12h with am/pm. strftime('%-I:%M %p') is POSIX-only,
                # so build it manually for Windows compatibility.
                hour_24 = now.hour
                hour_12 = hour_24 % 12 or 12
                suffix = "AM" if hour_24 < 12 else "PM"
                return f"It's {hour_12}:{now.strftime('%M')} {suffix}."

            if tool == "date_today":
                now = datetime.now()
                if is_greek:
                    months_el = [
                        "Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου",
                        "Μαΐου", "Ιουνίου", "Ιουλίου", "Αυγούστου",
                        "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου",
                    ]
                    weekdays_el = [
                        "Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη",
                        "Παρασκευή", "Σάββατο", "Κυριακή",
                    ]
                    return (
                        f"Σήμερα είναι {weekdays_el[now.weekday()]}, "
                        f"{now.day} {months_el[now.month - 1]} {now.year}."
                    )
                # %-d is POSIX-only, build the day-of-month manually for
                # cross-platform compatibility.
                return f"Today is {now.strftime('%A, %B ')}{now.day}, {now.year}."

            if tool == "noop":
                # response_override carries the ack; the caller returns it
                # directly when fp.action_only is True. Here we just confirm
                # we recognised the tool so the caller doesn't fall through
                # to the MCP-config check.
                return fp.response_override or "OK."

        except Exception as e:
            debug_log(f"local fast-path handler error ({fp.tool_name}): {e}", "voice")
            return None

        # Unknown _local tool — let the caller fall through.
        return None

    def _calculate_audio_energy(self, frames: list) -> float:
        """Calculate RMS energy from audio frames."""
        if not frames or np is None:
            return 0.0
        try:
            audio_data = np.concatenate(frames)
            rms = float(np.sqrt(np.mean(np.square(audio_data))))
            return rms
        except Exception:
            return 0.0

    def _clear_audio_buffers(self) -> None:
        """Clear all audio buffers and reset speech state.

        Call this on state transitions to prevent old audio from being
        incorrectly concatenated with new input.
        """
        self._utterance_frames = []
        self._pre_roll.clear()
        self.is_speech_active = False
        self._silence_frames = 0

        # Clear wake detection state
        self._wake_timestamp = None

        # Drain the audio queue
        try:
            while not self._audio_q.empty():
                self._audio_q.get_nowait()
        except Exception:
            pass

        debug_log("audio buffers cleared", "voice")

    def _is_speech_frame(self, frame) -> bool:
        """Determine if audio frame contains speech."""
        if np is None:
            return True

        # Track energy for echo detection
        rms = float(np.sqrt(np.mean(np.square(frame))))
        self._recent_audio_energy.append(rms)

        if self._vad is None:
            return rms >= float(getattr(self.cfg, "voice_min_energy", 0.0045))

        # Use VAD backend (Silero or WebRTC). When voice_debug is on, log
        # per-frame Silero probability + decision — invaluable for diagnosing
        # "VAD is rejecting my speech" issues without guessing.
        try:
            pcm16 = np.clip(frame.flatten() * 32768.0, -32768, 32767).astype(np.int16).tobytes()
            sample_rate = getattr(self, "_stream_samplerate", self._samplerate)
            is_speech = bool(self._vad.is_speech(pcm16, sample_rate))
            if getattr(self.cfg, "voice_debug", False):
                prob = getattr(self._vad, "last_probability", None)
                if prob is not None:
                    debug_log(
                        f"VAD frame: rms={rms:.4f} prob={prob:.3f} → "
                        f"{'speech' if is_speech else 'silence'}",
                        "vad",
                    )
            self._publish_audio_telemetry(frame, rms, is_speech)
            return is_speech
        except Exception:
            return False

    def _publish_audio_telemetry(self, frame, rms: float, voiced: bool) -> None:
        """Stream live telemetry to the console /ws/audio (whisper backend).

        Throttled to ~12 Hz; computes nothing when no console client is
        subscribed; never raises into the audio path.
        """
        try:
            now = time.time()
            if now - getattr(self, "_telemetry_last", 0.0) < 0.08:
                return
            from .. import api_server
            if not api_server.has_audio_subscribers():
                return
            self._telemetry_last = now
            from .audio_telemetry import band_spectrum, normalise_rms, telemetry_frame

            prob = getattr(self._vad, "last_probability", None) if self._vad is not None else None
            api_server.publish_audio_telemetry(telemetry_frame(
                # Whisper-path frames are float32 in [-1, 1].
                rms_norm=normalise_rms(rms, full_scale=1.0),
                state="listening" if self.is_speech_active else "idle",
                vad_prob=prob,
                voiced=voiced,
                spec=band_spectrum(np.asarray(frame, dtype=np.float32).flatten() * 32768.0),
            ))
        except Exception:
            pass

    # Whisper-hallucination blocklist now lives in the shared
    # ``listening/hallucinations`` module so the memory write-path can drop
    # the same residues at storage time without importing the listener.
    # Re-exposed as class attributes for backward compatibility (tests and
    # any external reader that read them off ``VoiceListener``).
    _HALLUCINATION_EXACT = HALLUCINATION_EXACT
    _HALLUCINATION_SUBSTRINGS = HALLUCINATION_SUBSTRINGS

    def _is_youtube_hallucination(self, text: str) -> bool:
        """Reject Whisper's known silence/echo hallucinations.

        Thin delegate to ``looks_like_hallucination`` in the shared
        ``listening/hallucinations`` module — kept as a method so existing
        call sites (and the unbound-method tests) stay unchanged.
        """
        return looks_like_hallucination(text)

    def _dump_utterance_wav(self, audio) -> None:
        """Save a VAD-gated audio segment to a WAV file for offline inspection.

        Output location: %LOCALAPPDATA%/Jarvis/debug_audio/utterance_<timestamp>.wav
        on Windows; falls back to ~/.cache/jarvis/debug_audio/ elsewhere.

        Only called when `voice_debug_save_audio` is True. Designed for
        diagnosing mistranscription cases — playing the WAV in any audio
        player lets us (and the user) confirm whether the input was clear
        enough for Whisper to have had a chance, or whether the audio was
        already lost / noisy by the time it reached the model.
        """
        import os
        import struct
        import wave
        from datetime import datetime
        from pathlib import Path

        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "Jarvis" / "debug_audio"
        else:
            base = Path(os.path.expanduser("~/.cache/jarvis/debug_audio"))
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = base / f"utterance_{stamp}.wav"

        # Convert float32 [-1, 1] → int16 PCM mono.
        pcm = np.clip(audio.flatten() * 32767.0, -32768, 32767).astype(np.int16).tobytes()
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(int(self._samplerate))
            wf.writeframes(pcm)
        debug_log(f"saved debug audio: {path}", "voice")

    def _pick_fallback_language(self, audio, allowed, decode_kwargs):
        """Pick the best allowed language when Whisper detected something outside the whitelist.

        Strategy (refined to fix Greek mis-detection):
          1. **Sticky lock**: if the language lock has consensus on an allowed
             language, use it.
          2. **Config priority**: if `language_priority` is set in config, try
             those languages first. The first one whose transcription has
             non-trivial confidence wins — much more reliable than
             `language_probability` which is biased toward English.
          3. **Quality-based vote**: probe each allowed language with a real
             transcribe call and score by `avg_logprob` of the actual segments
             (transcription quality), NOT `language_probability` (phonetic
             match — Whisper rates English-like phonetics high even for Greek).
          4. **Last resort**: `allowed[0]`.
        """
        locked = self._language_lock.suggest()
        if locked and locked in allowed:
            return locked

        # Config-driven priority: tries Greek first for el-primary users.
        priority = getattr(self.cfg, "language_priority", None) or []
        priority_list = [p for p in priority if p in allowed]

        candidates_to_probe = list(priority_list) + [c for c in allowed if c not in priority_list]

        best_lang = None
        best_score = float("-inf")
        scored: list[tuple[str, float, float]] = []  # (lang, avg_logprob, lang_prob)

        for candidate in candidates_to_probe:
            try:
                with self.transcribe_lock:
                    _segs, info = self.model.transcribe(
                        audio, language=candidate, **decode_kwargs,
                    )
                    seg_list = list(_segs)
                lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)
                # Real transcription quality: average avg_logprob across segments.
                # Higher (less negative) = better-quality words. Greek words
                # transcribed in Greek score much higher than Greek-as-English garbage.
                if seg_list:
                    logprobs = [
                        float(getattr(s, "avg_logprob", -10.0) or -10.0)
                        for s in seg_list
                    ]
                    avg_logprob = sum(logprobs) / len(logprobs)
                else:
                    avg_logprob = -10.0
            except Exception as e:
                debug_log(
                    f"fallback probe for language='{candidate}' failed: {e}",
                    "voice",
                )
                continue

            scored.append((candidate, avg_logprob, lang_prob))

            # Score = avg_logprob (primary) + small lang_prob bonus.
            # Priority languages get a static bonus so they win unless the
            # other candidate's transcription quality is *much* higher.
            priority_bonus = 0.5 if candidate in priority_list else 0.0
            score = avg_logprob + 0.1 * lang_prob + priority_bonus
            if score > best_score:
                best_score = score
                best_lang = candidate

        if best_lang is None:
            return allowed[0]

        scored_str = ", ".join(
            f"{l}: avg_logprob={lp:.2f} lang_prob={pp:.2f}"
            for l, lp, pp in scored
        )
        debug_log(
            f"fallback language probe: picked '{best_lang}' (best_score={best_score:.2f}; "
            f"candidates: {scored_str})",
            "voice",
        )
        return best_lang

    def _filter_noisy_segments(self, segments):
        """Filter out low-confidence Whisper segments + known hallucinations."""
        min_confidence = getattr(self.cfg, "whisper_min_confidence", 0.3)
        marginal_threshold = min_confidence / 3  # Show user-visible log for marginal confidence
        # Threshold above which a segment is considered non-speech (hallucination during silence).
        # Checked independently of avg_logprob because Whisper can be confident about a
        # hallucinated phrase even when no real speech is present.
        no_speech_threshold = getattr(self.cfg, "whisper_no_speech_threshold", 0.5)
        filtered = []

        for seg in segments:
            # Hard filter #0: known YouTube-trained hallucinations
            # (Whisper outputs these on silence/echo regardless of confidence).
            if self._is_youtube_hallucination(seg.text):
                debug_log(
                    f"segment filtered (YouTube hallucination): '{seg.text[:60]}'",
                    "voice",
                )
                continue

            # Hard filter: high no_speech_prob means no real speech regardless of logprob.
            if hasattr(seg, 'no_speech_prob') and is_whisper_hallucination(seg.no_speech_prob, no_speech_threshold):
                debug_log(
                    f"segment filtered (no_speech_prob={seg.no_speech_prob:.2f}): '{seg.text[:50]}'",
                    "voice",
                )
                continue

            confidence = None
            if hasattr(seg, 'avg_logprob'):
                confidence = min(1.0, max(0.0, (seg.avg_logprob + 1.0)))
            elif hasattr(seg, 'no_speech_prob'):
                confidence = 1.0 - seg.no_speech_prob

            if confidence is not None and confidence < min_confidence:
                if confidence >= marginal_threshold:
                    # Marginal confidence - show in log viewer (not debug)
                    print(f"🔇 Low confidence ({confidence:.2f}): \"{seg.text.strip()[:50]}...\"", flush=True)
                else:
                    # Very low confidence - debug only
                    debug_log(f"segment filtered (confidence={confidence:.2f}): '{seg.text}'", "voice")
                continue

            filtered.append(seg)

        return filtered

    def _is_repetitive_hallucination(self, text: str) -> bool:
        """
        Detect repetitive hallucinations that Whisper produces on quiet/ambiguous audio.

        Common patterns include repeated single words like "don't don't don't..."
        or repeated short phrases. Also detects character-level repetition patterns
        like "Jろ Jろ Jろ..." which may appear with or without spaces.

        Args:
            text: Transcribed text to check

        Returns:
            True if the text appears to be a hallucination
        """
        import re
        from collections import Counter

        if not text:
            return False

        text_stripped = text.strip()
        if len(text_stripped) < 6:
            return False

        # --- Character-level repetition detection ---
        # Remove all whitespace to detect patterns like "Jろ Jろ Jろ" or "JろJろJろ"
        text_no_space = re.sub(r'\s+', '', text_stripped.lower())

        # Look for repeating patterns of 1-5 characters appearing 3+ times consecutively
        # This catches "JろJろJろJろ" (pattern "Jろ" repeating)
        for pattern_len in range(1, 6):
            if len(text_no_space) < pattern_len * 3:
                continue

            # Check if text is mostly composed of a repeating pattern
            for start in range(pattern_len):
                pattern = text_no_space[start:start + pattern_len]
                if not pattern:
                    continue

                # Count how many times this pattern repeats consecutively from this start position
                remaining = text_no_space[start:]
                repeat_count = 0
                pos = 0
                while pos + pattern_len <= len(remaining) and remaining[pos:pos + pattern_len] == pattern:
                    repeat_count += 1
                    pos += pattern_len

                # If pattern repeats 4+ times and covers most of the string, it's a hallucination
                covered_chars = repeat_count * pattern_len
                coverage = covered_chars / len(text_no_space) if text_no_space else 0

                if repeat_count >= 4 and coverage >= 0.6:
                    debug_log(f"char-level repetition detected: pattern '{pattern}' repeats {repeat_count}x, coverage={coverage:.0%}", "voice")
                    return True

        # --- Word-level repetition detection (existing logic) ---
        words = text_stripped.lower().split()
        if len(words) < 4:
            return False

        # Strip punctuation from words for comparison (handles "word..." vs "word")
        clean_words = [re.sub(r'[^\w]', '', w) for w in words]
        clean_words = [w for w in clean_words if w]  # Remove empty strings

        if len(clean_words) < 4:
            return False

        word_counts = Counter(clean_words)
        most_common_word, most_common_count = word_counts.most_common(1)[0]

        # If a single word makes up more than 50% of all words and appears 4+ times
        if most_common_count >= 4 and most_common_count / len(clean_words) > 0.5:
            debug_log(f"repetitive hallucination detected: '{most_common_word}' repeated {most_common_count}x in '{text[:50]}...'", "voice")
            return True

        # Check for repeated consecutive sequences (e.g., "don don don" or "stop stop stop")
        # Look for any word repeated 3+ times consecutively
        consecutive_count = 1
        for i in range(1, len(clean_words)):
            if clean_words[i] == clean_words[i-1]:
                consecutive_count += 1
                if consecutive_count >= 3:
                    debug_log(f"consecutive repetition detected: '{clean_words[i]}' repeated {consecutive_count}+ times", "voice")
                    return True
            else:
                consecutive_count = 1

        return False

    def _check_query_timeout(self) -> None:
        """Check if there's a pending query that has timed out, and check hot window expiry."""
        if self.state_manager.check_collection_timeout():
            query = self.state_manager.clear_collection()
            if query.strip():
                self._dispatch_query(query)

        # Also check hot window expiry - this ensures the timeout is enforced
        # even when there's no audio being processed
        self.state_manager.check_hot_window_expiry(self.cfg.voice_debug)

    def _on_audio(self, indata, frames, time_info, status):
        """Audio callback from sounddevice."""
        try:
            with self._control_flags_lock:
                muted = self._muted
            if self._should_stop or self._dictation_active or muted:
                return
            self._callback_count += 1
            chunk = (indata.copy() if hasattr(indata, "copy") else indata)
            # Apply soft AGC before queueing so VAD + Whisper see a consistent
            # signal level regardless of mic output (dynamic mics like the
            # PD200X have low inherent output and would otherwise feed weak
            # signals into downstream gates). ~10µs/frame — negligible.
            if (
                np is not None
                and bool(getattr(self.cfg, "mic_agc_enabled", True))
                and chunk is not None
                and getattr(chunk, "size", 0) > 0
            ):
                try:
                    from .audio_preproc import normalize
                    chunk = normalize(
                        chunk,
                        target_rms=float(getattr(self.cfg, "mic_agc_target_rms", 0.1)),
                        max_gain=float(getattr(self.cfg, "mic_agc_max_gain", 10.0)),
                    )
                except Exception as e:
                    # AGC must never break audio capture — log and pass raw.
                    debug_log(f"AGC failed (passing raw chunk): {e}", "voice")
            try:
                self._audio_q.put_nowait(chunk)
            except Exception:
                pass
        except Exception:
            return

    def _determine_whisper_backend(self) -> str:
        """Determine which Whisper backend to use based on config and availability."""
        backend_pref = getattr(self.cfg, "whisper_backend", "auto")

        if backend_pref == "mlx":
            if MLX_WHISPER_AVAILABLE:
                return "mlx"
            debug_log("MLX Whisper requested but not available, falling back to faster-whisper", "voice")
            return "faster-whisper"

        if backend_pref == "faster-whisper":
            return "faster-whisper"

        # Auto mode: prefer MLX on Apple Silicon
        if MLX_WHISPER_AVAILABLE and _is_apple_silicon():
            return "mlx"

        return "faster-whisper"

    def _apply_whisper_load_success(
        self, model_name: str, try_device: str, try_compute: str,
        device: str, compute: str, cpu_threads: int,
        context: str = "",
    ) -> str:
        """Record state and print diagnostics after a successful Whisper model load.

        Returns the resolved device string.
        """
        ct2_model = getattr(self.model, "model", None)
        resolved_device = str(getattr(ct2_model, "device", try_device)).lower()
        debug_log(
            f"faster-whisper initialised{context}: name={model_name}, "
            f"device={resolved_device}, compute={try_compute}, "
            f"cpu_threads={cpu_threads}",
            "voice",
        )
        self._whisper_device = resolved_device

        if try_device != device and device in ("auto", "cuda"):
            print("     ⚠️  CUDA not available, using CPU (this may be slower)", flush=True)
            print("     💡 Tip: Install NVIDIA CUDA toolkit for faster speech recognition", flush=True)
        if try_compute != compute:
            print(f"     ⚠️  Using '{try_compute}' compute type ('{compute}' not supported)", flush=True)
        if resolved_device == "cpu":
            print(f"     ⚡ CPU mode: using {cpu_threads} threads with optimised decoding", flush=True)

        suffix = f" ({context})" if context else ""
        print(f"     🎤 Whisper '{model_name}' loaded on {resolved_device}{suffix}", flush=True)
        return resolved_device

    def _start_llm_warmup(self) -> list[threading.Thread]:
        """Pre-load chat and intent judge models into Ollama memory.

        Starts up to two daemon threads concurrently so warmup overlaps
        with Whisper initialisation. When both models point at the same
        Ollama model, a single warmup covers both (Ollama loads the
        weights once; ``keep_alive`` keeps them resident for every caller).

        Results land in ``self._llm_warmup_results`` keyed by role. The
        caller joins the returned threads with a shared deadline before
        announcing "Listening!" so the ready state actually means ready.
        """
        self._llm_warmup_results: dict[str, tuple[str, bool]] = {}

        chat_model = str(getattr(self.cfg, "ollama_chat_model", "") or "").strip()
        base_url = str(getattr(self.cfg, "ollama_base_url", "") or "").strip()
        chat_timeout = max(float(getattr(self.cfg, "llm_tools_timeout_sec", 8.0)), 60.0)
        judge = self._intent_judge
        judge_model = judge.config.model if judge is not None else ""
        shared_judge = bool(chat_model) and judge_model == chat_model

        # Tool router — only warmed when the LLM selection strategy is active
        # AND the router points at a model distinct from chat/judge. An empty
        # `tool_router_model` means "reuse the intent-judge model (small, fast,
        # already loaded for wake-word paths) or the chat model as a last
        # resort". Resolve the same way the reply engine does so warmup targets
        # whatever the engine will actually call. Skipping warmup for non-LLM
        # strategies avoids loading a model that won't be used this session.
        strategy = str(getattr(self.cfg, "tool_selection_strategy", "") or "").lower()
        # Use the same resolution helper the reply engine uses so warmup
        # targets the model the engine will actually call. Keeping a single
        # source of truth prevents drift between warmup and runtime.
        from ..reply.engine import resolve_tool_router_model
        router_model_effective = resolve_tool_router_model(self.cfg)
        router_model = router_model_effective if strategy == "llm" else ""
        shared_router = bool(router_model) and router_model in {chat_model, judge_model}

        threads: list[threading.Thread] = []

        if chat_model and base_url:
            def _warm_chat() -> None:
                ok = warm_up_ollama_model(base_url, chat_model, timeout=chat_timeout)
                self._llm_warmup_results["chat"] = (chat_model, ok)
                # When chat and judge share a model, one warmup covers both.
                if shared_judge:
                    self._llm_warmup_results["judge"] = (chat_model, ok)
                # Router reusing chat_model is already covered.
                if router_model and router_model == chat_model:
                    self._llm_warmup_results["router"] = (chat_model, ok)
                # Prime the fused router's BIG system prompt too: warming the
                # weights alone leaves its multi-k-token prompt eval cold, so
                # the first real query reliably blew the 10s fused timeout
                # and fell back to the (less reliable) legacy router.
                if ok and getattr(self, "_fused_intent", None) is not None:
                    try:
                        self._fused_intent.classify_route_plan(
                            "warmup ping", language="en")
                        self._llm_warmup_results["fused"] = (chat_model, True)
                    except Exception:
                        self._llm_warmup_results["fused"] = (chat_model, False)

            threads.append(threading.Thread(target=_warm_chat, daemon=True, name="warmup-chat"))

        if judge is not None and not shared_judge:
            def _warm_judge() -> None:
                ok = judge.warm_up()
                self._llm_warmup_results["judge"] = (judge_model, ok)
                if router_model and router_model == judge_model:
                    self._llm_warmup_results["router"] = (judge_model, ok)

            threads.append(threading.Thread(target=_warm_judge, daemon=True, name="warmup-judge"))

        if router_model and base_url and not shared_router:
            def _warm_router() -> None:
                ok = warm_up_ollama_model(base_url, router_model, timeout=chat_timeout)
                self._llm_warmup_results["router"] = (router_model, ok)

            threads.append(threading.Thread(target=_warm_router, daemon=True, name="warmup-router"))

        # Vision model — warmed only when vision is enabled, so the first
        # seeScreen call hits a resident model instead of paying the cold-load
        # cost. Under VRAM contention (chat 9B + judge/router 4B pinned) a cold
        # qwen2.5vl load + image eval can exceed the per-call vision timeout,
        # surfacing as "the vision system is taking a long time to wake up" on
        # the first ask after boot. Skipped when it shares a model already
        # warmed above. Best-effort and parallel like the others.
        vision_enabled = bool(getattr(self.cfg, "vision_enabled", False))
        vision_model = str(getattr(self.cfg, "vision_model", "") or "").strip()
        vision_shared = bool(vision_model) and vision_model in {
            chat_model, judge_model, router_model,
        }
        if vision_enabled and vision_model and base_url and not vision_shared:
            def _warm_vision() -> None:
                ok = warm_up_ollama_model(base_url, vision_model, timeout=chat_timeout)
                self._llm_warmup_results["vision"] = (vision_model, ok)

            threads.append(threading.Thread(target=_warm_vision, daemon=True, name="warmup-vision"))

        for t in threads:
            t.start()

        debug_log(
            f"LLM warmup started (chat={chat_model or 'n/a'}, "
            f"judge={judge_model or 'n/a'}, router={router_model or 'n/a'}, "
            f"shared_judge={shared_judge}, shared_router={shared_router})",
            "voice",
        )
        return threads

    def _weather_example(self, wake_title: str) -> str:
        """Return the weather query example for the startup banner.

        Shows the plain form when a location source is configured, or the
        [your city] placeholder form so the user knows to supply a city.
        """
        location_enabled = getattr(self.cfg, "location_enabled", True)
        location_auto_detect = getattr(self.cfg, "location_auto_detect", True)
        location_ip_address = getattr(self.cfg, "location_ip_address", None)
        location_known = (
            location_enabled
            and (location_auto_detect or bool(location_ip_address))
            and is_location_available()
        )
        if location_known:
            return f"\"How's the weather, {wake_title}?\""
        return f"\"How's the weather in [your city], {wake_title}?\""

    # Fast-failure window: if a (re)dispatched backend returns within this
    # many seconds it almost certainly failed to *start* (model OOM, mic
    # busy, bridge import error) rather than running and being asked to
    # switch — that distinction drives the fallback logic in run().
    _STT_FAST_FAIL_SEC = 8.0

    def run(self) -> None:
        """Re-entrant STT dispatcher.

        Runs the selected backend via ``_dispatch_once`` and loops so the
        backend can be hot-swapped in-process: a ``request_stt_switch`` sets
        ``_switch_event`` + ``_pending_backend``, the active backend loop
        breaks, we tear down its runtime and re-dispatch the new backend.
        On a fast startup failure of a freshly-requested backend we revert
        to the previous one (and persist that revert so the console reflects
        reality), guarding against fallback ping-pong.
        """
        while not self._should_stop:
            self._switch_event.clear()
            backend = self._stt_backend
            started = time.monotonic()
            crashed = False
            try:
                self._dispatch_once()
            except Exception as e:
                crashed = True
                debug_log(f"STT backend '{backend}' dispatch raised: {e!r}", "voice")
                print(f"  ❌ STT backend '{backend}' error: {e}", flush=True)

            if self._should_stop:
                break

            ran_long = (time.monotonic() - started) >= self._STT_FAST_FAIL_SEC
            if ran_long:
                # The backend genuinely started and ran, so any prior switch
                # succeeded — reset the fallback bookkeeping.
                self._consecutive_fast_failures = 0
                self._switch_from = None

            # Case 1: an explicit user-requested switch.
            if self._switch_event.is_set() and self._pending_backend:
                target = self._pending_backend
                self._pending_backend = None
                self._teardown_stt_runtime(backend)
                self._switch_from = backend
                self._stt_backend = target
                print(f"  🔀 Switching STT backend → {target}", flush=True)
                continue

            # Case 1b: a LONG-RUNNING backend crashed mid-flight. It started
            # fine (ran past the fast-fail window), so the crash was a
            # processing fluke, not a startup failure — restart the same
            # backend instead of exiting the thread. Exiting here left the
            # assistant permanently deaf (live: one bad utterance, then
            # switch requests and the manual trigger talked to a dead thread).
            if crashed and ran_long:
                print(f"  🔁 STT backend '{backend}' crashed after running — restarting it", flush=True)
                self._teardown_stt_runtime(backend)
                continue

            # Case 2: the backend ended on its own (returned early or raised)
            # without a switch request. A backend only returns from its loop
            # on failure (no mic, model OOM, bridge start error) — a quick
            # return therefore means it failed to *start*. Revert to the
            # backend we came from (or the other one) so the mic isn't left
            # dead, and persist that so the console shows the truth.
            if not ran_long and self._consecutive_fast_failures < 2:
                fallback = self._switch_from or ("whisper" if backend == "wispr" else "wispr")
                self._switch_from = None
                if fallback and fallback != backend:
                    self._consecutive_fast_failures += 1
                    self._teardown_stt_runtime(backend)
                    # Runtime-only revert: the configured backend is the
                    # user's PREFERENCE and must survive a failed start
                    # (user directive 2026-06-12: every restart defaults to
                    # the configured backend — e.g. Wispr Flow not running
                    # at boot must not flip the default to whisper forever).
                    print(
                        f"  ❌ STT backend '{backend}' failed to start; "
                        f"using '{fallback}' for this session "
                        f"(config still prefers '{backend}')",
                        flush=True,
                    )
                    self._stt_backend = fallback
                    continue

            # Clean stop, fatal error, or fallbacks exhausted → exit thread.
            break

        # Final teardown of whatever backend was last active.
        self._teardown_stt_runtime(self._stt_backend)

    def _dispatch_once(self) -> None:
        """Run the currently-selected STT backend once (blocks until the
        backend loop exits on stop or a requested switch)."""
        # Phase C: dispatch on STT backend. The Wispr branch owns its own
        # audio stream (openWakeWord + Silero VAD inside WisprBridge) and
        # delivers final transcripts via the on_transcription callback
        # (-> self.feed_transcript -> cascade). The Whisper branch keeps
        # the original behaviour intact — gating happens here so rollback
        # is one config flip away.
        if self._stt_backend == "wispr":
            self._run_wispr_backend()
            return

        if sd is None:
            debug_log("sounddevice not available", "voice")
            print("  ❌ Audio system not available - sounddevice failed to load", flush=True)
            return

        # Verify PortAudio is working by querying devices (catches Windows DLL issues)
        try:
            devices = sd.query_devices()
            input_devices = [d for d in devices if d.get('max_input_channels', 0) > 0]
            debug_log(f"PortAudio initialised: {len(input_devices)} input device(s) found", "voice")
            if not input_devices:
                print("  ❌ No microphone found. Please connect a microphone.", flush=True)
                return
        except Exception as e:
            debug_log(f"PortAudio device query failed: {e}", "voice")
            print(f"  ❌ Audio system error: {e}", flush=True)
            print("     PortAudio may not be properly installed", flush=True)
            if sys.platform == 'linux':
                print("     On Linux, ensure PortAudio is installed: sudo apt install libportaudio2", flush=True)
            return

        # Windows 11: Test microphone permission by attempting a brief recording
        # This catches privacy settings that silently block audio access.
        # A 5-second timeout prevents indefinite hangs when Windows blocks
        # the audio device at the system level without raising an error.
        # Uses InputStream (not sd.rec) so the stream can be explicitly closed
        # on timeout, avoiding resource leaks that could block later audio init.
        if sys.platform == 'win32':
            try:
                print("  🔐 Checking microphone permission...", flush=True)
                mic_ok = threading.Event()
                mic_error: list = [None]
                mic_stream: list = [None]

                def _mic_check():
                    try:
                        stream = sd.InputStream(
                            samplerate=self._samplerate, channels=1,
                            dtype="float32", blocksize=int(self._samplerate * 0.1),
                        )
                        mic_stream[0] = stream
                        stream.start()
                        time.sleep(0.15)
                        stream.stop()
                        stream.close()
                        mic_stream[0] = None
                        mic_ok.set()
                    except Exception as exc:
                        mic_error[0] = exc

                check_thread = threading.Thread(target=_mic_check, daemon=True)
                check_thread.start()
                check_thread.join(timeout=5.0)

                if check_thread.is_alive():
                    # Clean up the stream if the thread is still blocked
                    debug_log("microphone permission check timed out after 5s", "voice")
                    stream_ref = mic_stream[0]
                    if stream_ref is not None:
                        try:
                            stream_ref.abort()
                            stream_ref.close()
                        except Exception:
                            pass
                    print("  ⚠️  Microphone permission check timed out", flush=True)
                    print("     This may indicate Windows is blocking microphone access.", flush=True)
                    print("     Continuing anyway — voice input may not work.", flush=True)
                elif mic_error[0] is not None:
                    e = mic_error[0]
                    error_str = str(e).lower()
                    print(f"  ❌ Microphone permission check failed: {e}", flush=True)
                    if "unapproved" in error_str or "denied" in error_str or "access" in error_str or "-9999" in str(e):
                        print("", flush=True)
                        print("  ┌─────────────────────────────────────────────────────────┐", flush=True)
                        print("  │  🔒 MICROPHONE ACCESS BLOCKED BY WINDOWS               │", flush=True)
                        print("  │                                                         │", flush=True)
                        print("  │  To fix this:                                          │", flush=True)
                        print("  │  1. Open Windows Settings                              │", flush=True)
                        print("  │  2. Go to Privacy & security → Microphone              │", flush=True)
                        print("  │  3. Turn ON 'Microphone access'                        │", flush=True)
                        print("  │  4. Turn ON 'Let apps access your microphone'          │", flush=True)
                        print("  │  5. Turn ON 'Let desktop apps access your microphone'  │", flush=True)
                        print("  │                                                         │", flush=True)
                        print("  │  Then restart Jarvis.                                  │", flush=True)
                        print("  └─────────────────────────────────────────────────────────┘", flush=True)
                        print("", flush=True)
                    return
                elif mic_ok.is_set():
                    print("  ✅ Microphone permission OK", flush=True)
                else:
                    print("  ⚠️  Microphone returned empty audio", flush=True)
            except Exception as e:
                debug_log(f"microphone permission check error: {e}", "voice")
                print(f"  ⚠️  Microphone check error: {e}", flush=True)

        # Kick off LLM warmups in parallel with Whisper load so the first
        # user engagement doesn't pay cold-load cost on either model. All
        # warmup output (Whisper + LLMs) is indented under this header to
        # visually group the phase.
        print("  🔥 Warming up models...", flush=True)
        self._llm_warmup_started_at = time.time()
        self._llm_warmup_threads = self._start_llm_warmup()

        # Determine and initialise Whisper backend
        self._whisper_backend = self._determine_whisper_backend()
        model_name = getattr(self.cfg, "whisper_model", "small")

        # Validate large-v3-turbo support for faster-whisper backend
        if model_name == "large-v3-turbo" and self._whisper_backend != "mlx":
            if not _is_faster_whisper_turbo_supported():
                debug_log(
                    "faster-whisper does not support large-v3-turbo, "
                    "falling back to large-v3", "voice",
                )
                print(
                    "  ⚠️  large-v3-turbo is not supported by the installed Whisper engine, "
                    "using large-v3 instead", flush=True,
                )
                model_name = "large-v3"

        if self._whisper_backend == "mlx":
            if not MLX_WHISPER_AVAILABLE:
                debug_log("MLX Whisper not available", "voice")
                print("  ❌ MLX Whisper not available. Install with: pip install mlx-whisper", flush=True)
                return

            self._mlx_model_repo = _get_mlx_model_repo(model_name)
            print(f"     🎤 Loading MLX Whisper '{model_name}' (Apple Silicon GPU)...", flush=True)

            max_retries = 4
            for attempt in range(max_retries + 1):
                try:
                    # Pre-load the model by doing a warmup transcription.
                    # Use low-amplitude noise (not silence) so the decoder actually runs —
                    # silent audio trips the no-speech short-circuit and leaves the decode
                    # path cold, so the first real utterance still pays the full cost.
                    if np is not None:
                        rng = np.random.default_rng(0)
                        warmup_audio = rng.standard_normal(self._samplerate).astype(np.float32) * 0.01
                        _ = mlx_whisper.transcribe(
                            warmup_audio,
                            path_or_hf_repo=self._mlx_model_repo,
                            language=None,
                        )
                        debug_log(f"MLX Whisper model pre-loaded: repo={self._mlx_model_repo}", "voice")

                    print(f"     🎤 MLX Whisper '{model_name}' ready (Apple Silicon GPU)", flush=True)
                    break
                except Exception as e:
                    error_str = str(e).lower()
                    is_rate_limited = (
                        any(x in error_str for x in ["429", "too many requests", "rate limit"])
                        or getattr(getattr(e, "response", None), "status_code", None) == 429
                    )
                    if is_rate_limited and attempt < max_retries:
                        wait = 2 ** (attempt + 1)
                        debug_log(f"rate limited loading MLX Whisper (attempt {attempt + 1}): {e}", "voice")
                        print(f"  ⏳ Rate limited by HuggingFace, retrying in {wait}s ({attempt + 1}/{max_retries})...", flush=True)
                        time.sleep(wait)
                        continue
                    debug_log(f"failed to initialise MLX Whisper: {e}", "voice")
                    print(f"  ❌ Failed to initialise MLX Whisper: {e}", flush=True)
                    if is_rate_limited:
                        print("  💡 HuggingFace is rate limiting downloads. Please wait a few minutes and restart.", flush=True)
                    return
        else:
            # faster-whisper backend
            if not FASTER_WHISPER_AVAILABLE:
                debug_log("faster-whisper not available", "voice")
                print("  ❌ faster-whisper not available. Install with: pip install faster-whisper", flush=True)
                return

            device = getattr(self.cfg, "whisper_device", "auto")
            compute = getattr(self.cfg, "whisper_compute_type", "int8")

            # On Windows, probe for CUDA runtime libraries before trying to
            # use them. faster-whisper/CTranslate2 lazily loads cuBLAS and
            # cuDNN during transcription, so without this check a model
            # that loaded fine on cuda will crash on the first audio chunk.
            resolved_device, missing_libs = _probe_windows_cuda_libraries(device)
            if missing_libs:
                _print_cuda_unavailable_hint(missing_libs)
            device = resolved_device

            # Build list of (device, compute_type) combinations to try
            # This handles both compute type fallbacks and CUDA -> CPU fallbacks
            configs_to_try = []

            # Start with preferred config
            compute_types = [compute]
            if compute == "int8":
                compute_types.extend(["float16", "float32"])
            elif compute == "float16":
                compute_types.append("float32")

            # Add preferred device with all compute types
            for ct in compute_types:
                configs_to_try.append((device, ct))

            # If device is "auto" or "cuda", add CPU fallback configs
            # This handles Windows without CUDA libraries
            if device in ("auto", "cuda"):
                for ct in compute_types:
                    configs_to_try.append(("cpu", ct))

            last_error = None
            used_device = device
            used_compute = compute
            for try_device, try_compute in configs_to_try:
                try:
                    cpu_threads = (os.cpu_count() or 4) if try_device in ("cpu", "auto") else 0
                    print(f"     🎤 Loading Whisper '{model_name}' (device={try_device}, compute={try_compute})...", flush=True)
                    self.model = WhisperModel(
                        model_name, device=try_device, compute_type=try_compute,
                        cpu_threads=cpu_threads,
                    )
                    self._apply_whisper_load_success(
                        model_name, try_device, try_compute,
                        device, compute, cpu_threads,
                    )
                    used_device = try_device
                    used_compute = try_compute
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()

                    # Check if this is a CUDA/GPU-related error that we should fall back from
                    is_cuda_error = any(x in error_str for x in [
                        "cuda", "cublas", "cudnn", "gpu", "nvidia",
                        ".dll is not found", "library", "ctypes"
                    ])
                    is_compute_error = any(x in error_str for x in [
                        "compute type", "int8", "float16"
                    ])

                    if is_cuda_error or is_compute_error:
                        debug_log(f"config ({try_device}, {try_compute}) failed, trying fallback: {e}", "voice")
                        continue

                    # Check for corrupted model cache (e.g. interrupted download)
                    is_corrupted_cache = "unable to open file" in error_str

                    if is_corrupted_cache:
                        debug_log(f"detected corrupted Whisper model cache: {e}", "voice")
                        print("  ⚠️  Whisper model cache appears corrupted, attempting recovery...", flush=True)

                        cache_cleared = _clear_corrupted_whisper_cache(str(e))
                        if cache_cleared:
                            try:
                                print(f"     🎤 Re-downloading Whisper '{model_name}'...", flush=True)
                                self.model = WhisperModel(
                                    model_name, device=try_device, compute_type=try_compute,
                                    cpu_threads=cpu_threads,
                                )
                                self._apply_whisper_load_success(
                                    model_name, try_device, try_compute,
                                    device, compute, cpu_threads,
                                    context="recovered",
                                )
                                used_device = try_device
                                used_compute = try_compute
                                last_error = None
                                break
                            except Exception as retry_e:
                                debug_log(f"retry after cache clear also failed: {retry_e}", "voice")
                                print(f"  ❌ Failed to load Whisper model after cache recovery: {retry_e}", flush=True)
                                return
                        else:
                            debug_log("could not clear corrupted cache automatically", "voice")
                            print(f"  ❌ Failed to load Whisper model: {e}", flush=True)
                            print("  💡 Try manually deleting the Whisper model cache directory and restarting", flush=True)
                            return
                    # Check for rate limiting (HTTP 429) — check string and response status code
                    # (HfHubHTTPError may carry the status on .response without "429" in str(e))
                    is_rate_limited = (
                        any(x in error_str for x in ["429", "too many requests", "rate limit"])
                        or getattr(getattr(e, "response", None), "status_code", None) == 429
                    )

                    if is_rate_limited:
                        _max_retries = 4
                        _backoff = 2
                        debug_log(f"rate limited loading Whisper model: {e}", "voice")
                        retry_succeeded = False
                        for retry_num in range(1, _max_retries + 1):
                            wait = _backoff ** retry_num
                            print(f"  ⏳ Rate limited by HuggingFace, retrying in {wait}s ({retry_num}/{_max_retries})...", flush=True)
                            time.sleep(wait)
                            try:
                                self.model = WhisperModel(
                                    model_name, device=try_device, compute_type=try_compute,
                                    cpu_threads=cpu_threads,
                                )
                                self._apply_whisper_load_success(
                                    model_name, try_device, try_compute,
                                    device, compute, cpu_threads,
                                    context="rate-limit retry",
                                )
                                used_device = try_device
                                used_compute = try_compute
                                last_error = None
                                retry_succeeded = True
                                break
                            except Exception as retry_e:
                                debug_log(f"rate-limit retry {retry_num} failed: {retry_e}", "voice")
                                last_error = retry_e
                        if retry_succeeded:
                            break
                        debug_log(f"gave up after {_max_retries} rate-limit retries", "voice")
                        print(f"  ❌ Failed to load Whisper model after {_max_retries} retries: {last_error}", flush=True)
                        print("  💡 HuggingFace is rate limiting downloads. Please wait a few minutes and restart.", flush=True)
                        return
                    else:
                        # For other errors (model not found, etc.), don't try fallbacks
                        debug_log(f"failed to initialise faster-whisper: {e}", "voice")
                        print(f"  ❌ Failed to load Whisper model: {e}", flush=True)
                        return

            if last_error is not None:
                debug_log(f"failed to initialise faster-whisper with any config: {last_error}", "voice")
                print(f"  ❌ Failed to load Whisper model: {last_error}", flush=True)
                return

            # Warm up faster-whisper so the first real utterance doesn't pay
            # the cold-decode cost. Use low-amplitude noise rather than pure
            # silence — silence trips faster-whisper's no-speech short-circuit
            # and the decoder never actually runs. Mirror the real transcribe
            # parameters so beam search, language detection, and the timestamp
            # path are all exercised here instead of on the user's first word.
            if np is not None and self.model is not None:
                try:
                    cpu_mode = self._whisper_device == "cpu"
                    rng = np.random.default_rng(0)
                    warmup_audio = rng.standard_normal(self._samplerate).astype(np.float32) * 0.01
                    _crt = getattr(self.cfg, "whisper_compression_ratio_threshold", 1.35)
                    # Mirror the real-path policy: only include initial_prompt
                    # when the user has explicitly written one. Forcing a
                    # fallback ("Jarvis.") for the warmup would silently
                    # diverge from the prompt-free real-path behaviour.
                    _warmup_prompt = getattr(self.cfg, "whisper_initial_prompt", None)
                    if isinstance(_warmup_prompt, str):
                        _warmup_prompt = _warmup_prompt.strip() or None
                    _warmup_beam = int(getattr(self.cfg, "whisper_beam_size", 1))
                    _warmup_temp_chain = list(
                        getattr(self.cfg, "whisper_temperature_fallback", [0.0, 0.2, 0.4])
                    ) or [0.0]
                    _warmup_temp = (
                        tuple(_warmup_temp_chain)
                        if len(_warmup_temp_chain) > 1
                        else _warmup_temp_chain[0]
                    )
                    _warmup_hst = getattr(
                        self.cfg, "whisper_hallucination_silence_threshold", 2.0,
                    )
                    _warmup_kwargs = dict(
                        language=None,
                        vad_filter=False,
                        condition_on_previous_text=False,
                        without_timestamps=cpu_mode,
                        beam_size=_warmup_beam,
                        temperature=_warmup_temp,
                        no_speech_threshold=float(
                            getattr(self.cfg, "whisper_no_speech_threshold", 0.6)
                        ),
                    )
                    if _warmup_prompt:
                        _warmup_kwargs["initial_prompt"] = _warmup_prompt
                    if _crt is not None:
                        _warmup_kwargs["compression_ratio_threshold"] = float(_crt)
                    if _warmup_hst is not None:
                        _warmup_kwargs["hallucination_silence_threshold"] = float(_warmup_hst)
                    try:
                        segments_iter, _ = self.model.transcribe(warmup_audio, **_warmup_kwargs)
                    except TypeError:
                        segments_iter, _ = self.model.transcribe(warmup_audio, language=None)
                    for _ in segments_iter:
                        pass
                    debug_log("faster-whisper warmup transcription complete", "voice")
                except Exception as e:
                    debug_log(f"faster-whisper warmup failed: {e}", "voice")

        # Wait for LLM warmups before announcing "Listening!" so the first
        # engagement is responsive. A single 60s budget is shared across
        # all warmup threads so a slow/down Ollama can't block us from
        # listening — we'll just pay the cold-load cost on demand.
        warmup_threads = getattr(self, "_llm_warmup_threads", [])
        if warmup_threads:
            budget = 60.0
            deadline = getattr(self, "_llm_warmup_started_at", time.time()) + budget
            for t in warmup_threads:
                remaining = max(0.0, deadline - time.time())
                t.join(timeout=remaining)

            still_warming = any(t.is_alive() for t in warmup_threads)
            results = getattr(self, "_llm_warmup_results", {})

            # Trailing space after ⚠️ intentional: the warning glyph renders
            # narrower than 🧠/💬, so the pad keeps columns aligned.
            def _print_status(role_key: str, label: str, ok_icon: str) -> None:
                entry = results.get(role_key)
                if entry is None:
                    return
                name, ok = entry
                icon = ok_icon if ok else "⚠️ "
                status = "ready" if ok else "warmup failed — will load on first use"
                print(f"     {icon} {label} '{name}' {status}", flush=True)

            _print_status("chat", "Chat model", "💬")
            _print_status("judge", "Intent judge", "🧠")
            _print_status("router", "Tool router", "🔧")

            if still_warming:
                debug_log("LLM warmup still running after 60s — continuing without", "voice")
                print("     ⏳ Some models still warming — continuing anyway", flush=True)

        # Audio parameters
        frame_ms = int(getattr(self.cfg, "vad_frame_ms", 20))
        self._frame_samples = max(1, int(self._samplerate * frame_ms / 1000))
        pre_roll_ms = int(getattr(self.cfg, "vad_pre_roll_ms", 240))
        endpoint_silence_ms = int(getattr(self.cfg, "endpoint_silence_ms", 800))
        max_utt_ms = int(getattr(self.cfg, "max_utterance_ms", 12000))
        tts_max_utt_ms = int(getattr(self.cfg, "tts_max_utterance_ms", 3000))

        pre_roll_max_frames = max(1, int(pre_roll_ms / frame_ms))
        endpoint_silence_frames = max(1, int(endpoint_silence_ms / frame_ms))
        # max_utt_frames will be calculated dynamically based on TTS state
        normal_max_utt_frames = max(1, int(max_utt_ms / frame_ms))
        tts_max_utt_frames = max(1, int(tts_max_utt_ms / frame_ms))

        debug_log(f"audio params: sample_rate={self._samplerate}, frame_ms={frame_ms}, frame_samples={self._frame_samples}", "voice")
        debug_log(f"VAD: enabled={bool(self._vad is not None)}, aggressiveness={getattr(self.cfg, 'vad_aggressiveness', 2)}", "voice")

        # Audio device setup
        stream_kwargs = {}
        device_env = (self.cfg.voice_device or '').strip().lower()

        if self.cfg.voice_debug:
            debug_log("available input devices:", "voice")
            try:
                for idx, dev in enumerate(sd.query_devices()):
                    try:
                        max_in = int(dev.get("max_input_channels", 0))
                    except Exception:
                        max_in = 0
                    if max_in > 0:
                        name = dev.get("name")
                        rate = dev.get("default_samplerate")
                        debug_log(f"  [{idx}] {name} (channels={max_in}, default_sr={rate})", "voice")
            except Exception:
                pass

        # Configure audio device
        if device_env and device_env not in ("default", "system"):
            try:
                device_index = int(self.cfg.voice_device)
            except ValueError:
                device_index = None
                try:
                    for idx, dev in enumerate(sd.query_devices()):
                        if isinstance(dev.get("name"), str) and (self.cfg.voice_device or '').lower() in dev.get("name").lower():
                            device_index = idx
                            break
                except Exception:
                    device_index = None
            if device_index is not None:
                stream_kwargs["device"] = device_index

        # Log which device will be used
        try:
            if "device" in stream_kwargs:
                dev = sd.query_devices(stream_kwargs["device"])
                device_name = dev.get('name', 'Unknown')
                debug_log(f"using input device: {device_name} (index {stream_kwargs['device']})", "voice")
                print(f"  🎤 Using audio device: {device_name}", flush=True)
            else:
                debug_log("using system default input device", "voice")
                try:
                    default_dev = sd.query_devices(sd.default.device[0])
                    print(f"  🎤 Using default device: {default_dev.get('name', 'Unknown')}", flush=True)
                except Exception:
                    print("  🎤 Using system default input device", flush=True)
        except Exception:
            pass

        # Open audio stream — try configured rate first, fall back to device
        # native rate when the hardware rejects 16 kHz (common on Linux ALSA).
        self._stream_samplerate = self._samplerate
        open_error = None
        try:
            stream = sd.InputStream(
                samplerate=self._samplerate,
                channels=1,
                dtype="float32",
                blocksize=self._frame_samples,
                callback=self._on_audio,
                **stream_kwargs,
            )
        except Exception as e:
            error_msg = str(e).lower()
            is_rate_error = "sample rate" in error_msg or "9987" in error_msg
            if is_rate_error:
                debug_log(f"device rejected {self._samplerate} Hz, querying native rate", "voice")
                try:
                    if "device" in stream_kwargs:
                        dev_info = sd.query_devices(stream_kwargs["device"])
                    else:
                        dev_info = sd.query_devices(kind="input")
                    native_rate = int(dev_info.get("default_samplerate", self._samplerate))
                    if native_rate != self._samplerate:
                        self._stream_samplerate = native_rate
                        native_frame_samples = max(1, int(native_rate * 30 / 1000))
                        print(f"  ⚠️  Device doesn't support {self._samplerate} Hz — using {native_rate} Hz with resampling", flush=True)
                        debug_log(f"retrying stream at native {native_rate} Hz", "voice")
                        stream = sd.InputStream(
                            samplerate=native_rate,
                            channels=1,
                            dtype="float32",
                            blocksize=native_frame_samples,
                            callback=self._on_audio,
                            **stream_kwargs,
                        )
                    else:
                        open_error = e
                except Exception:
                    open_error = e
            else:
                open_error = e

        if open_error is not None:
            error_msg = str(open_error).lower()
            debug_log(f"failed to open input stream: {open_error}", "voice")

            # Provide helpful error messages for common issues
            if "access" in error_msg or "permission" in error_msg:
                print(f"  ❌ Microphone access denied. Please check: {_get_mic_permission_hint()}", flush=True)
            elif "device" in error_msg and ("use" in error_msg or "busy" in error_msg):
                print("  ❌ Microphone is being used by another application", flush=True)
            elif "device" in error_msg:
                print(f"  ❌ Failed to open microphone: {open_error}", flush=True)
                print("     Try selecting a different audio device in settings", flush=True)
            else:
                print(f"  ❌ Failed to start audio recording: {open_error}", flush=True)
            return

        # Main audio processing loop
        with stream:
            # Verify stream is actually recording (helps catch permission issues)
            if not stream.active:
                try:
                    stream.start()
                except Exception as e:
                    error_msg = str(e).lower()
                    debug_log(f"failed to start audio stream: {e}", "voice")
                    if "access" in error_msg or "permission" in error_msg:
                        print(f"  ❌ Microphone access denied. Please check: {_get_mic_permission_hint()}", flush=True)
                    else:
                        print(f"  ❌ Failed to start recording: {e}", flush=True)
                    return

            # Show ready message only after stream is confirmed active
            wake_word = getattr(self.cfg, "wake_word", "jarvis").lower()
            wake_title = wake_word.title()
            print(f"\n{'─' * 50}\n🎙️  Listening! Try:", flush=True)
            print(f"      {self._weather_example(wake_title)}", flush=True)
            print(f"      \"I just ate a Big Mac, {wake_title}.\"", flush=True)
            print(f"      \"What are you thinking, {wake_title}?\"", flush=True)
            print(f"      \"What do you know about me, {wake_title}?\"", flush=True)

            # Small-model disclaimer: SMALL models can't infer your intent
            # from vague prompts, but they can still execute complex flows
            # if you spell out the steps. Assume the model is dumb and lay
            # things out for it. Classification lives in model_variants so
            # it stays in sync when supported models change.
            from ..reply.prompts.model_variants import detect_model_size, ModelSize
            chat_model_name = str(getattr(self.cfg, "ollama_chat_model", "") or "").strip()
            if chat_model_name and detect_model_size(chat_model_name) == ModelSize.SMALL:
                print(
                    f"  ⚠️  Small model in use ({chat_model_name}). Assume it can't infer — spell out the steps for anything more involved:",
                    flush=True,
                )
                print(
                    f"      \"Tell me tomorrow's weather, then find local events for tomorrow, then recommend ones that suit the weather, {wake_title}.\"",
                    flush=True,
                )

            # Chrome MCP tip: the chrome MCP exposes a `navigate` tool that
            # takes a URL. Vague phrasing like "Open YouTube" forces the model
            # to guess a URL; "Navigate to youtube.com" maps directly to the
            # tool's argument and is more reliable on small models.
            try:
                from ..tools.registry import get_cached_mcp_tools
                mcp_tool_names = list(get_cached_mcp_tools().keys())
                has_chrome_mcp = any("chrome" in name.lower() for name in mcp_tool_names)
            except Exception:
                has_chrome_mcp = False
            if has_chrome_mcp:
                print(
                    f"  🌐 Chrome MCP detected. Name the destination URL so the browser tool can act directly:",
                    flush=True,
                )
                print(
                    f"      \"Navigate to youtube.com, {wake_title}.\"",
                    flush=True,
                )

            # Set face state to IDLE (awake and ready, waiting for wake word)
            try:
                from desktop_app.face_widget import get_jarvis_state, JarvisState
                state_manager = get_jarvis_state()
                state_manager.set_state(JarvisState.IDLE)
            except Exception:
                pass

            # Track start time for audio health monitoring
            _audio_start_time = time.time()
            _audio_health_logged = False

            while not self._should_stop and not self._switch_event.is_set():
                # Manual finalize: mute pressed during Trigger Now listening.
                # Read-and-clear atomically so a concurrent MUTE on the bus
                # worker can never be lost or consumed twice.
                if self._consume_manual_finalize():
                    if self.is_speech_active:
                        self._finalize_utterance()
                    if self.state_manager.is_collecting():
                        query = self.state_manager.clear_collection()
                        if query.strip():
                            self._dispatch_query(query)
                        else:
                            self._stop_thinking_tune()
                            try:
                                from desktop_app.face_widget import get_jarvis_state, JarvisState
                                get_jarvis_state().set_state(JarvisState.IDLE)
                            except Exception:
                                pass
                    self._clear_audio_buffers()
                    continue

                # One-time audio health check after 5 seconds
                if not _audio_health_logged and time.time() - _audio_start_time > 5:
                    _audio_health_logged = True
                    if self._callback_count == 0:
                        print("  ⚠️  No audio received after 5 seconds!", flush=True)
                        print(f"     Check: {_get_mic_permission_hint()}", flush=True)
                        print("     Also check that your microphone is not muted", flush=True)

                try:
                    item = self._audio_q.get(timeout=0.2)
                except queue.Empty:
                    # Critical: Check timeouts even when no audio is being received
                    # This ensures hot window expiry fires reliably
                    self._check_query_timeout()
                    continue

                # Discard queued audio when muted
                with self._control_flags_lock:
                    muted = self._muted
                if muted:
                    continue

                if item is None:
                    # Reset marker
                    self.is_speech_active = False
                    self._silence_frames = 0
                    self._utterance_frames = []
                    self._pre_roll.clear()
                    continue

                if np is None:
                    continue

                # Process audio buffer
                buf = item
                try:
                    mono = buf.reshape(-1, buf.shape[-1])[:, 0] if buf.ndim > 1 else buf.flatten()
                except Exception:
                    mono = buf.flatten()

                # Process frames
                offset = 0
                total = mono.shape[0]
                frame_timestamp = time.time()  # Timestamp for this batch of frames

                while offset + self._frame_samples <= total:
                    frame = mono[offset: offset + self._frame_samples]
                    offset += self._frame_samples

                    # VAD decision
                    is_voice = self._is_speech_frame(frame)

                    if not self.is_speech_active:
                        if is_voice:
                            self.is_speech_active = True

                            # Backdate start time by pre-roll duration — the
                            # actual speech onset was before VAD triggered.
                            pre_roll_sec = len(self._pre_roll) * frame_ms / 1000.0
                            utterance_start_time = time.time() - pre_roll_sec

                            # Track utterance timing for echo detection
                            self.echo_detector.track_utterance_timing(utterance_start_time, 0.0)

                            # Seed with pre-roll
                            if self._pre_roll:
                                self._utterance_frames.extend(list(self._pre_roll))
                            self._utterance_frames.append(frame.copy())
                            self._silence_frames = 0
                        else:
                            # Maintain pre-roll buffer
                            self._pre_roll.append(frame.copy())
                            while len(self._pre_roll) > pre_roll_max_frames:
                                try:
                                    self._pre_roll.popleft()
                                except Exception:
                                    break
                    else:
                        # CRITICAL: append EVERY frame to the utterance, even
                        # ones VAD labelled "silence". The VAD's role is
                        # endpoint detection (when to STOP listening), not
                        # which frames to keep. Dropping VAD-silence frames
                        # mid-utterance gave Whisper a swiss-cheese audio
                        # stream and was the root cause of mistranscriptions
                        # like "ποιος είναι ο καιρός στη Θεσσαλονίκη" →
                        # "εσείς είναι από την Καλονίκη" (Whisper hallucinated
                        # connective tissue between captured speech fragments).
                        # Whisper handles intra-utterance silence fine.
                        self._utterance_frames.append(frame.copy())
                        if is_voice:
                            self._silence_frames = 0
                        else:
                            self._silence_frames += 1
                            # Use shorter timeout during TTS for quick stop command detection
                            current_max_frames = tts_max_utt_frames if (self.tts and self.tts.is_speaking()) else normal_max_utt_frames
                            if self._silence_frames >= endpoint_silence_frames or len(self._utterance_frames) >= current_max_frames:
                                self._finalize_utterance()
                                self._pre_roll.clear()

                    # Check for query timeouts
                    self._check_query_timeout()

                # Handle remaining audio
                if offset < total:
                    tail = mono[offset:]
                    if tail.size > 0:
                        self._pre_roll.append(tail.copy())
                        while len(self._pre_roll) > pre_roll_max_frames:
                            try:
                                self._pre_roll.popleft()
                            except Exception:
                                break

    def _finalize_utterance(self) -> None:
        """Process completed utterance through speech recognition."""
        if np is None or not self._utterance_frames:
            self.is_speech_active = False
            self._silence_frames = 0
            self._utterance_frames = []
            return

        # Track when utterance ends - but don't overwrite global timing yet
        utterance_end_time = time.time()
        utterance_start_time = self.echo_detector._utterance_start_time

        if self.cfg.voice_debug:
            utterance_duration = utterance_end_time - utterance_start_time if utterance_start_time > 0 else 0
            start_time_str = datetime.fromtimestamp(utterance_start_time).strftime('%H:%M:%S.%f')[:-4] if utterance_start_time > 0 else "N/A"
            end_time_str = datetime.fromtimestamp(utterance_end_time).strftime('%H:%M:%S.%f')[:-4]
            debug_log(f"utterance captured: duration={utterance_duration:.2f}s (started: {start_time_str}, ended: {end_time_str})", "voice")

        # Transcribe full audio - the intent judge will extract the relevant query
        try:
            audio = np.concatenate(self._utterance_frames, axis=0).flatten()
        except Exception:
            audio = None

        # Calculate energy before clearing frames for transcript processing
        utterance_energy = self._calculate_audio_energy(self._utterance_frames[-10:] if self._utterance_frames else [])

        # Reset state before processing
        self.is_speech_active = False
        self._silence_frames = 0
        self._utterance_frames = []

        if audio is None or audio.size == 0:
            return

        # Resample to Whisper's expected rate if the stream ran at a different rate
        stream_rate = getattr(self, "_stream_samplerate", self._samplerate)
        if stream_rate != self._samplerate:
            audio = _resample(audio, stream_rate, self._samplerate)

        # Filter short audio
        audio_duration = len(audio) / self._samplerate
        min_duration = getattr(self.cfg, "whisper_min_audio_duration", 0.3)
        if audio_duration < min_duration:
            debug_log(f"audio too short ({audio_duration:.2f}s < {min_duration}s), ignoring", "voice")
            self.state_manager.check_hot_window_expiry(self.cfg.voice_debug)
            return

        # Per-utterance RMS diagnostic (Phase A — A8). Logs the segment's
        # signal level so we can tell whether the mic is genuinely underdriving
        # (in which case Phase B's DSP frontend is the right escalation) or
        # whether the issue is downstream of audio capture.
        try:
            _seg_rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
            debug_log(
                f"utterance RMS={_seg_rms:.4f} duration={audio_duration:.2f}s",
                "voice",
            )
        except Exception:
            _seg_rms = 0.0

        # Optional debug WAV dump. When `voice_debug_save_audio: true` is set
        # in config, each VAD-gated segment is written to %LOCALAPPDATA%/
        # Jarvis/debug_audio/ as utterance_YYYYMMDD_HHMMSS.wav. Lets us
        # listen to exactly what Whisper hears and decide whether
        # mistranscriptions are an audio-quality problem or a model problem.
        # Off by default — has zero effect on the live path.
        if bool(getattr(self.cfg, "voice_debug_save_audio", False)):
            try:
                self._dump_utterance_wav(audio)
            except Exception as e:
                debug_log(f"debug audio dump failed: {e}", "voice")

        # Per-segment gain normalisation (Phase A — A4). Different from the
        # continuous AGC we removed: this runs ONCE on the complete VAD-gated
        # segment, after VAD has confirmed there's actual speech. It does not
        # amplify silence frames and does not interfere with Whisper's
        # internal mel-spectrogram normalisation (which is a global statistic,
        # not aware of per-segment levels). Brings PD200X-style dynamic-mic
        # input up to the amplitude range Whisper's training set occupies.
        try:
            from .audio_preproc import normalize_segment
            audio = normalize_segment(
                audio,
                target_rms=float(getattr(self.cfg, "mic_agc_target_rms", 0.1)),
            )
        except Exception as e:
            debug_log(f"segment normalisation failed (using raw audio): {e}", "voice")

        # Speech recognition with appropriate backend
        try:
            if self._whisper_backend == "mlx":
                # MLX Whisper transcription
                with self.transcribe_lock:
                    result = mlx_whisper.transcribe(
                        audio,
                        path_or_hf_repo=self._mlx_model_repo,
                        language=None,
                    )

                # Capture Whisper's auto-detected language (ISO-639-1) so
                # downstream tools can pick locale-appropriate resources.
                detected = result.get("language")
                if isinstance(detected, str) and detected:
                    self._last_detected_language = detected

                # Filter segments by confidence (MLX Whisper returns segments with avg_logprob)
                min_confidence = getattr(self.cfg, "whisper_min_confidence", 0.3)
                marginal_threshold = min_confidence / 3  # Show user-visible log for marginal confidence
                no_speech_threshold = getattr(self.cfg, "whisper_no_speech_threshold", 0.5)
                segments = result.get("segments", [])

                if segments:
                    filtered_texts = []
                    for seg in segments:
                        avg_logprob = seg.get("avg_logprob", 0)
                        no_speech_prob = seg.get("no_speech_prob", 0)

                        # Convert avg_logprob to confidence (typically -1 to 0, so add 1)
                        confidence = min(1.0, max(0.0, avg_logprob + 1.0))
                        seg_text = seg.get("text", "").strip()

                        # Hard filter: high no_speech_prob means no real speech regardless of logprob.
                        if is_whisper_hallucination(no_speech_prob, no_speech_threshold):
                            debug_log(f"MLX segment filtered (no_speech_prob={no_speech_prob:.2f}): '{seg_text[:50]}'", "voice")
                            continue

                        if confidence < min_confidence:
                            if confidence >= marginal_threshold:
                                # Marginal confidence - show in log viewer (not debug)
                                print(f"🔇 Low confidence ({confidence:.2f}): \"{seg_text[:50]}...\"", flush=True)
                            else:
                                # Very low confidence - debug only
                                debug_log(f"MLX segment filtered (confidence={confidence:.2f}): '{seg_text[:50]}'", "voice")
                            continue

                        filtered_texts.append(seg.get("text", ""))

                    text = " ".join(filtered_texts).strip()
                else:
                    # Fallback to full text if no segments
                    text = result.get("text", "").strip()
            else:
                # faster-whisper transcription
                # CPU mode: skip timestamps for speed.
                cpu_mode = self._whisper_device == "cpu"

                allowed = list(getattr(self.cfg, "whisper_allowed_languages", None) or ["el", "en"])

                # `initial_prompt` is interpreted as "the start of the
                # transcript the model has been writing", not as instructions.
                # Long / instruction-style prompts get memorised and echoed
                # back as transcription (real failure observed in production:
                # the prompt's literal text replaced the user's speech). We
                # only pass a prompt when the user has explicitly written one
                # — and document in the spec that it must be SHORT and
                # speech-style. See the "Prompt poisoning" section.
                effective_prompt = getattr(self.cfg, "whisper_initial_prompt", None)
                if isinstance(effective_prompt, str):
                    effective_prompt = effective_prompt.strip() or None

                # Language hint selection:
                # 1. Sticky lock consensus from recent utterances (best).
                # 2. Configured `whisper_default_language` bootstrap (covers
                #    the first-utterance case where the lock has no data).
                # 3. None → Whisper auto-detects (least reliable on short or
                #    quiet audio — e.g. it once labelled Greek as German).
                language_hint = self._language_lock.suggest()
                if language_hint is None:
                    default_lang = getattr(self.cfg, "whisper_default_language", None)
                    if isinstance(default_lang, str) and default_lang:
                        language_hint = default_lang

                # Decoder accuracy knobs (Phase A — see listening.spec.md):
                # - condition_on_previous_text=False ALWAYS — command-style ASR
                #   processes utterances independently; carry-over only spreads
                #   one utterance's errors into the next.
                # - beam_size=1 (greedy) by default — large beam values explore
                #   the decoding tree to "find" plausible sentences in noise,
                #   amplifying silence hallucinations. Greedy collapses the
                #   search space so the model fails fast on silence. Also
                #   avoids a Blackwell GSP firmware crash with multi-stream
                #   beam search.
                # - temperature schedule [0.0, 0.2, 0.4] — Whisper retries
                #   with rising temperatures when the primary T=0.0 trips the
                #   compression/no-speech gates, helping it escape repetition
                #   loops on ambiguous input.
                # - no_speech_threshold + compression_ratio_threshold +
                #   hallucination_silence_threshold — three layers of
                #   hallucination defence at the decoder level.
                _no_speech = float(getattr(self.cfg, "whisper_no_speech_threshold", 0.6))
                _crt = getattr(self.cfg, "whisper_compression_ratio_threshold", 1.35)
                _beam = int(getattr(self.cfg, "whisper_beam_size", 1))
                _temp_chain = list(getattr(self.cfg, "whisper_temperature_fallback", [0.0, 0.2, 0.4])) or [0.0]
                _hst = getattr(self.cfg, "whisper_hallucination_silence_threshold", 2.0)
                _temp_arg = tuple(_temp_chain) if len(_temp_chain) > 1 else _temp_chain[0]
                _decode_kwargs = dict(
                    vad_filter=False,
                    condition_on_previous_text=False,
                    without_timestamps=cpu_mode,
                    beam_size=_beam,
                    temperature=_temp_arg,
                    no_speech_threshold=_no_speech,
                )
                if effective_prompt:
                    _decode_kwargs["initial_prompt"] = effective_prompt
                if _crt is not None:
                    _decode_kwargs["compression_ratio_threshold"] = float(_crt)
                if _hst is not None:
                    # faster-whisper added this in 1.1.x — the TypeError
                    # fallback below covers older versions that don't accept it.
                    _decode_kwargs["hallucination_silence_threshold"] = float(_hst)

                with self.transcribe_lock:
                    try:
                        segments, _info = self.model.transcribe(
                            audio, language=language_hint, **_decode_kwargs,
                        )
                    except TypeError:
                        # Older faster-whisper that doesn't accept some kwargs.
                        segments, _info = self.model.transcribe(audio, language=language_hint)
                    segments_list = list(segments)

                # Capture detected language; guard against older API variants.
                detected = getattr(_info, "language", None)
                if isinstance(detected, str) and detected and allowed and detected not in allowed:
                    # Smart fallback: prefer the locked language, otherwise
                    # probability-vote between the allowed languages. Avoids
                    # the regression where Greek speech mis-detected as `de`
                    # got force-transcribed as English (allowed[0]) producing
                    # nonsense like "That'll be...".
                    fallback_lang = self._pick_fallback_language(
                        audio, allowed, _decode_kwargs,
                    )
                    debug_log(
                        f"whisper detected '{detected}' (not in allowed {allowed}); "
                        f"re-transcribing as '{fallback_lang}'",
                        "voice",
                    )
                    with self.transcribe_lock:
                        try:
                            segments, _info = self.model.transcribe(
                                audio, language=fallback_lang, **_decode_kwargs,
                            )
                        except TypeError:
                            segments, _info = self.model.transcribe(audio, language=fallback_lang)
                        segments_list = list(segments)
                    detected = fallback_lang

                if isinstance(detected, str) and detected:
                    self._last_detected_language = detected
                    # Feed the lock so future utterances benefit from consensus.
                    self._language_lock.record(detected)
                filtered_segments = self._filter_noisy_segments(segments_list)
                text = " ".join(seg.text for seg in filtered_segments).strip()
        except Exception as e:
            debug_log(f"transcription error: {e}", "voice")
            if sys.platform == 'win32':
                print(f"  ❌ Whisper error: {e}", flush=True)
            text = ""

        if not text or not text.strip():
            self.state_manager.check_hot_window_expiry(self.cfg.voice_debug)
            return

        # Log successful transcription — separator omitted on the first utterance since
        # there is no prior turn to visually separate from.
        separator = "" if self._first_utterance else f"\n{'─' * 50}"
        self._first_utterance = False
        print(f"{separator}\n📝 Heard: \"{text}\"", flush=True)

        # Filter out repetitive hallucinations (e.g., "don't don't don't...")
        if self._is_repetitive_hallucination(text):
            debug_log(f"rejected repetitive hallucination: '{text[:80]}...'", "voice")
            self.state_manager.check_hot_window_expiry(self.cfg.voice_debug)
            return

        # Add to transcript buffer for context-aware processing
        # Mark as "during TTS" if utterance STARTED during TTS (not just if TTS is still speaking now)
        # This ensures mixed echo+user speech gets properly marked for intent judge
        if self.tts is not None and self.tts.is_speaking():
            is_during_tts = True
        else:
            tts_finish_time = self.echo_detector._last_tts_finish_time
            echo_tolerance = self.echo_detector.echo_tolerance
            is_during_tts = (tts_finish_time > 0 and utterance_start_time > 0 and utterance_start_time < tts_finish_time + echo_tolerance)
        self._transcript_buffer.add(
            text=text,
            start_time=utterance_start_time,
            end_time=utterance_end_time,
            energy=utterance_energy,
            is_during_tts=is_during_tts,
        )

        # Process the transcript with pre-calculated energy and utterance timing.
        # Per-utterance isolation: an exception while HANDLING one transcript
        # must never collapse the backend loop (live: a NameError in the
        # wake-ack path propagated to the dispatcher, which treated the
        # long-running backend's crash as fatal and exited the STT thread —
        # the assistant went permanently deaf until restart).
        try:
            self._process_transcript(text, utterance_energy, utterance_start_time, utterance_end_time)
        except Exception as e:
            debug_log(f"transcript processing failed (utterance dropped): {e!r}", "error")
            self._stop_thinking_tune()
            self._set_face_state_idle()

    # ==================================================================
    # Phase C + D — Wispr Flow backend
    # ==================================================================
    # The Wispr branch replaces Whisper + sounddevice + Silero (the
    # `run()` loop above) with the WisprBridge: openWakeWord wake
    # detection, Silero VAD endpointing, and clipboard pickup of the
    # final transcript from Wispr Flow's cloud round-trip. Transcripts
    # land in `feed_transcript` (called from a daemon worker thread)
    # and are funnelled through the SAME intent cascade Whisper uses
    # via `_dispatch_wispr_transcript_to_cascade`.

    def _run_wispr_backend(self) -> None:
        """Main loop for the Wispr Flow backend (Phase C).

        Boots the WisprBridge (loads openWakeWord + Silero, opens its
        own sounddevice InputStream) and then idles on
        ``self._should_stop`` so the daemon-thread `VoiceListener` stays
        alive for the duration of the process. Transcripts and wake
        events arrive asynchronously via the callbacks wired up in
        ``__init__``.
        """
        # Build (or rebuild, after a whisper→wispr hot-switch) the bridge.
        if not self._ensure_wispr_bridge():
            print(
                "  ❌ Wispr backend selected but bridge unavailable. "
                "Falling back to local Whisper.",
                flush=True,
            )
            return

        # Kick off LLM warmups in parallel with model load (mirrors the
        # Whisper branch — first engagement shouldn't pay cold-load
        # cost on either the STT or the LLMs).
        print("  🔥 Warming up LLM models in parallel with Wispr bridge...", flush=True)
        self._llm_warmup_started_at = time.time()
        self._llm_warmup_threads = self._start_llm_warmup()

        # Block until the bridge has loaded models and opened the audio
        # stream. Returns False on any failure — print a hint and bail.
        print("  🎙️  Starting Wispr bridge (openWakeWord + Silero VAD)...", flush=True)
        try:
            ok = self._wispr_bridge.start()
        except Exception as e:  # noqa: BLE001 — defensive: bridge may raise on import
            debug_log(f"WisprBridge.start() raised: {e}", "voice")
            print(f"  ❌ WisprBridge startup error: {e}", flush=True)
            return

        if not ok:
            print(
                "  ❌ WisprBridge failed to start. Check the [ERROR]/[HINT] "
                "lines above for the root cause (missing openWakeWord, "
                "Silero, mic permissions, etc.).",
                flush=True,
            )
            return

        # Drain LLM warmups (same 60s budget as the Whisper branch).
        warmup_threads = getattr(self, "_llm_warmup_threads", [])
        if warmup_threads:
            budget = 60.0
            deadline = getattr(self, "_llm_warmup_started_at", time.time()) + budget
            for t in warmup_threads:
                remaining = max(0.0, deadline - time.time())
                t.join(timeout=remaining)
            results = getattr(self, "_llm_warmup_results", {})

            def _print_status(role_key: str, label: str, ok_icon: str) -> None:
                entry = results.get(role_key)
                if entry is None:
                    return
                name, ready = entry
                icon = ok_icon if ready else "⚠️ "
                status = "ready" if ready else "warmup failed — will load on first use"
                print(f"     {icon} {label} '{name}' {status}", flush=True)

            _print_status("chat", "Chat model", "💬")
            _print_status("judge", "Intent judge", "🧠")
            _print_status("router", "Tool router", "🔧")

        wake_title = getattr(self.cfg, "wake_word", "jarvis").lower().title()
        print(f"\n{'─' * 50}\n🎙️  Listening via Wispr Flow! Try:", flush=True)
        print(f"      {self._weather_example(wake_title)}", flush=True)
        print(f"      \"What are you thinking, {wake_title}?\"", flush=True)

        # Set face state to IDLE — bridge is up and waiting for "Hey Jarvis".
        try:
            from desktop_app.face_widget import get_jarvis_state, JarvisState
            get_jarvis_state().set_state(JarvisState.IDLE)
        except Exception:
            pass

        # Stay alive — the bridge runs its own threads. We just need to
        # keep the VoiceListener thread alive so stop() can be called
        # cleanly from the outside (or a hot-switch can yield us).
        while not self._should_stop and not self._switch_event.is_set():
            time.sleep(0.2)

        # Clean shutdown — stop the bridge if it's still running.
        try:
            self._wispr_bridge.stop()
        except Exception as e:
            debug_log(f"WisprBridge stop error (during run shutdown): {e}", "voice")

    def feed_transcript(self, text: str) -> None:
        """Entry point for transcripts arriving from WisprBridge.

        Called from a background thread (the WisprPostDictationWorker
        in wispr_bridge.py) when Wispr Flow produces a final transcript.
        Runs the text through the same intent cascade Whisper would have
        used.

        Thread-safety: this method does not block the bridge's worker —
        we strip the leading wake word and then dispatch synchronously
        into the cascade. Dictations are serialised by the bridge state
        machine (DICTATING -> IDLE happens before the next wake fires),
        so concurrent invocations are not expected. If they did occur,
        the underlying state machinery (`state_manager`, `tts`,
        `dialogue_memory`) holds its own locks where needed.
        """
        text = (text or "").strip()
        if not text:
            return

        # STOP guard: drop any transcript that lands inside the post-abort
        # suppression window. After a STOP (reset_everything) a late echo /
        # phantom / leftover transcript could otherwise re-enter the cascade and
        # restart the thinking tune, which is exactly what forced the user to
        # press STOP twice. A genuine new engagement clears the window via
        # _on_wispr_wake, so deliberate re-use is never blocked.
        if time.monotonic() < getattr(self, "_post_abort_suppress_until", 0.0):
            debug_log(
                f"feed_transcript: dropped (post-STOP suppression): '{text[:40]}'",
                "voice",
            )
            return

        # Strip leading wake word if Wispr Flow captured it. The wake
        # word fires ~200ms before PTT, so Wispr Flow's recording can
        # easily include the wake word at the head of the transcript.
        text = self._strip_leading_wake_word(text)
        if not text:
            debug_log("feed_transcript: text empty after wake-word strip", "voice")
            return

        # Never route a pure stop/interrupt utterance into the cascade as a
        # query. Reuse the bridge's language-agnostic stop pattern (single
        # source of truth) rather than hardcoding stop words here.
        try:
            from .wispr_bridge import WisprBridge
            if WisprBridge._STOP_PATTERN.match(text):
                debug_log("feed_transcript: dropped pure-stop transcript", "voice")
                return
        except Exception:
            pass

        debug_log(f"feed_transcript → cascade: '{text[:80]}'", "voice")
        try:
            self._dispatch_wispr_transcript_to_cascade(text)
        except Exception as e:  # noqa: BLE001 — never crash the bridge worker
            debug_log(f"_dispatch_wispr_transcript_to_cascade raised: {e}", "voice")
            print(f"  ❌ Wispr cascade dispatch error: {e}", flush=True)

    def _strip_leading_wake_word(self, text: str) -> str:
        """Strip a leading wake word ('hey jarvis' / 'jarvis' / Greek
        variants) from a Wispr Flow transcript. Match is case-insensitive
        and tolerant of surrounding punctuation/whitespace."""
        import re
        return re.sub(
            r"^\s*(hey|ok|okay|hi|hello|γεια)?\s*"
            r"(jarvis|τζάρβις|τζαρβις|γιάρβης|γιαρβης)"
            r"[\s,.\-:!?]*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

    def _on_wispr_wake(self) -> None:
        """Called from the bridge's audio thread the instant the wake
        word fires (BEFORE the dictation completes). SHORT — do not
        block the audio callback. Heavy work happens in
        ``feed_transcript`` later once the transcript arrives.

        The thinking tune is deliberately NOT started here: it is a
        PROCESSING indicator, not a listening one. While the user is still
        speaking we only show the LISTENING face/popup; the tune begins when
        processing begins (``_dispatch_query``)."""
        # A genuine new wake clears any post-STOP suppression window so a
        # deliberate re-engagement right after a STOP is never dropped.
        self._post_abort_suppress_until = 0.0
        try:
            self._set_face_state_listening()
        except Exception:
            pass
        # Clear the PREVIOUS turn's query on the HUD: Wispr only delivers the
        # transcript at the end of the utterance, so without this the eye
        # preview shows the old text while the user is speaking the new one.
        try:
            from .. import api_server
            api_server.publish_state(query="")
        except Exception:
            pass
        # Set a synthetic wake timestamp so the cascade's
        # `has_engagement_signal` gate accepts the transcript we'll
        # feed in shortly.
        try:
            self._wake_timestamp = time.time()
        except Exception:
            pass

    def _on_wispr_dictation_end(self, captured: bool = True, reason=None) -> None:
        """Called from the post-dictation worker once clipboard polling
        has either captured the transcript or timed out.

        Args:
            captured: True if Wispr Flow produced a transcript, False otherwise.
                Defaults to True so any caller that doesn't pass the flag
                keeps the original no-op behaviour.
            reason: Why no transcript was captured (``None`` when captured):
                ``"off"`` (clipboard polling disabled / pyperclip missing),
                ``"timeout"`` (watched but nothing arrived in time), or
                ``"unchanged"`` (clipboard never advanced). Used only to give a
                more honest notice; defaults to ``None`` for backward
                compatibility with one-argument callers.

        When ``captured`` is True the cascade entry (``_process_transcript``
        invoked from ``_dispatch_wispr_transcript_to_cascade``) drives its own
        state transitions (thinking-tune, face state, hot window) once the
        transcript arrives, so there is nothing to do here. Hot-window
        re-arming happens inside :meth:`WisprBridge._stop_dictation` BEFORE
        this callback fires, so we don't double-arm it.

        When ``captured`` is False the wake handler has already started the
        thinking tune and put the face into LISTENING, but no transcript will
        ever arrive to clear them — so we stop the tune (which also resets the
        face to IDLE) and surface a visible notice so the failure isn't
        silent. We deliberately do NOT speak via TTS here to avoid noise.
        """
        if captured:
            return None

        debug_log(
            f"wispr dictation produced no transcript (reason={reason})",
            "voice",
        )
        try:
            if reason == "off":
                print(
                    "  🔇 Clipboard capture is off (pyperclip not installed) — "
                    "no transcript captured.",
                    flush=True,
                )
            else:
                print("  🔇 Didn't catch that (no transcript).", flush=True)
        except Exception:
            pass
        # Tear down the stuck thinking tune + reset the face to IDLE.
        self._stop_thinking_tune()
        return None

    def _on_wispr_unavailable(self) -> None:
        """Called from the bridge when a dictation START could not be confirmed
        to have put Wispr Flow into recording (closed-loop only).

        The wake handler already started the thinking tune and set the face to
        LISTENING, but Wispr never started, so no transcript will arrive. Tear
        the UI back down and surface an honest notice instead of a permanent
        false "listening". No TTS, to avoid noise."""
        debug_log(
            "wispr start unconfirmed — Wispr Flow did not begin recording",
            "voice",
        )
        try:
            print(
                "  🔇 Wispr Flow did not start recording. Check that its "
                "hands-free shortcut matches wispr_hands_free_combo.",
                flush=True,
            )
        except Exception:
            pass
        self._stop_thinking_tune()
        return None

    def _on_playback_ended(self) -> None:
        """Called when TTS playback finishes naturally (not on interrupt).

        Opens the Wispr hot window so the user can follow up without
        re-saying "Hey Jarvis". Idempotent — the bridge clamps repeat
        calls inside :meth:`WisprBridge.enter_hot_window`.
        """
        if self._stt_backend == "wispr" and self._wispr_bridge is not None:
            try:
                self._wispr_bridge.enter_hot_window()
            except Exception as e:
                debug_log(f"enter_hot_window failed: {e!r}", "voice")
        # Always clear the speaking flag — even if hot-window opening
        # raised, we don't want to leave the bridge thinking JARVIS is
        # still speaking. The bridge route the next stop-keyword to
        # on_transcription instead of on_stop, which is the safe default.
        self._set_bridge_speaking(False)

    def _handle_wispr_stop(self) -> None:
        """Stop pattern detected by Wispr bridge while TTS was playing.

        Fired from :meth:`WisprBridge._dispatch_transcription` BEFORE the
        regular ``on_transcription`` callback so the in-flight TTS is torn
        down as fast as possible. We piggy-back on the existing
        :meth:`reset_everything` path which already interrupts TTS,
        cancels in-flight LLM work, and clears the dialogue/hot-window
        state. Safe to call from any thread.
        """
        try:
            self.reset_everything()
        except Exception as e:
            debug_log(f"_handle_wispr_stop failed: {e!r}", "voice")

    def _set_bridge_speaking(self, speaking: bool) -> None:
        """Forward TTS playback start/end to the Wispr bridge.

        Wraps :meth:`WisprBridge.set_speaking` so call sites in TTS
        callbacks don't need to repeat the backend/None checks. No-op on
        the Whisper backend.
        """
        if self._stt_backend == "wispr" and self._wispr_bridge is not None:
            try:
                self._wispr_bridge.set_speaking(bool(speaking))
            except Exception as e:
                debug_log(f"set_speaking({speaking}) failed: {e!r}", "voice")

    def _dispatch_wispr_transcript_to_cascade(self, text: str) -> None:
        """Inject a Wispr transcript into the same cascade Whisper uses.

        The Whisper path lands at ``_process_transcript(text, energy,
        start, end)`` (called from ``_finalize_utterance``). We replicate
        that call here with neutral defaults for the audio-level fields
        Wispr doesn't have access to:

          - ``utterance_energy``: 0.0 — used only by echo detection,
            and the openWakeWord wake-gating in the bridge gives us a
            much stronger directed-speech signal than energy ever
            could.
          - ``utterance_start_time`` / ``utterance_end_time``:
            ``now`` and ``now`` — used for transcript-buffer ordering
            and hot-window timing checks. Since Wispr's wake-word
            gating already happened, the post-TTS hot window math is
            secondary; setting both to ``now`` means the utterance is
            treated as "just finished" which is accurate.

        Adds the transcript to the rolling transcript buffer so the
        intent judge has context (matches what _finalize_utterance does).
        """
        now = time.time()

        # Add to the rolling transcript buffer so the legacy judge (and
        # any cascade tier that consults context) sees the new utterance.
        try:
            is_during_tts = bool(self.tts is not None and self.tts.is_speaking())
            self._transcript_buffer.add(
                text=text,
                start_time=now,
                end_time=now,
                energy=0.0,
                is_during_tts=is_during_tts,
            )
        except Exception as e:
            debug_log(f"transcript buffer add failed (non-fatal): {e}", "voice")

        # Reset the "first utterance" flag so the visual separator
        # behaves like the Whisper path.
        separator = "" if self._first_utterance else f"\n{'─' * 50}"
        self._first_utterance = False
        print(f"{separator}\n📝 Heard (Wispr): \"{text}\"", flush=True)

        # The cascade entry point. _process_transcript handles:
        #   - Tier 0 fast-path SHORT-CIRCUIT
        #   - Tier 1 (heuristic) and Tier 2 (fused intent) cascade
        #   - Legacy intent_judge fallback
        #   - Hot-window / echo / wake-word logic
        #   - Dispatch via _dispatch_query → reply.engine
        # Energy is set to 0.0 (we have no raw audio); timestamps are
        # both `now` (transcript "just arrived"). source="wispr" tells
        # _process_transcript to (a) synthesise a wake_timestamp (since
        # openWakeWord already validated the wake out-of-band — the text
        # never contains the wake word for the in-text gate to find),
        # and (b) flip `_wispr_current_source` so `_start_collection`
        # dispatches immediately instead of waiting for a silence-timeout
        # finalize that would never fire (Wispr already gave us the full
        # utterance — no more partials will arrive via audio callback).
        try:
            self._process_transcript(text, 0.0, now, now, source="wispr")
        except Exception as e:
            # Per-utterance isolation — a processing exception must never
            # propagate into the bridge callback and take the listener down.
            debug_log(f"transcript processing failed (utterance dropped): {e!r}", "error")
            self._stop_thinking_tune()
            self._set_face_state_idle()
        finally:
            # Always clear, even if _process_transcript raised, so non-wispr
            # invocations (TRIGGER button, etc.) downstream behave normally.
            self._wispr_current_source = None
