from __future__ import annotations
import platform
import subprocess
import threading
import queue
import shutil
import signal
import tempfile
import os
import re
import sys
import time
import warnings
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse

import numpy as np

from ..debug import debug_log, info_log, log_state_transition

# Module-scope so the live output-device resolver (and its tests) can read
# settings fresh on each call without threading config through the engines.
# Imported lazily-safe: if config import fails at module load we fall back to a
# stub that returns an object with no tts_output_device (follow mode).
try:  # pragma: no cover - trivial import guard
    from ..config import load_settings  # type: ignore
except Exception:  # pragma: no cover
    def load_settings():  # type: ignore
        class _Empty:
            tts_output_device = None
        return _Empty()


# ============================================================================
# Piper TTS Model Configuration
# ============================================================================
# Default voice model for automatic download
# en_GB-alan-medium: Good quality, ~60MB, British English male
PIPER_DEFAULT_VOICE = "en_GB-alan-medium"
PIPER_VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"


# Path to the cross-process state file. Inlined as a module-level constant
# so the daemon's TTS worker thread does NOT need to import
# `desktop_app.face_widget` (a 1700-line PyQt6 module) just to compute this
# path. The import was triggering a Python import-lock deadlock when fired
# from a worker thread for the first time while the daemon main thread was
# concurrently doing heavy initialisation.
_JARVIS_STATE_FILE = os.path.join(tempfile.gettempdir(), "jarvis_state")


# JarvisState (string) → React state vocabulary. Used by ChatterboxTTS
# ._publish_tts_state to push live phase info to the React HUD without
# instantiating any QObject in the daemon's worker thread (which would
# deadlock — see the method's docstring).
_JARVIS_STATE_TO_REACT_VOCAB = {
    "asleep": "idle",
    "idle": "idle",
    "listening": "listening",
    "thinking": "thinking",
    "synthesizing": "thinking",
    "speaking": "speaking",
    "dictating": "listening",
    "dictation_processing": "thinking",
}


def _publish_tts_react_state(state) -> None:
    """Publish the current TTS phase to the React HUD (WebSocket) and the
    cross-process state file, WITHOUT importing desktop_app.face_widget or
    touching any QObject (importing PyQt6 from the daemon's TTS worker thread
    deadlocks on Python's import lock — the reason this was rewritten away from
    the face_widget path).

    Accepts a JarvisState enum OR a plain string ('synthesizing', 'speaking',
    'idle', ...). Used by BOTH the Piper and Chatterbox engines so neither can
    drift back to the broken path.
    """
    state_value = state.value if hasattr(state, "value") else str(state)
    debug_log(f"_publish_tts_state: {state_value}", "tts")

    # Idle guard: only fall back to idle if we are still mid-TTS
    # (speaking/synthesizing). If a follow-up already set LISTENING or the
    # reply engine set THINKING, leave that state alone — don't clobber it
    # with a late idle from a finishing TTS utterance.
    if state_value == "idle":
        try:
            with open(_JARVIS_STATE_FILE) as _f:
                _current = _f.read().strip()
            if _current and _current not in ("speaking", "synthesizing"):
                debug_log(f"_publish_tts_state: skip idle (current={_current})", "tts")
                return
        except Exception:
            pass  # no readable state file -> fail open and write idle

    try:
        with open(_JARVIS_STATE_FILE, "w") as f:
            f.write(state_value)
    except Exception as e:
        debug_log(f"state file write failed: {e!r}", "tts")
    try:
        from jarvis import api_server
        react_state = _JARVIS_STATE_TO_REACT_VOCAB.get(state_value, "idle")
        api_server.publish_state(state=react_state)
    except Exception as e:
        debug_log(f"api_server publish_state failed: {e!r}", "tts")


def _list_output_devices() -> None:
    """Print available output devices once, so the user can verify routing."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_out = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
        print("🔉 Audio output devices:", flush=True)
        for idx, dev in enumerate(devices):
            if dev.get("max_output_channels", 0) > 0:
                mark = " ← DEFAULT" if idx == default_out else ""
                print(f"    [{idx}] {dev.get('name', '?')}  ({int(dev.get('default_samplerate', 0))} Hz){mark}", flush=True)
    except Exception as e:
        print(f"🔉 Could not enumerate output devices: {e!r}", flush=True)


def _safe_mixer_init(samplerate: int) -> bool:
    """Initialize pygame.mixer ONCE per process — idempotent + correct.

    CRITICAL: must call mixer.init() with EXPLICIT args. `pre_init` is unreliable
    on Windows pygame — the user observed 2x speed because pre_init's
    `channels=1` was ignored and pygame opened a stereo mixer for mono WAVs,
    making playback twice as fast.

    Strategy:
      - If the mixer is already initialised AT THE CORRECT RATE, reuse it.
      - Otherwise quit any existing mixer and init fresh with the requested
        frequency + 1 channel + 16-bit signed PCM.
      - Mixer stays alive between speak calls (no quit-in-finally).
    """
    import pygame
    try:
        existing = pygame.mixer.get_init()
        if existing is not None:
            cur_freq, _cur_size, cur_channels = existing
            if cur_freq == int(samplerate) and cur_channels == 1:
                # Already correct — reuse.
                return True
            # Wrong format — tear down and re-init at the right rate.
            try:
                pygame.mixer.quit()
            except Exception:
                pass

        # Explicit args — pre_init has been observed silently ignoring some
        # parameters on Windows (notably channels), so we pass everything to
        # init() directly.
        pygame.mixer.init(
            frequency=int(samplerate),
            size=-16,
            channels=1,
            buffer=1024,
        )
        new_init = pygame.mixer.get_init()
        print(f"🔊 TTS mixer initialised: {new_init} (requested samplerate={samplerate})", flush=True)
        return True
    except Exception as e:
        # Real failure — surface it so the user knows.
        print(f"⚠️ TTS mixer init FAILED: {e!r}", flush=True)
        debug_log(f"pygame.mixer.init failed: {e!r}", "tts")
        return False


def _play_audio(
    wav_path: str,
    samplerate: int,
    volume: float,
    should_interrupt,
    label: str = "tts",
    duration_hint: float = 0.0,
    on_engaged: Optional[Callable[[], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
) -> tuple[bool, bool]:
    """Play a WAV file. Try sounddevice first (correct sample-rate handling on
    Windows), fall back to pygame mixer if PortAudio is unavailable.

    Returns (played_ok, interrupted). The caller controls state + callback.

    sounddevice is primary because pygame's SDL backend on Windows opens the
    output device in stereo (channels=2) regardless of the channels=1 request
    in mixer.init(). Loading a mono WAV onto that stereo mixer interleaves
    samples as if they were L/R pairs, halving the duration → 2x playback
    speed. sounddevice uses PortAudio, which reads the WAV header correctly
    and lets the OS audio API handle resampling + channel conversion.

    ``on_finished`` fires ONLY when playback completes naturally (interrupt
    path skips it — the caller knows the stream was torn down). Used by the
    listener to open the Wispr hot window the instant TTS audio ends.
    """
    sd_result = _play_via_sounddevice(
        wav_path, volume, should_interrupt, label, duration_hint, on_engaged,
        on_finished,
    )
    if sd_result is not None:
        return sd_result
    return _play_via_pygame(
        wav_path, samplerate, volume, should_interrupt, label, duration_hint,
        on_engaged, on_finished,
    )


def _build_extra_settings():
    """Return (sd.WasapiSettings(exclusive=True), wasapi_default_device_idx)
    on Windows if WASAPI HostApi is available; else (None, None).

    Tier 3.9: WASAPI exclusive mode bypasses Windows's shared mixer, dropping
    audio latency from ~20-50ms (shared, resampled) to ~3-10ms (exclusive,
    bit-perfect). When TTS is the only audio source, this is pure upside.

    Tradeoff: while exclusive mode is engaged, OTHER Windows audio is muted
    (browser, music, system sounds). Acceptable for a voice assistant — the
    user expects JARVIS to "take the floor" while speaking — but worth noting.

    IMPORTANT: WasapiSettings is only valid when the stream is routed to a
    WASAPI device. The system default output device is often on a different
    host API (MME / DirectSound), so we must explicitly select the WASAPI
    host API's default output device. Otherwise PortAudio rejects the
    extra_settings with `Incompatible host API specific stream info` (-9984).
    """
    if sys.platform != "win32":
        return None, None
    try:
        import sounddevice as sd
        hostapis = sd.query_hostapis()
        wasapi_index = next(
            (i for i, ha in enumerate(hostapis) if "wasapi" in ha["name"].lower()),
            None,
        )
        if wasapi_index is None:
            return None, None
        wasapi_default = hostapis[wasapi_index].get("default_output_device", -1)
        if wasapi_default is None or wasapi_default < 0:
            # WASAPI host API present but no default device — extra_settings
            # would still be rejected without a valid device target.
            return None, None
        return sd.WasapiSettings(exclusive=True), int(wasapi_default)
    except Exception as e:
        debug_log(f"_build_extra_settings: WASAPI unavailable ({e!r})", "tts")
        return None, None


def _resolve_output_device(spec) -> Optional[int]:
    """Resolve a `tts_output_device` config value to a sounddevice index.

    Accepts:
      - None / empty → return None (use system default)
      - int / digit string → use that index directly
      - non-digit string → case-insensitive substring match on device name;
        prefers WASAPI host API over MME/DirectSound when multiple devices
        share the same name (better quality + lower latency).

    Returns None on any failure (caller falls back to default).
    """
    if spec is None or (isinstance(spec, str) and spec.strip() == ""):
        return None
    try:
        import sounddevice as sd
        s = str(spec).strip()
        # Numeric → direct index
        if s.lstrip("-").isdigit():
            return int(s)
        # Substring match — find all output devices whose name contains spec
        needle = s.lower()
        candidates = []
        for i, dev in enumerate(sd.query_devices()):
            if dev.get("max_output_channels", 0) <= 0:
                continue
            if needle in dev.get("name", "").lower():
                ha_name = sd.query_hostapis(dev["hostapi"])["name"].lower()
                # Score: WASAPI=2, DirectSound=1, MME/WDM-KS=0 (prefer WASAPI)
                score = 2 if "wasapi" in ha_name else (1 if "directsound" in ha_name else 0)
                candidates.append((score, i, dev["name"], ha_name))
        if not candidates:
            print(f"⚠️ tts_output_device: no device matching '{spec}' — using system default",
                  flush=True)
            return None
        candidates.sort(reverse=True)  # highest score first
        score, idx, name, ha = candidates[0]
        print(f"🎯 tts_output_device='{spec}' → matched [{idx}] {name} ({ha})", flush=True)
        return idx
    except Exception as e:
        debug_log(f"_resolve_output_device({spec!r}) raised: {e!r}", "tts")
        return None


def _resolve_output_device_live() -> Optional[int]:
    """Resolve the playback output device FRESH on every call — no caching.

    This is what makes both manual device changes AND Windows-default changes
    apply LIVE (no restart):

      * If ``cfg.tts_output_device`` is set (non-empty) → match THAT name to a
        sounddevice index via ``audio_devices.match_name_to_sd_index``.
      * Else (follow mode) → read the CURRENT Windows default output name via
        ``audio_devices.get_default_output_name`` and match THAT. So unplugging
        the headphones and switching Windows to the speakers re-routes Jarvis on
        the very next utterance.

    Fail-open: any miss / error → ``None`` so playback uses PortAudio's own
    default device.

    Replaces the previous module-cached ``_get_configured_output_device`` whose
    value was pinned at first call, requiring a restart for changes to take
    effect.
    """
    try:
        from . import audio_devices
    except Exception as e:
        debug_log(f"_resolve_output_device_live: audio_devices import failed ({e!r})", "tts")
        return None
    try:
        cfg = load_settings()
        spec = getattr(cfg, "tts_output_device", None)
    except Exception:
        spec = None

    try:
        if spec is not None and str(spec).strip() != "":
            idx = audio_devices.match_name_to_sd_index(str(spec).strip(), kind="output")
            if idx is not None:
                debug_log(f"_resolve_output_device_live: configured '{spec}' → {idx}", "tts")
            return idx
        # Follow mode — track the live Windows default output.
        default_name = audio_devices.get_default_output_name()
        if not default_name:
            return None
        idx = audio_devices.match_name_to_sd_index(default_name, kind="output")
        if idx is not None:
            debug_log(
                f"_resolve_output_device_live: follow default '{default_name}' → {idx}",
                "tts",
            )
        return idx
    except Exception as e:
        debug_log(f"_resolve_output_device_live raised: {e!r}", "tts")
        return None


def _get_configured_output_device() -> Optional[int]:
    """Backward-compatible alias. Now resolves LIVE (no cache) so changes to
    the configured device or the Windows default take effect without a restart.

    Kept as a thin wrapper because external callers / older code may import this
    name; the cached module global it used to populate is gone.
    """
    return _resolve_output_device_live()


def _play_via_sounddevice(
    wav_path: str,
    volume: float,
    should_interrupt,
    label: str = "tts",
    duration_hint: float = 0.0,
    on_engaged: Optional[Callable[[], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
) -> Optional[tuple[bool, bool]]:
    """Primary playback via sounddevice + PortAudio.

    Returns (played_ok, interrupted) on success or interrupt, None when the
    backend isn't available so the caller can try pygame instead.

    Tier 3.9: on Windows, attempt WASAPI exclusive mode first for low-latency
    bit-perfect playback (~3-10ms vs ~20-50ms shared). Falls back to shared
    mode on PortAudioError (format-negotiation failure, device already owned,
    etc.). `latency='low'` + `blocksize=256` (~10.7ms at 24kHz) are passed
    through `sd.play()`'s **kwargs to the internal OutputStream so we get
    the tighter buffer in both modes.

    Known limitation: when the pygame.mixer fallback is initialised at startup
    (`_safe_mixer_init(24000)` in ChatterboxTTS.start), SDL holds an open
    handle on the *system default* output device. PortAudio's WASAPI exclusive
    open then fails with `Invalid device` (-9996) even when targeting a
    *different* device index, because WASAPI exclusive needs uncontested
    host-API access. The fallback to shared mode is automatic and keeps
    audio playing, so this is correctness-safe — but the WASAPI win only
    materialises when pygame is NOT pre-initialised. Future tier: defer
    pygame mixer init until the sounddevice path actually fails.
    """
    try:
        import soundfile as sf
        import sounddevice as sd
    except Exception as e:
        debug_log(f"sounddevice/soundfile unavailable: {e!r}", "tts")
        return None
    try:
        data, sr = sf.read(wav_path, dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)  # downmix to mono if stereo
        if abs(volume - 1.0) > 1e-3:
            data = data * float(volume)

        # Resolve the target output device FRESH (no cache) so a just-changed
        # configured device OR the live Windows default applies without a
        # restart. None → caller wants PortAudio's default.
        resolved_device = _resolve_output_device_live()

        # Try WASAPI exclusive first; fall back to shared on any PortAudio
        # error (most commonly: device already opened exclusively by another
        # process, or the requested format isn't supported in exclusive mode).
        # The device index must point at a WASAPI device for extra_settings
        # to be honored — see _build_extra_settings docstring.
        extra, wasapi_device = _build_extra_settings()
        used_mode = "shared"
        play_started = False
        # CRITICAL: WASAPI exclusive extra_settings are pinned to the WASAPI
        # DEFAULT device index. They are only valid for THAT device — passing
        # them for any other device raises PortAudio -9984. So only take the
        # exclusive path when the freshly-resolved device IS the WASAPI default
        # (or when nothing specific was resolved, i.e. "use default", which the
        # exclusive path already targets). When the user follows / pins a
        # DIFFERENT device, skip exclusive and play shared on it below.
        _exclusive_ok = (
            extra is not None
            and wasapi_device is not None
            and (resolved_device is None or resolved_device == wasapi_device)
        )
        if _exclusive_ok:
            try:
                # Exclusive mode requires the device's NATIVE sample rate
                # (Windows can't insert its mixer to resample). Query the
                # device's default rate and resample if needed. Chatterbox
                # emits 24000 Hz; typical Realtek WASAPI devices are 48000,
                # so the ratio is usually a clean 2:1.
                play_data = data
                play_sr = int(sr)
                try:
                    dev_info = sd.query_devices(wasapi_device)
                    native_sr = int(dev_info.get("default_samplerate", sr))
                except Exception:
                    native_sr = int(sr)
                if native_sr and native_sr != int(sr):
                    try:
                        from scipy.signal import resample_poly
                        from math import gcd
                        g = gcd(native_sr, int(sr)) or 1
                        up = native_sr // g
                        down = int(sr) // g
                        play_data = resample_poly(data, up, down).astype(np.float32)
                        play_sr = native_sr
                        debug_log(
                            f"WASAPI exclusive: resampled {int(sr)} -> {native_sr} "
                            f"(poly up/down={up}/{down})",
                            "tts",
                        )
                    except Exception as _re:
                        # Resample failed — let exclusive try the original
                        # rate; if PortAudio rejects we'll fall back to shared.
                        debug_log(
                            f"WASAPI exclusive: resample failed ({_re!r}); "
                            f"trying original rate {int(sr)} (likely will fail)",
                            "tts",
                        )

                sd.play(
                    play_data,
                    samplerate=play_sr,
                    device=wasapi_device,
                    extra_settings=extra,
                    latency="low",
                    blocksize=256,
                )
                used_mode = "WASAPI exclusive"
                play_started = True
                print(
                    f"🔊 TTS playing (sounddevice {used_mode}, dev={wasapi_device}, "
                    f"{play_sr} Hz, {duration_hint:.1f}s)",
                    flush=True,
                )
            except sd.PortAudioError as pae:
                # Exclusive denied (format negotiation failed, device busy,
                # etc.) — retry with shared mode below.
                print(
                    f"⚠️ WASAPI exclusive denied ({pae!r}) — falling back to shared mode",
                    flush=True,
                )
                debug_log(f"WASAPI exclusive denied: {pae!r}", "tts")
                # Make sure no half-started stream lingers.
                try:
                    sd.stop()
                except Exception:
                    pass

        if not play_started:
            # Shared mode on the freshly-resolved device (configured or the
            # live Windows default). This is also the path taken when the
            # resolved device is NOT the WASAPI default — shared mode accepts
            # any device, unlike the exclusive extra_settings above.
            # None = use system default (sd.default.device[1]).
            shared_device = resolved_device
            if shared_device is not None:
                sd.play(data, samplerate=int(sr), device=shared_device,
                        latency="low", blocksize=256)
                used_mode = f"shared dev={shared_device}"
            else:
                sd.play(data, samplerate=int(sr), latency="low", blocksize=256)
                used_mode = "shared"
            print(
                f"🔊 TTS playing (sounddevice {used_mode}, {int(sr)} Hz, {duration_hint:.1f}s)",
                flush=True,
            )

        # Fire on_engaged immediately — PortAudio startup latency is ~20-50ms
        # shared / ~3-10ms exclusive, close enough to "now" for echo-detection
        # timing.
        if on_engaged is not None:
            try:
                on_engaged()
            except Exception as e:
                debug_log(f"on_engaged callback raised: {e!r}", "tts")
        stream = sd.get_stream()
        while True:
            try:
                if stream is None or not stream.active:
                    break
            except Exception:
                break
            if should_interrupt is not None and should_interrupt.is_set():
                sd.stop()
                print(f"⏹  TTS interrupted ({label})", flush=True)
                return (True, True)
            sd.sleep(50)
        debug_log(f"sounddevice playback finished ({label}, mode={used_mode})", "tts")
        # Natural-completion hook: lets the listener open the Wispr hot
        # window the instant audio stops. Interrupt path skips this — the
        # caller already knows the stream was torn down via STOP.
        if on_finished is not None:
            try:
                on_finished()
            except Exception as e:
                debug_log(f"on_finished callback raised: {e!r}", "tts")
        return (True, False)
    except Exception as e:
        print(f"⚠️ TTS sounddevice failed ({label}): {e!r} — trying pygame", flush=True)
        debug_log(f"sounddevice playback failed: {e!r}", "tts")
        return None


def _play_via_pygame(
    wav_path: str,
    samplerate: int,
    volume: float,
    should_interrupt,
    label: str = "tts",
    duration_hint: float = 0.0,
    on_engaged: Optional[Callable[[], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
) -> tuple[bool, bool]:
    """Fallback playback via pygame.mixer (used when sounddevice is missing)."""
    import pygame
    pygame_ok = False
    try:
        if pygame.mixer.get_init() is None:
            debug_log(f"pygame mixer not init, initialising now (sr={samplerate})", "tts")
            pygame_ok = _safe_mixer_init(samplerate)
        else:
            pygame_ok = True

        if pygame_ok:
            debug_log(f"pygame load + play ({label}, {duration_hint:.1f}s)", "tts")
            try:
                pygame.mixer.music.load(wav_path)
                pygame.mixer.music.set_volume(float(volume))
                pygame.mixer.music.play()
                pygame.time.wait(80)
                if pygame.mixer.music.get_busy():
                    print(f"🔊 TTS playing (pygame fallback, {label}, {duration_hint:.1f}s)", flush=True)
                    if on_engaged is not None:
                        try:
                            on_engaged()
                        except Exception as e:
                            debug_log(f"on_engaged callback raised: {e!r}", "tts")
                    while pygame.mixer.music.get_busy():
                        if should_interrupt is not None and should_interrupt.is_set():
                            pygame.mixer.music.stop()
                            print(f"⏹  TTS interrupted ({label})", flush=True)
                            return (True, True)
                        pygame.time.wait(100)
                    # Natural-completion hook (see _play_via_sounddevice).
                    if on_finished is not None:
                        try:
                            on_finished()
                        except Exception as e:
                            debug_log(f"on_finished callback raised: {e!r}", "tts")
                    return (True, False)
                else:
                    print(f"⚠️ TTS stalled (pygame fallback, {label})", flush=True)
            except Exception as e:
                print(f"⚠️ TTS pygame error ({label}): {e!r}", flush=True)
    except Exception as e:
        print(f"⚠️ TTS pygame setup error ({label}): {e!r}", flush=True)
    return (False, False)


def _get_piper_models_dir() -> Path:
    """Get the directory for storing Piper voice models."""
    base = Path.home() / ".local" / "share" / "jarvis" / "models" / "piper"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_default_piper_model_path() -> str:
    """Get the path to the default Piper voice model."""
    return str(_get_piper_models_dir() / f"{PIPER_DEFAULT_VOICE}.onnx")


def _download_piper_voice(voice_name: str, progress_callback: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """
    Download a Piper voice model from HuggingFace.

    Args:
        voice_name: Voice name like "en_US-lessac-medium"
        progress_callback: Optional callback for progress messages

    Returns:
        Path to the downloaded model, or None if download failed
    """
    import requests

    def log(msg: str):
        if progress_callback:
            progress_callback(msg)
        debug_log(msg, "tts")

    # Parse voice name to construct URL
    # Format: {lang}_{region}-{name}-{quality}
    # Example: en_US-lessac-medium -> en/en_US/lessac/medium/en_US-lessac-medium.onnx
    parts = voice_name.split("-")
    if len(parts) < 3:
        log(f"Invalid voice name format: {voice_name}")
        return None

    lang_region = parts[0]  # e.g., "en_US"
    name = parts[1]         # e.g., "lessac"
    quality = parts[2]      # e.g., "medium"

    lang = lang_region.split("_")[0]  # e.g., "en"

    # Construct URLs
    base_path = f"{lang}/{lang_region}/{name}/{quality}/{voice_name}"
    onnx_url = f"{PIPER_VOICE_BASE_URL}/{base_path}.onnx"
    json_url = f"{PIPER_VOICE_BASE_URL}/{base_path}.onnx.json"

    # Target paths
    models_dir = _get_piper_models_dir()
    onnx_path = models_dir / f"{voice_name}.onnx"
    json_path = models_dir / f"{voice_name}.onnx.json"

    # Download with progress
    try:
        for url, target_path, desc in [
            (onnx_url, onnx_path, "model"),
            (json_url, json_path, "config"),
        ]:
            if target_path.exists():
                log(f"  {desc} already exists: {target_path.name}")
                continue

            log(f"  Downloading {desc}...")

            # Stream download with retry on rate limiting (HTTP 429)
            max_retries = 4
            response = None
            for attempt in range(max_retries + 1):
                response = requests.get(url, stream=True, timeout=60)
                try:
                    response.raise_for_status()
                    break  # Success
                except requests.exceptions.HTTPError as http_err:
                    response.close()
                    status = getattr(http_err.response, "status_code", None)
                    if status == 429 and attempt < max_retries:
                        wait = 2 ** (attempt + 1)
                        log(f"  ⏳ Rate limited by HuggingFace, retrying in {wait}s ({attempt + 1}/{max_retries})...")
                        time.sleep(wait)
                        continue
                    raise  # Non-429 or retries exhausted

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            # Write to temp file first, then rename (atomic)
            temp_path = target_path.with_suffix(".tmp")
            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0 and progress_callback:
                        pct = (downloaded / total_size) * 100
                        if downloaded % (1024 * 1024) < 8192:  # Log every ~1MB
                            log(f"  Downloading {desc}... {pct:.0f}%")

            # Rename temp to final
            temp_path.rename(target_path)
            log(f"  Downloaded {desc}: {target_path.name}")

        return str(onnx_path)

    except requests.RequestException as e:
        log(f"  Download failed: {e}")
        # Clean up partial downloads
        for p in [onnx_path, json_path]:
            tmp = p.with_suffix(".tmp")
            if tmp.exists():
                tmp.unlink()
        return None
    except Exception as e:
        log(f"  Download error: {e}")
        return None


# Default speaking rates for TTS estimation
DEFAULT_WPM = 200  # Default rate used in config (words per minute)
AUDIO_BUFFER_DELAY_SEC = 0.5  # Extra delay for audio buffer latency


def _estimate_tts_duration(text: str, wpm: int) -> float:
    """
    Estimate how long TTS audio will take to play.

    Args:
        text: The text being spoken
        wpm: Words per minute rate

    Returns:
        Estimated duration in seconds
    """
    # Count words (simple split on whitespace)
    words = len(text.split())

    # Calculate duration based on WPM
    if wpm <= 0:
        wpm = DEFAULT_WPM

    duration_sec = (words / wpm) * 60.0

    # Add buffer for audio latency
    return duration_sec + AUDIO_BUFFER_DELAY_SEC


def _extract_domain_description(url: str) -> tuple[str, bool]:
    """
    Extract a readable domain description from a URL.

    Returns:
        Tuple of (domain_description, is_homepage)
        - domain_description: e.g., "google.com"
        - is_homepage: True if URL points to homepage (no meaningful path)
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]

        # Remove common prefixes
        if domain.startswith('www.'):
            domain = domain[4:]

        # Check if it's a homepage (no path or just /)
        path = parsed.path.rstrip('/')
        is_homepage = not path or path == ''

        return domain, is_homepage
    except Exception:
        return url, True


_NUMBERED_MARKER_RE = re.compile(r"^\s*(\d+)[.)]\s+")


def _strip_markdown_for_speech(text: str) -> str:
    """Strip markdown formatting so TTS doesn't read syntax characters aloud.

    Small models often produce markdown (``**bold**``, bullet lists, headings)
    even when told to be conversational. Piper and similar engines read the
    syntax characters literally ("asterisk asterisk bold asterisk asterisk").
    This function removes the markup while preserving the words inside it.

    Handled:
    - Fenced code blocks ``` ```lang\\ncode\\n``` ``` → inner text only
    - Inline code ``` `x` ``` → ``x``
    - Bold ``**x**`` / ``__x__`` → ``x``
    - Italic ``*x*`` / ``_x_`` → ``x``
    - Strikethrough ``~~x~~`` → ``x``
    - Word-internal underscores (e.g. ``my_function``) are preserved so
      identifiers aren't mangled into concatenated words.
    - HTML tags ``<b>x</b>`` → ``x``
    - Leading heading markers ``# ``, ``## `` … at line start → removed
    - Setext heading underlines (``===`` / ``---`` beneath a title line) → removed
    - Leading blockquote markers ``> `` at line start → removed
    - Leading bullet markers ``- ``, ``* ``, ``+ `` at line start → removed
    - Leading numbered-list markers ``1. ``, ``2) ``: stripped only when the
      line is part of a real list — detected as ≥2 adjacent lines whose
      numbers are each ≤ 99. Prevents eating prose like "2024. The year...".
    """
    if not text:
        return text

    # Fenced code blocks: keep inner content, drop fences and language tag.
    text = re.sub(r"```[a-zA-Z0-9_-]*\n?([\s\S]*?)```", r"\1", text)

    # Inline code: keep inner content.
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Bold / strikethrough (before italic so the double-char form matches first).
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)

    # Italic with asterisk: single * not flanked by another *.
    text = re.sub(r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)", r"\1", text)
    # Italic with underscore: require word boundaries so we don't eat
    # underscores inside identifiers like "some_variable_name".
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"\1", text)

    # HTML tags: drop tags, keep inner text. Safe here because TTS input is
    # assistant prose, not code discussing literal inequalities like "x<3".
    text = re.sub(r"<[^>]+>", "", text)

    # True list detection: a numbered line is a list item only if it's part
    # of a contiguous group of ≥2 such lines whose numbers are each ≤ 99.
    # This preserves prose like "2024. The year..." and "2023.\n2024." pairs
    # that are clearly years, not list markers.
    lines = text.split("\n")
    numbers = [
        int(m.group(1)) if (m := _NUMBERED_MARKER_RE.match(line)) else None
        for line in lines
    ]
    strip_numbered = [False] * len(lines)
    run_start: Optional[int] = None
    for i in range(len(lines) + 1):
        in_run = i < len(lines) and numbers[i] is not None and numbers[i] <= 99
        if in_run and run_start is None:
            run_start = i
        elif not in_run and run_start is not None:
            if i - run_start >= 2:
                for k in range(run_start, i):
                    strip_numbered[k] = True
            run_start = None

    cleaned: list[str] = []
    for i, line in enumerate(lines):
        # Setext heading underline: a line of only = or - (≥3 chars) directly
        # beneath a non-empty title line. Drop the underline; keep the title.
        if (
            i > 0
            and lines[i - 1].strip()
            and re.fullmatch(r"\s*(=+|-+)\s*", line)
            and len(line.strip()) >= 3
        ):
            continue
        stripped = re.sub(r"^\s*#{1,6}\s+", "", line)        # headings
        stripped = re.sub(r"^\s*>\s?", "", stripped)         # blockquotes
        stripped = re.sub(r"^\s*[-*+]\s+", "", stripped)     # bullets
        if strip_numbered[i]:
            stripped = _NUMBERED_MARKER_RE.sub("", stripped)
        cleaned.append(stripped)
    return "\n".join(cleaned)


def _preprocess_for_speech(text: str) -> str:
    """
    Preprocess text for TTS by converting links to readable descriptions and
    stripping markdown formatting.

    Handles:
    - Markdown links: [text](url) → "Link to domain.com with the text 'text'" or
      "Link to a page under domain.com with the text 'text'"
    - Raw URLs: https://domain.com → "domain.com homepage" or
      https://domain.com/path → "a page under domain.com"
    - Markdown formatting (bold, italic, code, headings, lists) → stripped so
      TTS engines don't read syntax characters (``**``, ``#``, ``-``) aloud.
    """
    # Pattern for markdown links: [text](url)
    markdown_link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'

    def replace_markdown_link(match: re.Match) -> str:
        link_text = match.group(1)
        url = match.group(2)
        domain, is_homepage = _extract_domain_description(url)

        if is_homepage:
            return f"Link to {domain} homepage with the text '{link_text}'"
        else:
            return f"Link to a page under {domain} with the text '{link_text}'"

    # Replace markdown links first
    result = re.sub(markdown_link_pattern, replace_markdown_link, text)

    # Pattern for raw URLs (not already processed as markdown)
    # Matches http://, https://, and www. prefixed URLs
    raw_url_pattern = r'(?<!\()(https?://[^\s<>\[\]()]+|www\.[^\s<>\[\]()]+)(?!\))'

    def replace_raw_url(match: re.Match) -> str:
        url = match.group(1)
        # Ensure URL has protocol for parsing
        if url.startswith('www.'):
            url = 'https://' + url
        domain, is_homepage = _extract_domain_description(url)

        if is_homepage:
            return f"{domain} homepage"
        else:
            return f"a page under {domain}"

    # Replace raw URLs
    result = re.sub(raw_url_pattern, replace_raw_url, result)

    # Strip any remaining markdown so TTS doesn't read syntax aloud.
    result = _strip_markdown_for_speech(result)

    return result


# Sentence-final punctuation, EL + EN aware. Note that Greek's question mark is
# the SAME code point as the Latin semicolon (U+003B ';'), so a single class
# covers both. '·' (U+0387, Greek ano teleia) is a sentence-level separator.
_SENTENCE_TERMINATORS = ".!?;·"

# Minimal abbreviation set whose trailing '.' must NOT end a sentence. Kept
# deliberately tiny and language-agnostic-ish (these forms are borrowed across
# many European languages). This is a pragmatic guard, not an attempt to model
# every abbreviation — splitting is fail-open, so a missed split just means one
# slightly longer synthesis chunk, never wrong audio.
_NON_TERMINAL_ABBREVIATIONS = frozenset(
    {
        "e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "prof", "st",
        "no", "fig", "al", "approx", "cf", "p.s",
    }
)


def _next_nonspace_char(text: str, start: int) -> str:
    """Return the first non-space char at/after ``start``, or '' at end."""
    j = start
    n = len(text)
    while j < n and text[j].isspace():
        j += 1
    return text[j] if j < n else ""


def _ends_with_abbreviation(accumulated: str) -> bool:
    """True if ``accumulated`` (ending just before/at a '.') closes a known
    abbreviation such as ``etc``, ``vs`` or the dotted ``e.g`` / ``i.e``.

    Compares the trailing whitespace-delimited token, normalised to lower-case
    with any trailing dots removed, against ``_NON_TERMINAL_ABBREVIATIONS``.
    """
    token = re.split(r"\s", accumulated)[-1] if accumulated else ""
    core = token.rstrip(".").lower()
    return core in _NON_TERMINAL_ABBREVIATIONS


def _split_into_sentences(text: str) -> list[str]:
    """Split already-preprocessed TTS text into sentences, EL + EN aware.

    Splits on sentence-final punctuation (``. ! ? ;`` and the Greek ``;``/``·``)
    and on newlines, but deliberately does NOT split inside:
      * decimals — ``3.5`` stays intact (digit on both sides of the dot),
      * ellipses — ``...`` is treated as one terminator, no empty fragments,
      * common abbreviations — ``e.g.``, ``etc.``, ``i.e.`` etc.

    The terminator stays attached to the sentence it ends. Blank fragments are
    dropped. Operates on the output of ``_preprocess_for_speech`` /
    ``_strip_markdown_for_speech`` so URLs and markdown are already handled.

    Fail-open: any uncertainty resolves towards NOT splitting, so the worst case
    is a slightly larger synthesis chunk, never mangled or reordered audio.
    """
    if not text or not text.strip():
        return []

    sentences: list[str] = []
    buf: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        buf.append(ch)

        if ch == "\n":
            # Hard boundary — newlines always separate sentences.
            sentence = "".join(buf).strip()
            if sentence:
                sentences.append(sentence)
            buf = []
            i += 1
            continue

        if ch in _SENTENCE_TERMINATORS:
            if ch == ".":
                prev_ch = text[i - 1] if i > 0 else ""
                next_ch = text[i + 1] if i + 1 < n else ""
                # Decimal: digit on both sides → not a terminator (e.g. 3.5).
                if prev_ch.isdigit() and next_ch.isdigit():
                    i += 1
                    continue
                # Ellipsis / dot-run (2+ dots): swallow the whole run and never
                # treat it as a boundary — keeps "Well... I suppose" together.
                if next_ch == ".":
                    while i + 1 < n and text[i + 1] == ".":
                        buf.append(text[i + 1])
                        i += 1
                    i += 1
                    continue
                # Abbreviation guard: the trailing dotted word is a known
                # abbreviation (e.g. "etc.", "vs.", "e.g."). Catches the case
                # where an abbreviation is followed by a capitalised word, which
                # the next-char heuristic below would misread as a boundary.
                if _ends_with_abbreviation("".join(buf)):
                    i += 1
                    continue
                # Sentence-continuation heuristic (language-agnostic): a real
                # sentence boundary is followed by end-of-text or an
                # upper/title-case char. If the next non-space char is
                # lower-case, this dot is mid-sentence (abbreviation, initial,
                # filename) → do not split. Greek upper-case is handled by
                # str.isupper(), so no per-language list is needed.
                nxt = _next_nonspace_char(text, i + 1)
                if nxt and not (nxt.isupper() or nxt.istitle()):
                    i += 1
                    continue

            # Real sentence end — flush the accumulated buffer.
            sentence = "".join(buf).strip()
            if sentence:
                sentences.append(sentence)
            buf = []
            i += 1
            continue

        i += 1

    tail = "".join(buf).strip()
    if tail:
        sentences.append(tail)

    return sentences


# Cached result of reading cfg.tts_streaming_enabled, mirroring
# _get_configured_output_device's lazy-load-once pattern so the TTS worker
# thread never repeatedly hits disk. Tests patch _get_streaming_enabled
# directly, so they bypass the cache entirely.
_STREAMING_ENABLED_CACHED = None


def _get_streaming_enabled() -> bool:
    """Read cfg.tts_streaming_enabled (default True). Cached after first call.

    Read lazily here rather than threaded through PiperTTS.__init__ /
    create_tts_engine so sentence streaming stays fully contained in this
    module and needs no changes to the daemon or listener.
    """
    global _STREAMING_ENABLED_CACHED
    if _STREAMING_ENABLED_CACHED is not None:
        return _STREAMING_ENABLED_CACHED
    enabled = True
    try:
        from ..config import load_settings
        cfg = load_settings()
        enabled = bool(getattr(cfg, "tts_streaming_enabled", True))
    except Exception as e:
        debug_log(f"_get_streaming_enabled: defaulting True ({e!r})", "tts")
        enabled = True
    _STREAMING_ENABLED_CACHED = enabled
    return _STREAMING_ENABLED_CACHED


class ChatterboxTTS:
    """Experimental TTS implementation using Resemble AI's Chatterbox model."""

    def __init__(self, enabled: bool = True, voice: Optional[str] = None, rate: Optional[int] = None,
                 device: str = "cuda", audio_prompt_path: Optional[str] = None,
                 exaggeration: float = 0.5, cfg_weight: float = 0.5) -> None:
        self.enabled = enabled
        self.voice = voice  # Not used in Chatterbox, kept for interface compatibility
        self.rate = rate    # Not directly supported in Chatterbox, kept for interface compatibility
        self.device = device
        self.audio_prompt_path = audio_prompt_path
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight

        # Threading and queue setup (same as TextToSpeech)
        self._q: queue.Queue[str] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._is_speaking = threading.Event()
        self._last_spoken_text: str = ""
        self._completion_callback: Optional[Callable[[], None]] = None
        self._duration_callback: Optional[Callable[[float], None]] = None
        # Fires when audio playback ACTUALLY engages (after pygame.get_busy
        # flips True), NOT when speak() is called. Used by the echo detector
        # to reset its `_tts_start_time` to the real play-start time —
        # otherwise it computes which part of the TTS text is "currently
        # playing" using a timestamp from ~5-7 seconds before audio actually
        # began (because synthesis + buffer fill is slow), and false-positives
        # the echo check.
        self._playback_started_callback: Optional[Callable[[], None]] = None
        # Fires once playback finishes naturally (NOT on interrupt). Used by
        # the Wispr listener to open the hot window the instant audio ends,
        # so the user can follow up without re-saying "Hey Jarvis".
        self._playback_ended_callback: Optional[Callable[[], None]] = None
        self._should_interrupt = threading.Event()

        # Chatterbox model (eagerly loaded during initialization)
        self._model = None
        self._model_error = None
        # Tier 1.2: reduced max_new_tokens for the t3 sampling loop.
        # Resolved lazily in _initialize_with_logging() from cfg.tts_chatterbox_steps (default 300).
        self._steps: int = 300
        # Lazy initialization flags
        self._initialized = False
        self._init_lock = threading.Lock()

    def _initialize_with_logging(self) -> None:
        """Initialize Chatterbox with proper logging."""
        import sys

        print("🔧 [TTS] Initializing Chatterbox neural voice synthesis...", file=sys.stderr)

        try:
            print("📦 [TTS] Loading Chatterbox dependencies...", file=sys.stderr)

            # Import dependencies
            import torch
            import torchaudio as ta
            from chatterbox.tts import ChatterboxTTS as ChatterboxModel

            # Check device availability
            if self.device == "cuda" and not torch.cuda.is_available():
                print("⚠️  [TTS] CUDA requested but not available, falling back to CPU", file=sys.stderr)
                actual_device = "cpu"
            else:
                actual_device = self.device

            print(f"🚀 [TTS] Loading Chatterbox model on {actual_device.upper()}...", file=sys.stderr)

            # Load model with proper device specification
            self._model = ChatterboxModel.from_pretrained(device=actual_device)

            # Tier 1.2: resolve max-new-tokens override from config (default 300).
            try:
                from ..config import load_settings as _ls
                _s = _ls()
                self._steps = int(getattr(_s, "tts_chatterbox_steps", 300))
                print(f"⏩ Chatterbox: max_new_tokens override = {self._steps}", file=sys.stderr, flush=True)
            except Exception as _e:
                print(f"⚠️  Chatterbox steps override failed (default=300): {_e!r}", file=sys.stderr, flush=True)
                self._steps = 300

            # Tier 1.2: BF16 cast on t3 — ~2× speed, ~50% VRAM.
            try:
                if torch.cuda.is_available() and hasattr(self._model, "t3"):
                    self._model.t3.to(dtype=torch.bfloat16)
                    if getattr(self._model, "conds", None) is not None and hasattr(self._model.conds, "t3"):
                        self._model.conds.t3.to(dtype=torch.bfloat16)
                    print("⏩ Chatterbox: t3 cast to bfloat16", file=sys.stderr, flush=True)
            except Exception as _e:
                print(f"⚠️  Chatterbox BF16 cast skipped: {_e!r}", file=sys.stderr, flush=True)

            # Tier 1.2: torch.compile(cudagraphs) on the per-step decoder.
            # NOTE: this entry point lives in rsxdalv/chatterbox fast fork; not in upstream
            # ResembleAI build. On upstream we log a warning and skip gracefully.
            try:
                if torch.cuda.is_available() and hasattr(self._model, "t3"):
                    target = getattr(self._model.t3, "_step_compilation_target", None)
                    if target is not None and callable(target):
                        self._model.t3._step_compilation_target = torch.compile(
                            target, fullgraph=True, backend="cudagraphs"
                        )
                        print("⏩ Chatterbox: torch.compile(cudagraphs) wrapped on _step_compilation_target",
                              file=sys.stderr, flush=True)
                    else:
                        print("⚠️  Chatterbox torch.compile: _step_compilation_target not found "
                              "(upstream resemble-ai build, not rsxdalv/chatterbox fast fork)",
                              file=sys.stderr, flush=True)
            except Exception as _e:
                print(f"⚠️  Chatterbox torch.compile skipped: {_e!r}", file=sys.stderr, flush=True)

            # Tier 1.2: monkey-patch t3.inference to (a) clamp max_new_tokens to configured value
            # and (b) coerce t3_cond to the t3 weights' dtype (BF16) because prepare_conditionals()
            # rebuilds self.conds as fp32 on every generate() call with audio_prompt_path, which
            # would otherwise cause a dtype mismatch against the BF16-cast t3 weights.
            # The upstream chatterbox/tts.py:249 hardcodes max_new_tokens=1000 with a TODO;
            # this wraps it so we can configure it without touching the library.
            try:
                if hasattr(self._model, "t3") and hasattr(self._model.t3, "inference"):
                    _orig_inference = self._model.t3.inference
                    _steps_capture = self._steps
                    _t3_module = self._model.t3
                    def _patched_inference(*args, **kwargs):
                        kwargs["max_new_tokens"] = _steps_capture
                        # Coerce t3_cond to the t3 module's weight dtype to avoid Float/BFloat16 mismatch.
                        try:
                            _wparam = next(_t3_module.parameters(), None)
                            _target_dtype = _wparam.dtype if _wparam is not None else None
                            _cond = kwargs.get("t3_cond")
                            if _cond is not None and _target_dtype is not None:
                                kwargs["t3_cond"] = _cond.to(dtype=_target_dtype)
                        except Exception:
                            pass
                        return _orig_inference(*args, **kwargs)
                    self._model.t3.inference = _patched_inference
                    print(f"⏩ Chatterbox: t3.inference wrapped to max_new_tokens={self._steps} (with dtype coerce)",
                          file=sys.stderr, flush=True)
            except Exception as _e:
                print(f"⚠️  Chatterbox steps patch skipped: {_e!r}", file=sys.stderr, flush=True)

            print("✅ [TTS] Chatterbox neural voice synthesis ready!", file=sys.stderr)

        except ImportError as e:
            self._model_error = f"Chatterbox dependencies not available: {e}"
            print(f"❌ [TTS] Missing dependencies: {self._model_error}", file=sys.stderr)
            warnings.warn(f"ChatterboxTTS initialization failed: {self._model_error}")
        except Exception as e:
            self._model_error = f"Failed to load Chatterbox model: {e}"
            print(f"❌ [TTS] Model loading failed: {self._model_error}", file=sys.stderr)
            warnings.warn(f"ChatterboxTTS initialization failed: {self._model_error}")

    def _ensure_initialized(self) -> None:
        """Initialize heavy dependencies only once, when actually needed."""
        if self._initialized or not self.enabled:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._initialize_with_logging()
            self._initialized = True

    def _ensure_model(self) -> bool:
        """Check if Chatterbox model is loaded. Returns True if successful."""
        # Ensure lazy initialization happens before checking model
        self._ensure_initialized()
        if self._model is not None:
            return True
        if self._model_error is not None:
            return False
        return False

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return

        # STEP 1: list output devices + init pygame.mixer FIRST so the user
        # sees these logs even if Chatterbox model loading later hangs/takes
        # forever. Windows SDL audio init from a worker thread is unreliable —
        # doing it here on the caller's thread (daemon main) is required.
        print("⏩ TTS phase: pre-init (enumerate devices)", flush=True)
        try:
            _list_output_devices()  # one-shot diagnostic
        except Exception as e:
            print(f"⚠️ device enumeration failed: {e!r}", flush=True)

        # IMPORTANT: pygame.mixer.init is DEFERRED to lazy-init inside
        # _play_via_pygame (only fires if sounddevice fails). The previous
        # eager init grabbed the system default device handle via SDL,
        # which then prevented sounddevice from successfully routing audio
        # to it (shared-mode "play" succeeded but produced silence) AND
        # blocked WASAPI exclusive mode with "-9996 Invalid device".
        # By deferring, sounddevice owns the device unless it fails — at
        # which point pygame falls back, by which time sounddevice has
        # already released its handle.
        print("⏩ TTS phase: pygame mixer init DEFERRED (lazy on sounddevice failure)", flush=True)

        # STEP 2: load Chatterbox model. This is the slow part on first run
        # (can take 30-60s). Bracket it with timing logs so the user sees
        # progress instead of silence.
        print("⏩ TTS phase: loading Chatterbox model (this may take 30-60s on first run)...", flush=True)
        _model_t0 = time.time()
        try:
            self._ensure_initialized()
            print(f"⏩ TTS phase: Chatterbox model ready in {time.time()-_model_t0:.1f}s", flush=True)
        except Exception as e:
            print(f"❌ TTS phase: Chatterbox model load FAILED after {time.time()-_model_t0:.1f}s: {e!r}", flush=True)
            debug_log(f"chatterbox load failed: {e!r}", "tts")
            # Continue anyway — worker thread will surface the error when it
            # tries to use the model.

        # STEP 3: start the worker thread. From here on, all TTS work is
        # asynchronous; speak() just enqueues text.
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("⏩ TTS phase: worker thread started — ready to speak", flush=True)

    def stop(self) -> None:
        if self._thread is None:
            return
        # Ensure any active speech is interrupted immediately
        try:
            self.interrupt()
        except Exception:
            pass
        self._stop.set()
        try:
            self._q.put_nowait("")
        except Exception:
            pass
        self._thread.join(timeout=2.0)
        self._thread = None
        self._stop.clear()
        # Release the audio device only at engine shutdown — NOT between
        # individual speak calls. _safe_mixer_init is idempotent and reuses
        # the existing mixer if already initialised.
        try:
            import pygame
            if pygame.mixer.get_init() is not None:
                pygame.mixer.quit()
        except Exception:
            pass

    def speak(self, text: str, completion_callback: Optional[Callable[[], None]] = None,
              duration_callback: Optional[Callable[[float], None]] = None,
              playback_started_callback: Optional[Callable[[], None]] = None,
              playback_ended_callback: Optional[Callable[[], None]] = None,
              volume: float = 1.0) -> None:
        if not self.enabled or not text.strip():
            return
        # Lazy start the worker thread and lazy init on first speak
        if self._thread is None:
            self.start()
        self._completion_callback = completion_callback
        self._duration_callback = duration_callback
        self._playback_started_callback = playback_started_callback
        self._playback_ended_callback = playback_ended_callback
        self._speak_volume = float(np.clip(volume, 0.0, 2.0))
        # Preprocess text for speech (convert links to readable descriptions)
        processed_text = _preprocess_for_speech(text)
        try:
            self._q.put_nowait(processed_text)
        except Exception:
            pass

    def interrupt(self) -> None:
        """Stop current speech immediately"""
        self._should_interrupt.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if not text:
                continue
            try:
                self._speak_once(text)
            except Exception:
                continue

    def _speak_once(self, text: str) -> None:
        # Sentence-by-sentence streaming (tts_streaming_enabled) is implemented
        # for Piper ONLY — see PiperTTS._speak_once. Chatterbox stays on the
        # whole-text path: its generate() returns a single tensor for the full
        # text, its TTS cache is keyed on the full text, and the per-call BF16 /
        # dtype patching makes per-sentence invocation risky for no clear win
        # (Chatterbox synthesis dominates wall-clock regardless). So Chatterbox
        # ignores the streaming flag and synthesises the reply in one shot.
        #
        # Diagnostic tracer prints (debug_log so they don't spam the Live Logs
        # UI; can be enabled selectively if a regression appears).
        debug_log(f"_speak_once entered (text_len={len(text)})", "tts")
        self._is_speaking.set()
        self._last_spoken_text = text
        self._should_interrupt.clear()
        interrupted = False

        # Signal synthesizing state to face widget (audio not playing yet).
        # _publish_tts_state is QObject-free AND face_widget-import-free.
        self._publish_tts_state("synthesizing")

        try:
            # Check if model is available
            if not self._ensure_model():
                warnings.warn("Chatterbox TTS not available, skipping speech synthesis")
                print("⚠️ TTS: Chatterbox model unavailable, skipping", flush=True)
                return

            # Generate audio using Chatterbox
            import tempfile
            import pygame
            import os

            # --- TTS cache lookup -------------------------------------------------
            from .tts_cache import get_cache
            _cache = get_cache()
            _cached_wav = _cache.lookup(
                text, self.audio_prompt_path, self.exaggeration, self.cfg_weight
            )
            debug_log(f"cache lookup done (hit={_cached_wav is not None})", "tts")
            if _cached_wav is not None:
                debug_log(f"TTS cache HIT (text='{text[:40]}...')", "tts")
                # Compute duration via soundfile (no model invocation needed)
                import soundfile as _sf
                _info = _sf.info(str(_cached_wav))
                exact_duration = float(_info.frames) / float(_info.samplerate)
                if self._duration_callback is not None:
                    try:
                        self._duration_callback(exact_duration)
                    except Exception as e:
                        debug_log(f"cached duration callback error: {e}", "tts")
                # Audio playback actually starts — switch to SPEAKING
                self._publish_tts_state("speaking")  # string literal — JarvisState was never imported at module scope
                played_ok, was_interrupted = _play_audio(
                    str(_cached_wav),
                    _info.samplerate,
                    self._speak_volume,
                    self._should_interrupt,
                    label="cache hit",
                    duration_hint=exact_duration,
                    on_engaged=self._playback_started_callback,
                    on_finished=self._playback_ended_callback,
                )
                if was_interrupted:
                    interrupted = True
                if not played_ok:
                    print(
                        "⚠️ TTS skipped — both pygame and sounddevice failed. "
                        "Check Windows Sound settings and default playback device.",
                        flush=True,
                    )
                return  # Done — no neural synthesis needed
            # --- end cache lookup -------------------------------------------------

            # Generate speech — suppress chatterbox's tqdm progress bar spam
            # by redirecting stderr during synthesis.
            debug_log(f"synthesis START (text='{text[:40]}...', len={len(text)})", "tts")
            _synth_t0 = time.time()
            import io
            _stderr_capture = io.StringIO()
            _orig_stderr = sys.stderr
            sys.stderr = _stderr_capture
            try:
                wav = self._model.generate(
                    text,
                    audio_prompt_path=self.audio_prompt_path,
                    exaggeration=self.exaggeration,
                    cfg_weight=self.cfg_weight
                )
            finally:
                sys.stderr = _orig_stderr
                _captured = _stderr_capture.getvalue()
                if _captured:
                    debug_log(f"Chatterbox synthesis stderr:\n{_captured}", "tts")

            # Calculate exact duration from audio samples
            exact_duration = wav.shape[-1] / self._model.sr
            _synth_elapsed = time.time() - _synth_t0
            debug_log(
                f"synthesis DONE in {_synth_elapsed:.2f}s "
                f"(audio={exact_duration:.2f}s, sr={self._model.sr})",
                "tts",
            )

            # Notify listener of exact duration for precise echo detection
            if self._duration_callback is not None:
                try:
                    self._duration_callback(exact_duration)
                except Exception as e:
                    debug_log(f"Chatterbox TTS duration callback error: {e}", "tts")

            # Save to temporary file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_path = tmp_file.name

            try:
                # Save audio
                debug_log("saving WAV...", "tts")
                import torchaudio as ta
                ta.save(tmp_path, wav, self._model.sr)

                # Cache the freshly-synthesized audio so we skip generation
                # next time the same text + voice combination is spoken.
                try:
                    _cache.store(
                        text, self.audio_prompt_path,
                        self.exaggeration, self.cfg_weight,
                        Path(tmp_path),
                    )
                except Exception as _ce:
                    debug_log(f"TTS cache store error (non-fatal): {_ce}", "tts")

                # Audio playback actually starts — switch to SPEAKING
                self._publish_tts_state("speaking")  # string literal — JarvisState was never imported at module scope
                played_ok, was_interrupted = _play_audio(
                    tmp_path,
                    self._model.sr,
                    self._speak_volume,
                    self._should_interrupt,
                    label="synthesis",
                    duration_hint=exact_duration,
                    on_engaged=self._playback_started_callback,
                    on_finished=self._playback_ended_callback,
                )
                if was_interrupted:
                    interrupted = True
                if not played_ok:
                    print(
                        "⚠️ TTS skipped — both pygame and sounddevice failed. "
                        "Check Windows Sound settings and default playback device.",
                        flush=True,
                    )
                # Fall through to inner finally for tmp-file cleanup.

            finally:
                # Only delete temp file. Do NOT pygame.mixer.quit() here —
                # the mixer stays alive between speak calls (idempotent init
                # in _safe_mixer_init). Quitting would lock the audio device
                # on Windows and silently break the next playback.
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            warnings.warn(f"Chatterbox TTS error: {e}")
        finally:
            self._is_speaking.clear()
            # Signal speaking stopped to face widget
            self._publish_tts_state("idle")  # string literal — JarvisState was never imported at module scope

            # ALWAYS fire the completion callback — even on interrupt or audio
            # failure — so the listener's hot window activates and we never
            # leave the voice pipeline stuck waiting for a TTS that never
            # completes. The callback (activate_hot_window) is idempotent and
            # handles the interrupted case safely.
            #
            # Previously this guard was `and not interrupted`, which meant a
            # STOP press during the 100ms wait loop would leave the listener
            # hung — exactly the symptom the user reported.
            if self._completion_callback is not None:
                try:
                    self._completion_callback()
                except Exception as _cb_err:
                    debug_log(f"completion_callback raised: {_cb_err!r}", "tts")
                self._completion_callback = None
            # Reset the playback-ended hook so it doesn't leak into a
            # subsequent speak() call that doesn't supply one. The natural
            # fire-site is inside _play_audio; this only clears the slot.
            self._playback_ended_callback = None
            # Same for the engaged hook for symmetry.
            self._playback_started_callback = None

    def _publish_tts_state(self, state: "JarvisState") -> None:
        """Publish TTS phase cross-process WITHOUT touching any QObject
        AND WITHOUT importing `desktop_app.face_widget`.

        Previously this method imported `_get_jarvis_state_file` from
        `desktop_app.face_widget`. That import — fired from the TTS worker
        thread on first speak — pulled in a 1700-line PyQt6 module while
        the daemon main thread was concurrently doing heavy work. Python's
        import lock deadlocks in that scenario. The diagnostic prints below
        will fire even on cold start, so any future hang is visible.
        """
        _publish_tts_react_state(state)

    # Loopback guard helpers (same interface as TextToSpeech)
    def is_speaking(self) -> bool:
        return self._is_speaking.is_set()

    def get_last_spoken_text(self) -> str:
        return self._last_spoken_text


class PiperTTS:
    """TTS implementation using Piper (local neural TTS with exact duration).

    Piper generates actual audio samples, enabling precise duration calculation
    instead of WPM-based estimation. Uses sounddevice for streaming playback
    with responsive interruption support.
    """

    def __init__(
        self,
        enabled: bool = True,
        voice: Optional[str] = None,
        rate: Optional[int] = None,
        model_path: Optional[str] = None,
        speaker: Optional[int] = None,
        length_scale: float = 1.0,
        noise_scale: float = 0.667,
        noise_w: float = 0.8,
        sentence_silence: float = 0.2,
    ) -> None:
        self.enabled = enabled
        self.voice = voice  # Not used in Piper, kept for interface compatibility
        self.rate = rate    # Not directly supported, use length_scale instead
        self.model_path = model_path
        self.speaker = speaker
        self.length_scale = length_scale
        self.noise_scale = noise_scale
        self.noise_w = noise_w
        self.sentence_silence = sentence_silence

        # Threading and queue setup (same pattern as other TTS engines)
        self._q: queue.Queue[str] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._is_speaking = threading.Event()
        self._last_spoken_text: str = ""
        self._completion_callback: Optional[Callable[[], None]] = None
        self._duration_callback: Optional[Callable[[float], None]] = None
        self._playback_started_callback: Optional[Callable[[], None]] = None
        self._playback_ended_callback: Optional[Callable[[], None]] = None
        self._should_interrupt = threading.Event()
        self._speak_volume = 1.0

        # Piper voice (lazy loaded)
        self._voice = None
        self._sample_rate: int = 22050  # Piper default, updated on model load
        self._initialized = False
        self._init_lock = threading.Lock()
        self._init_error: Optional[str] = None

        # Audio stream for interruption
        self._audio_stream = None
        self._audio_lock = threading.Lock()

    def _ensure_initialized(self) -> bool:
        """Initialize Piper voice model. Returns True if successful.

        If no model is configured, automatically downloads the default voice.
        """
        if self._initialized:
            return self._voice is not None
        if not self.enabled:
            return False

        with self._init_lock:
            if self._initialized:
                return self._voice is not None

            try:
                # Use configured path or default
                model_path = self.model_path
                if not model_path:
                    model_path = _get_default_piper_model_path()
                    debug_log(f"No model configured, using default: {model_path}", "tts")

                # Expand user path (e.g., ~/models/voice.onnx)
                model_path = os.path.expanduser(model_path)
                config_path = model_path + ".json"

                # Auto-download if model doesn't exist
                if not os.path.exists(model_path) or not os.path.exists(config_path):
                    # Extract voice name from path for download
                    voice_name = os.path.basename(model_path).replace(".onnx", "")

                    print(f"🔊 Downloading Piper voice: {voice_name}", file=sys.stderr, flush=True)
                    print("   This is a one-time download (~60MB)...", file=sys.stderr, flush=True)

                    def progress(msg):
                        print(msg, file=sys.stderr, flush=True)

                    downloaded_path = _download_piper_voice(voice_name, progress_callback=progress)

                    if not downloaded_path:
                        self._init_error = f"Failed to download voice: {voice_name}"
                        debug_log(f"Piper TTS init failed: {self._init_error}", "tts")
                        self._initialized = True
                        return False

                    model_path = downloaded_path
                    config_path = model_path + ".json"
                    print("✓ Voice downloaded successfully!", file=sys.stderr, flush=True)

                # Final check that files exist
                if not os.path.exists(model_path):
                    self._init_error = f"Model file not found: {model_path}"
                    debug_log(f"Piper TTS init failed: {self._init_error}", "tts")
                    self._initialized = True
                    return False

                if not os.path.exists(config_path):
                    self._init_error = f"Model config not found: {config_path}"
                    debug_log(f"Piper TTS init failed: {self._init_error}", "tts")
                    self._initialized = True
                    return False

                debug_log(f"Piper TTS loading model: {model_path}", "tts")

                # Import piper and load model
                from piper.voice import PiperVoice

                self._voice = PiperVoice.load(model_path, config_path)
                self._sample_rate = self._voice.config.sample_rate

                debug_log(f"Piper TTS initialized: sample_rate={self._sample_rate}", "tts")

            except ImportError as e:
                self._init_error = f"piper-tts not installed: {e}"
                debug_log(f"Piper TTS init failed: {self._init_error}", "tts")
            except Exception as e:
                self._init_error = f"Failed to load Piper model: {e}"
                debug_log(f"Piper TTS init failed: {self._init_error}", "tts")

            self._initialized = True
            return self._voice is not None

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        # Initialize model eagerly at startup (downloads if needed)
        # This provides better UX - download happens during startup, not first speech
        self._ensure_initialized()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        try:
            self.interrupt()
        except Exception:
            pass
        self._stop.set()
        try:
            self._q.put_nowait("")
        except Exception:
            pass
        self._thread.join(timeout=2.0)
        self._thread = None
        self._stop.clear()

    def speak(self, text: str, completion_callback: Optional[Callable[[], None]] = None,
              duration_callback: Optional[Callable[[float], None]] = None,
              playback_started_callback: Optional[Callable[[], None]] = None,
              playback_ended_callback: Optional[Callable[[], None]] = None,
              volume: float = 1.0) -> None:
        # Signature mirrors ChatterboxTTS.speak so callers (listener.py) can
        # pass the same callbacks regardless of which engine is active.
        if not self.enabled or not text.strip():
            return
        # Lazy start the worker thread
        if self._thread is None:
            self.start()
        self._completion_callback = completion_callback
        self._duration_callback = duration_callback
        self._playback_started_callback = playback_started_callback
        self._playback_ended_callback = playback_ended_callback
        self._speak_volume = float(np.clip(volume, 0.0, 2.0))
        # Preprocess text for speech
        processed_text = _preprocess_for_speech(text)
        try:
            self._q.put_nowait(processed_text)
        except Exception:
            pass

    def interrupt(self) -> None:
        """Stop current speech immediately."""
        self._should_interrupt.set()
        with self._audio_lock:
            if self._audio_stream is not None:
                try:
                    self._audio_stream.abort()
                except Exception:
                    pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if not text:
                continue
            try:
                self._speak_once(text)
            except Exception as e:
                debug_log(f"Piper TTS error in _speak_once: {e}", "tts")
                continue

    def _speak_once(self, text: str) -> None:
        self._is_speaking.set()
        self._last_spoken_text = text
        self._should_interrupt.clear()
        interrupted = False

        # Signal synthesizing state to face widget (audio not playing yet)
        self._publish_tts_state("synthesizing")  # string literal — JarvisState was never imported at module scope

        try:
            # Initialize on first use
            if not self._ensure_initialized():
                if self._init_error:
                    print(f"  ⚠️ Piper TTS: {self._init_error}", flush=True)
                return

            start_time = time.time()

            # Check for interruption before synthesis
            if self._should_interrupt.is_set():
                debug_log("Piper TTS interrupted before synthesis", "tts")
                return

            # Decide whole-text vs sentence-streaming. Streaming synthesises +
            # plays one sentence at a time so time-to-first-audio is the FIRST
            # sentence's synthesis time, not the whole reply's. Gate on the
            # config flag AND >1 sentence; otherwise fall through to the
            # byte-for-byte whole-text path (a single segment).
            segments = [text]
            if _get_streaming_enabled():
                split = _split_into_sentences(text)
                if len(split) > 1:
                    segments = split
                    debug_log(
                        f"Piper TTS streaming: {len(segments)} sentences", "tts"
                    )

            # `_started_fired` guarantees the wake-listener mute hook
            # (playback_started_callback) fires EXACTLY ONCE for the whole
            # reply — on the first sentence whose audio actually engages.
            started_fired = [False]

            def _fire_started_once():
                if started_fired[0]:
                    return
                started_fired[0] = True
                if self._playback_started_callback is not None:
                    try:
                        self._playback_started_callback()
                    except Exception as _cb_err:
                        debug_log(
                            f"Piper playback_started_callback error: {_cb_err}",
                            "tts",
                        )

            for seg in segments:
                if self._should_interrupt.is_set():
                    debug_log("Piper TTS interrupted before next sentence", "tts")
                    interrupted = True
                    break

                seg_audio = self._synthesise(seg)
                if self._should_interrupt.is_set():
                    interrupted = True
                    break
                if seg_audio is None or len(seg_audio) == 0:
                    # Nothing to play for this segment — skip, keep going.
                    continue

                # Exact duration per played segment, for echo detection. In
                # streaming mode this tracks the currently-playing sentence,
                # which is the correct echo window (each sentence plays at a
                # distinct time). track_tts_start / the full-reply text remain
                # the listener's responsibility and are untouched.
                exact_duration = len(seg_audio) / self._sample_rate
                if self._duration_callback is not None:
                    try:
                        self._duration_callback(exact_duration)
                    except Exception as e:
                        debug_log(f"Piper TTS duration callback error: {e}", "tts")

                _played_ok, seg_interrupted = self._play_int16_array(
                    seg_audio, play_started_hook=_fire_started_once
                )
                if seg_interrupted:
                    interrupted = True
                    break

            actual_duration = time.time() - start_time
            debug_log(
                f"Piper TTS complete: actual={actual_duration:.2f}s "
                f"(segments={len(segments)}, interrupted={interrupted})",
                "tts",
            )

        except Exception as e:
            debug_log(f"Piper TTS error: {e}", "tts")
            print(f"  ⚠️ Piper TTS error: {e}", flush=True)
        finally:
            self._is_speaking.clear()
            self._publish_tts_state("idle")  # string literal — JarvisState was never imported at module scope

            # Fire playback-ended on natural completion (mirrors Chatterbox),
            # then clear the one-shot start/ended callbacks so they don't leak
            # into the next utterance.
            if self._playback_ended_callback is not None and not interrupted:
                try:
                    self._playback_ended_callback()
                except Exception as _cb_err:
                    debug_log(f"Piper playback_ended_callback error: {_cb_err}", "tts")
            self._playback_started_callback = None
            self._playback_ended_callback = None

            # Call completion callback if set and not interrupted
            if self._completion_callback is not None and not interrupted:
                try:
                    self._completion_callback()
                except Exception as e:
                    print(f"  ⚠️ Piper TTS completion callback error: {e}", flush=True)
                self._completion_callback = None

    def _synthesise(self, text: str) -> Optional["np.ndarray"]:
        """Synthesise one text segment to a concatenated int16 mono array.

        Returns the audio samples, or None if interrupted mid-synthesis or no
        audio was produced. Interrupt checks happen between chunks so a STOP
        during synthesis of a long sentence aborts promptly. This is the exact
        synthesis logic the whole-text path used previously, lifted verbatim so
        single-segment behaviour is byte-for-byte unchanged.
        """
        import numpy as np
        from piper.config import SynthesisConfig

        debug_log(
            f"Piper TTS starting synthesis: {len(text.split())} words", "tts"
        )
        syn_config = SynthesisConfig(
            speaker_id=self.speaker,
            length_scale=self.length_scale,
            noise_scale=self.noise_scale,
            noise_w_scale=self.noise_w,
        )
        audio_chunks = []
        for chunk in self._voice.synthesize(text, syn_config):
            if self._should_interrupt.is_set():
                debug_log("Piper TTS interrupted during synthesis", "tts")
                return None
            audio_chunks.append(chunk.audio_int16_array)

        if self._should_interrupt.is_set():
            debug_log("Piper TTS interrupted after synthesis", "tts")
            return None
        if not audio_chunks:
            debug_log("Piper TTS: no audio chunks generated", "tts")
            return None

        full_audio = np.concatenate(audio_chunks)
        if len(full_audio) == 0:
            debug_log("Piper TTS: no audio generated", "tts")
            return None

        exact_duration = len(full_audio) / self._sample_rate
        debug_log(
            f"Piper TTS synthesis complete: {exact_duration:.2f}s, "
            f"{len(full_audio)} samples",
            "tts",
        )
        return full_audio

    def _play_int16_array(
        self,
        full_audio: "np.ndarray",
        play_started_hook: Optional[Callable[[], None]] = None,
    ) -> tuple[bool, bool]:
        """Play one int16 mono buffer via sounddevice, honouring interrupt.

        Returns ``(played_ok, interrupted)``. ``play_started_hook`` fires once
        this buffer's stream actually engages (used to fire the reply-level
        ``playback_started_callback`` exactly once, on the first sentence).

        This is the playback logic the whole-text path used previously, lifted
        verbatim (device selection, WASAPI-rate resample, streaming callback,
        interrupt-abort wait loop) so single-segment behaviour is unchanged. It
        is reused per sentence in streaming mode.
        """
        import sounddevice as sd
        import numpy as np

        interrupted = False

        # Play audio with streaming for interruption support
        play_position = [0]
        blocksize = 1024  # Small blocks for responsive interruption

        def audio_callback(outdata, frames, time_info, status):
            if self._should_interrupt.is_set():
                raise sd.CallbackAbort()

            start = play_position[0]
            end = start + frames
            chunk = full_audio[start:end]

            boost = self._speak_volume
            if len(chunk) < frames:
                # Pad with zeros if we're at the end
                boosted = (chunk.astype(np.float32) * boost)
                boosted = np.clip(boosted, -32768.0, 32767.0)
                outdata[:len(chunk), 0] = boosted.astype(np.int16)
                outdata[len(chunk):, 0] = 0
                raise sd.CallbackStop()
            else:
                boosted = (chunk.astype(np.float32) * boost)
                boosted = np.clip(boosted, -32768.0, 32767.0)
                outdata[:, 0] = boosted.astype(np.int16)

            play_position[0] = end

        # Resolve the output device FRESH on every play (no cache): honours a
        # just-changed cfg.tts_output_device AND, in follow mode, the CURRENT
        # Windows default output. So unplugging the headphones re-routes Piper
        # on the next utterance with no restart. None → PortAudio default.
        configured_device = _resolve_output_device_live()

        # WASAPI shared mode rejects sample rates that differ from the
        # device's mix format — e.g. Piper's 22050 Hz on a 48000 Hz CORSAIR
        # headset raises PortAudioError('Invalid device', -9996). Resample
        # to the device's native rate so any host API (incl. low-latency
        # WASAPI) accepts the stream. The duration callback already used the
        # original-rate sample count, and resampling preserves wall-clock
        # length. `full_audio` is reassigned here and the audio_callback
        # closes over it (late binding), so the callback streams the
        # resampled buffer.
        play_sr = self._sample_rate
        if configured_device is not None:
            try:
                dev_native = int(round(float(
                    sd.query_devices(configured_device).get(
                        "default_samplerate", self._sample_rate))))
            except Exception:
                dev_native = self._sample_rate
            if dev_native and dev_native != self._sample_rate:
                try:
                    from scipy.signal import resample_poly
                    from math import gcd
                    g = gcd(dev_native, self._sample_rate) or 1
                    resampled = resample_poly(
                        full_audio.astype(np.float32),
                        dev_native // g, self._sample_rate // g)
                    full_audio = np.clip(
                        resampled, -32768.0, 32767.0).astype(np.int16)
                    play_sr = dev_native
                    debug_log(
                        f"Piper: resampled {self._sample_rate}->{dev_native} "
                        f"for device {configured_device}", "tts")
                except Exception as _re:
                    debug_log(
                        f"Piper resample failed ({_re!r}); trying native "
                        f"{self._sample_rate} Hz", "tts")

        def _open_stream(dev, rate):
            return sd.OutputStream(
                samplerate=rate,
                channels=1,
                dtype='int16',
                blocksize=blocksize,
                device=dev,
                callback=audio_callback,
            )

        with self._audio_lock:
            try:
                self._audio_stream = _open_stream(configured_device, play_sr)
                if configured_device is not None:
                    print(f"🔊 Piper TTS → device {configured_device} @ {play_sr} Hz",
                          flush=True)
            except Exception as _dev_err:
                if configured_device is not None:
                    print(f"⚠️ Piper: device {configured_device} @ {play_sr} Hz "
                          f"failed ({_dev_err!r}) — falling back to default",
                          flush=True)
                    debug_log(f"Piper device {configured_device} open failed: "
                              f"{_dev_err!r}; using default", "tts")
                    self._audio_stream = _open_stream(None, play_sr)
                else:
                    raise
            # Audio playback actually starts — switch to SPEAKING
            self._publish_tts_state("speaking")  # string literal — JarvisState was never imported at module scope
            self._audio_stream.start()

        # Audio is now engaged — fire playback-started (e.g. so the wake
        # listener mutes itself while Jarvis speaks). Outside the audio lock.
        # In streaming mode the hook is a once-guard so only the first
        # sentence's engage actually invokes the reply-level callback.
        if play_started_hook is not None:
            try:
                play_started_hook()
            except Exception as _cb_err:
                debug_log(f"Piper play_started_hook error: {_cb_err}", "tts")

        # Wait for playback to complete
        try:
            while self._audio_stream is not None and self._audio_stream.active:
                if self._should_interrupt.is_set():
                    interrupted = True
                    with self._audio_lock:
                        if self._audio_stream is not None:
                            self._audio_stream.abort()
                    break
                time.sleep(0.05)
        finally:
            with self._audio_lock:
                if self._audio_stream is not None:
                    try:
                        self._audio_stream.close()
                    except Exception:
                        pass
                    self._audio_stream = None

        return (True, interrupted)

    def _publish_tts_state(self, state: "JarvisState") -> None:
        """Publish the current TTS phase to the React HUD via the shared
        QObject-free helper. (Previously this used the desktop_app.face_widget
        path with an enum-vs-string comparison, so Piper never reached the HUD
        and the widget stuck on PROCESSING.)"""
        _publish_tts_react_state(state)

    # Loopback guard helpers (same interface as TextToSpeech)
    def is_speaking(self) -> bool:
        return self._is_speaking.is_set()

    def get_last_spoken_text(self) -> str:
        return self._last_spoken_text


def create_tts_engine(
    engine: str = "piper",
    enabled: bool = True,
    voice: Optional[str] = None,
    rate: Optional[int] = None,
    # Chatterbox parameters
    device: str = "cuda",
    audio_prompt_path: Optional[str] = None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    # Piper parameters
    piper_model_path: Optional[str] = None,
    piper_speaker: Optional[int] = None,
    piper_length_scale: float = 1.0,
    piper_noise_scale: float = 0.667,
    piper_noise_w: float = 0.8,
    piper_sentence_silence: float = 0.2,
):
    """Factory function to create the appropriate TTS engine.

    Supported engines:
    - "piper" (default): Neural TTS with auto-download, exact duration tracking
    - "chatterbox": AI voice with emotion control (requires PyTorch)
    """
    if engine.lower() == "chatterbox":
        return ChatterboxTTS(
            enabled=enabled,
            voice=voice,
            rate=rate,
            device=device,
            audio_prompt_path=audio_prompt_path,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
        )
    else:
        # Default to Piper TTS
        return PiperTTS(
            enabled=enabled,
            voice=voice,
            rate=rate,
            model_path=piper_model_path,
            speaker=piper_speaker,
            length_scale=piper_length_scale,
            noise_scale=piper_noise_scale,
            noise_w=piper_noise_w,
            sentence_silence=piper_sentence_silence,
        )


def json_escape_ps(s: str) -> str:
    # For PowerShell, use double quotes and escape internal double quotes
    # This avoids issues with apostrophes in contractions like "you're"
    escaped = s.replace('"', '""')
    return '"' + escaped + '"'
