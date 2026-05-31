import os
import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv


# ============================================================================
# SUPPORTED CHAT MODELS - Single Source of Truth
# ============================================================================
# This is the authoritative list of officially supported chat models.
# Other modules should import from here rather than defining their own lists.

SUPPORTED_CHAT_MODELS: Dict[str, Dict[str, str]] = {
    "gemma4:e2b": {
        "name": "Gemma 4 E2B (Default)",
        "description": "Fast, multimodal, effective 2B — a little dumb, occasionally fumbles tool calls; ~7.2GB download",
        "size": "~7.2GB",
        "vram": "8GB+",
    },
    "gemma4:e4b": {
        "name": "Gemma 4 E4B (Recommended)",
        "description": "Smarter tool use and reasoning, multimodal, effective 4B — ~9.6GB download",
        "size": "~9.6GB",
        "vram": "16GB+",
    },
    "gpt-oss:20b": {
        "name": "GPT-OSS 20B (High-end)",
        "description": "Best performance, ~12GB download",
        "size": "~12GB",
        "vram": "24GB+",
    },
    "qwen3.5:9b-8k": {
        "name": "Qwen 3.5 9B (8k ctx)",
        "description": "Custom local build — strong chat + tool use; pairs with Piper TTS on a 16GB GPU",
        "size": "~6.6GB",
        "vram": "16GB+",
    },
    "qwen3.5:4b-4k": {
        "name": "Qwen 3.5 4B (4k ctx)",
        "description": "Fast intent/router model — low VRAM, quick classification",
        "size": "~3.4GB",
        "vram": "8GB+",
    },
}

# The default chat model (first in the supported list)
DEFAULT_CHAT_MODEL = "gemma4:e2b"


def get_supported_model_ids() -> set[str]:
    """Get set of supported model IDs for quick lookup."""
    return set(SUPPORTED_CHAT_MODELS.keys())


def _default_dictation_hotkey() -> str:
    """Return the platform-appropriate default dictation hotkey.

    Aligned with WisprFlow defaults:
    - Windows: Ctrl+Win (pynput maps Win to ``cmd``)
    - macOS: Fn is not detectable by pynput, so use Ctrl+Option (WisprFlow
      fallback when Fn is unavailable)
    - Linux: Ctrl+Alt (mirrors macOS fallback)
    """
    if sys.platform == "win32":
        return "ctrl+cmd"
    elif sys.platform == "darwin":
        return "ctrl+alt"
    else:
        return "ctrl+alt"


def _default_db_path() -> str:
    base = Path.home() / ".local" / "share" / "jarvis"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "jarvis.db")


@dataclass(frozen=True)
class Settings:
    # Database & Storage
    db_path: str
    sqlite_vss_path: str | None

    # LLM & AI Models
    ollama_base_url: str
    ollama_embed_model: str
    ollama_chat_model: str
    llm_chat_timeout_sec: float
    llm_tools_timeout_sec: float
    # Tight deadline for the cheap distil passes used by memory_digest and
    # tool_result_digest. Separate from `llm_tools_timeout_sec` because
    # those paths run a small classification-shaped LLM call, not a
    # long-running tool — a 5-minute ceiling there would stall replies.
    llm_digest_timeout_sec: float
    llm_embedding_timeout_sec: float
    llm_profile_select_timeout_sec: float
    # Bounds/tuning for the main agentic chat generation. `llm_chat_max_tokens`
    # caps generated tokens per synthesis turn (num_predict) so latency/length
    # are bounded; `llm_chat_temperature` is the sampling temperature, with the
    # sentinel -1.0 meaning "unset / use the model default".
    llm_chat_max_tokens: int
    llm_chat_temperature: float

    # Profiles & Behavior
    active_profiles: list[str]
    use_stdin: bool
    voice_debug: bool
    # When True, save each VAD-gated audio segment as a WAV file under
    # %LOCALAPPDATA%/Jarvis/debug_audio/ (Windows) or ~/.cache/jarvis/
    # debug_audio/ (other). Lets us listen to exactly what Whisper receives.
    # Off by default — only useful for diagnostic sessions.
    voice_debug_save_audio: bool

    # Screen Capture
    allowlist_bundles: list[str]

    # Text-to-Speech
    tts_enabled: bool
    tts_engine: str  # "piper" (default) or "chatterbox"
    tts_voice: str | None
    tts_rate: int | None  # Words per minute (WPM), 200=normal
    tts_chatterbox_device: str  # "cuda", "auto", or "cpu" for Chatterbox
    tts_chatterbox_audio_prompt: str | None  # Path to audio file for voice cloning with Chatterbox
    tts_chatterbox_exaggeration: float  # Emotion exaggeration control (0.0-1.0+)
    tts_chatterbox_cfg_weight: float  # CFG weight for quality/speed trade-off
    tts_chatterbox_steps: int  # Tier 1.2: max_new_tokens for t3 diffusion sampling (1000 default upstream, 300 recommended)
    tts_output_device: Optional[str]  # Output device for sounddevice + pygame. None = system default. Accepts integer index (e.g. "16") or case-insensitive name substring (e.g. "PD200X" or "Realtek").
    tts_streaming_enabled: bool  # Synthesise + play replies sentence-by-sentence (Piper) so the first sentence starts before the whole reply is synthesised. Falls back to whole-text playback when False or for single-sentence replies.

    # Piper TTS
    tts_piper_model_path: str | None  # Path to .onnx voice model
    tts_piper_speaker: int | None  # Speaker ID for multi-speaker models
    tts_piper_length_scale: float  # Speed: <1.0 faster, >1.0 slower
    tts_piper_noise_scale: float  # Audio variation
    tts_piper_noise_w: float  # Phoneme width variation
    tts_piper_sentence_silence: float  # Post-sentence silence in seconds

    # Voice Input & Audio
    voice_device: str | None
    sample_rate: int
    voice_min_energy: float

    # Audio Device Selection (explicit, remembered by STABLE endpoint id)
    # The user's chosen output (speaker) + input (wake-word mic) are persisted
    # by Windows Core Audio endpoint id (preferred, survives reconnects) with
    # the friendly name kept alongside as a display label + resolution
    # fallback. Empty string = "not selected" (no OS-default follow). See
    # docs/superpowers/specs/2026-05-29-audio-device-redesign-design.md.
    audio_output_endpoint_id: str
    audio_output_name: str
    audio_input_endpoint_id: str
    audio_input_name: str

    # Voice Collection & Timing
    voice_block_seconds: float
    voice_collect_seconds: float
    voice_max_collect_seconds: float

    # Wake Word Detection
    wake_word: str
    wake_aliases: list[str]
    wake_fuzzy_ratio: float

    # STT backend selection — "whisper" (local faster-whisper) or "wispr" (cloud Wispr Flow via push-to-talk bridge)
    stt_backend: str
    # Wispr Flow bridge settings (only used when stt_backend == "wispr")
    wispr_wake_model: str          # openWakeWord model name (default "hey_jarvis_v0.1")
    wispr_wake_threshold: float    # Detection confidence threshold 0.0-1.0 (default 0.1)
    wispr_wake_gain: float         # Software gain on the wake-detection audio ONLY (default 1.0)
    wispr_wake_rms_floor: float    # Ungained int16 RMS below which a wake frame is gated as silence on the TRIGGER only; 0.0 = off (default 0.0)
    wispr_silence_ms: int          # Silero VAD silence ms for PTT release (default 800)
    wispr_min_dictation_sec: float # Suppress early VAD release for this many seconds (default 2.0)
    wispr_max_dictation_sec: int   # Hard timeout for dictation (default 30)
    wispr_clipboard_wait_sec: float # Max wait for Wispr Flow transcript to appear in clipboard (default 6.0)
    wispr_hot_window_sec: float    # Seconds after reply during which follow-up does not need wake word (default 10.0)
    wispr_suppress_autotype: bool  # Send backspaces to erase Wispr Flow's auto-typed text (default True)
    wispr_mic_device: int | str | None  # Mic device for the bridge; None = system default
    # Closed-loop start/stop synchronisation (reconcile against Wispr's real mic-recording state)
    wispr_closed_loop_enabled: bool        # Read Wispr's real recording state and reconcile before/after taps (default True)
    wispr_hands_free_combo: list[str]      # Wispr hands-free toggle chord to simulate, e.g. ["ctrl","cmd","space"] (default)
    wispr_min_tap_gap_sec: float           # Minimum gap between consecutive toggle taps to dodge Wispr's rapid-toggle freeze (default 0.5)
    wispr_confirm_timeout_sec: float       # How long to poll Wispr's mic state to confirm a tap took effect (default 1.2)
    wispr_clipboard_grace_sec: float       # Extra grace after the clipboard wait before declaring no-capture (default 2.0)
    wispr_erase_max_chars: int             # Cap on auto-type erase backspaces; longer transcripts skip erase (default 300)
    wispr_barge_in_interrupt: bool         # Tear down TTS on speech onset during a hot window (default True)

    # Whisper Speech Recognition
    whisper_model: str
    whisper_backend: str  # "auto", "mlx", or "faster-whisper"
    whisper_device: str  # "cuda", "auto", or "cpu" (only for faster-whisper)
    whisper_compute_type: str
    whisper_vad: bool
    whisper_min_confidence: float
    whisper_no_speech_threshold: float
    whisper_min_audio_duration: float
    whisper_min_word_length: int
    # Whisper decoder accuracy knobs. None = use library default.
    whisper_compression_ratio_threshold: Optional[float]
    whisper_initial_prompt: Optional[str]
    whisper_allowed_languages: list[str]
    # When Whisper's auto-detect returns a language NOT in allowed, the
    # fallback picker tries languages in this priority order before falling
    # back to probability-voting. Set to e.g. ["el", "en"] for Greek-primary
    # users so Greek wins over English-biased auto-detect. None = no priority.
    language_priority: list[str]
    # Bootstrap language for the first few utterances before the sticky
    # language lock reaches consensus. None = auto-detect.
    whisper_default_language: Optional[str]
    # Decoder strategy knobs (Phase A — see listening.spec.md "ASR reliability").
    whisper_beam_size: int  # 1 = greedy, recommended for command-style ASR
    whisper_temperature_fallback: list[float]  # fallback schedule on retry
    whisper_hallucination_silence_threshold: Optional[float]  # faster-whisper hallucination guard

    # Voice Activity Detection (VAD)
    vad_enabled: bool
    vad_backend: str  # "silero" (default, ~4x fewer errors than webrtc) or "webrtc" (fallback)
    vad_aggressiveness: int  # webrtc backend only: 0-3
    # Silero backend tunables — hysteresis pair + segmentation params.
    vad_silero_threshold: float          # onset threshold (strict — fewer false starts)
    vad_silero_neg_threshold: float      # offset threshold (permissive — catch Greek codas)
    vad_silero_min_speech_ms: int        # filter out sub-N ms breath/click noise
    vad_silero_min_silence_ms: int       # don't split intra-utterance pauses
    vad_silero_speech_pad_ms: int        # preserve unvoiced consonants
    vad_frame_ms: int
    vad_pre_roll_ms: int
    endpoint_silence_ms: int
    max_utterance_ms: int
    tts_max_utterance_ms: int

    # Microphone input preprocessing (AGC)
    mic_agc_enabled: bool
    mic_agc_target_rms: float
    mic_agc_max_gain: float

    # UI/UX Features
    tune_enabled: bool
    hot_window_enabled: bool
    hot_window_seconds: float

    # Echo Detection
    echo_energy_threshold: float
    echo_tolerance: float

    # Intent Judge (LLM-based intent classification)
    # Always used when available, falls back to simple wake word detection
    intent_judge_model: str
    intent_judge_timeout_sec: float

    # Transcript Buffer - ambient speech context for intent judge
    transcript_buffer_duration_sec: float

    # Memory & Dialogue
    # Drives both the short-term memory window and forced diary update interval
    dialogue_memory_timeout: float
    memory_enrichment_max_results: int
    memory_enrichment_source: str  # "all", "diary", or "graph"
    # How many agentic turns the inter-turn memory-injection window stays open.
    # If the async memory worker has not finished by this turn, the recalled
    # memory is dropped (logged via debug_log) so the loop can progress.
    memory_injection_max_turns: int
    # Tool-call + tool-result messages from prior replies in the hot window
    # are re-injected into the next turn so follow-ups can reuse them instead
    # of re-fetching. These knobs cap how many prior tool turns survive and
    # how much of each tool payload is retained (the fence markers of
    # UNTRUSTED WEB EXTRACT blocks are preserved on truncation).
    tool_carryover_max_turns: int
    tool_carryover_per_entry_chars: int
    # Distil diary + graph into a short relevance-filtered note via a cheap
    # LLM pass before injecting into the reply system prompt. When None
    # (the default), it auto-enables for SMALL models (≤7B) and stays off
    # for larger models that can handle raw dumps. Set explicitly to force.
    memory_digest_enabled: Optional[bool]
    # Distil raw tool-result payloads (e.g. webSearch extracts) into a
    # short, attributed fact note via a cheap LLM pass before appending
    # them as tool-role messages. When None (the default), it auto-enables
    # for SMALL models (≤7B) and stays off for larger models that ground
    # on the raw payload reliably. Set explicitly to force on/off.
    tool_result_digest_enabled: Optional[bool]

    # Agentic Loop
    agentic_max_turns: int
    tool_selection_strategy: str  # "all", "keyword", "embedding", or "llm"
    # When `tool_selection_strategy == "llm"`, this model does the routing.
    # Empty string means "reuse `ollama_chat_model`" (the default).
    tool_router_model: str
    # Optional override for the post-turn evaluator LLM. Empty string means
    # "fall back to intent_judge_model, then ollama_chat_model" (the default).
    evaluator_model: str
    # None = auto (on for SMALL models, off for LARGE). Explicit true/false forces.
    evaluator_enabled: Optional[bool]
    # Upper bound on toolSearchTool invocations per reply turn. The cap
    # prevents a small model from churning through the escape hatch forever
    # when no tool really fits.
    tool_search_max_calls: int
    # Upper bound on evaluator-driven nudges per reply. Each time the
    # evaluator says "continue" with a nudge, the nudge is injected into
    # the next turn's system message. This cap stops nudge ping-pong when
    # the model keeps producing prose despite the nudge.
    evaluator_nudge_max: int
    # Optional override for the pre-loop task-list planner model. Empty
    # string means "fall back to tool_router_model → intent_judge_model →
    # ollama_chat_model" (the default). The planner is a small
    # classification-shaped pass so it rides the same small-model chain
    # as the router and the evaluator.
    planner_model: str
    # Whether the pre-loop planner is enabled. True = planner always runs;
    # False = planner never runs (legacy behaviour, with the
    # compound_query fallback still active). Default True — the planner
    # fails open to an empty plan so the cost of a miss is one cheap LLM
    # round-trip, and the upside is multi-step queries actually complete.
    planner_enabled: bool
    # Timeout for the planner LLM call. Short because the planner is on
    # the critical path — a long timeout would dominate first-token
    # latency for every query. Planner fails open on timeout.
    planner_timeout_sec: float

    # Location Services
    location_enabled: bool
    location_cache_minutes: int
    location_ip_address: str | None
    location_auto_detect: bool
    location_cgnat_resolve_public_ip: bool

    # Web Search
    web_search_enabled: bool
    # Optional Brave Search API key. When set, Brave is used as the primary
    # fallback when DuckDuckGo is rate-limited or returns no usable content.
    # Empty string means "not configured" — the tool then falls through to
    # the always-on Wikipedia fallback. Free tier is 2,000 queries/month.
    brave_search_api_key: str
    # Zero-config Wikipedia fallback toggle. When True (default), the tool
    # queries Wikipedia's REST summary API as a last resort before giving up
    # with the honest "blocked" envelope. Privacy-light (public API, no key,
    # no account) and language-aware via the Whisper-detected utterance
    # language.
    wikipedia_fallback_enabled: bool

    # Vision & Screen Interaction Engine (see src/jarvis/vision/vision.spec.md).
    # Disabled by default — the tools stay dormant until vision_enabled is True.
    vision_enabled: bool
    vision_model: str                 # Ollama vision model for describe + grounding
    vision_default_mode: str          # observe | assist | auto
    vision_auto_whitelist: list       # process names allowed to act without confirmation in AUTO
    vision_auto_blacklist: list       # process names never auto-actioned (banks, password mgrs, browsers)
    vision_pending_ttl_sec: int       # how long a proposed action waits for confirmation
    vision_keep_alive: str            # Ollama keep_alive for the vision model (short -> self-evicts)
    vision_max_width: Optional[int]   # cap longest side of the image sent to the vision model (None = off); OCR/read keeps full res
    vision_timeout_sec: float         # per-call vision model timeout (headroom for cold load)

    # Dictation (hold-to-dictate)
    dictation_enabled: bool
    dictation_hotkey: str
    dictation_filler_removal: bool
    dictation_custom_dictionary: list

    # MCP Integration
    mcps: Dict[str, Any]

    # Reminders (time-triggered spoken + tray reminders; fired on the daemon poll loop)
    reminders_enabled: bool = True
    reminder_check_interval_sec: float = 2.0
    reminder_grace_window_sec: float = 300.0
    reminder_default_snooze_min: int = 5
    reminder_speak_on_fire: bool = True
    reminder_parse_timeout_sec: float = 8.0

    # Memory lifecycle (TTL / pruning / monthly consolidation; run on the poll loop)
    memory_ttl_enabled: bool = False
    memory_ttl_default_days: int = 0
    memory_weekly_prune_enabled: bool = True
    memory_weekly_prune_min_age_days: int = 30
    memory_monthly_consolidation_enabled: bool = True
    memory_archive_delete_raw: bool = True



def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "jarvis" / "config.json"
    return Path.home() / ".config" / "jarvis" / "config.json"


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: Dict[str, Any]) -> bool:
    """Save config data to JSON file. Returns True on success."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def _migrate_config(cfg_path: Path, cfg_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply config migrations for version upgrades.

    Returns the (possibly modified) config dict.
    """
    modified = False

    # Get current migration version (0 if not set = pre-migration config)
    migration_version = cfg_json.get("_config_version", 0)

    # Migration v1: tts_engine "system" -> "piper"
    # Piper is now the default TTS with auto-download support.
    if migration_version < 1:
        if cfg_json.get("tts_engine") == "system":
            cfg_json["tts_engine"] = "piper"
            print("📢 Upgraded TTS engine: system → piper (neural voice with auto-download)", flush=True)
            print("   To revert: set \"tts_engine\": \"system\" in config.json", flush=True)
        cfg_json["_config_version"] = 1
        modified = True

    # Migration v2: mic accuracy upgrade — only migrate fields the user clearly
    # did NOT customise (still on their pre-upgrade default), so users who chose
    # int8 deliberately or wrote their own initial_prompt keep their preference.
    if migration_version < 2:
        # int8 → float16 (faster AND more accurate on CUDA; CPU fallback chain
        # automatically downgrades back to int8 if float16 isn't supported).
        if cfg_json.get("whisper_compute_type") == "int8":
            cfg_json["whisper_compute_type"] = "float16"
            print("📢 Upgraded Whisper compute type: int8 → float16 (faster + more accurate on CUDA)", flush=True)
        # NOTE: v2 also seeded a verbose initial_prompt, but migration v3 below
        # reverts that — it turned out to poison Whisper's decoder. We keep the
        # v2 marker so the schema-version counter is monotonic.
        cfg_json["_config_version"] = 2
        modified = True

    # Migration v3: undo the prompt-poisoning regression from v2 and disable
    # the AGC default that interfered with Whisper's internal normalisation.
    if migration_version < 3:
        # The v2 prompt was instruction-style and Whisper memorised it,
        # echoing "Greek voice assistant. Λέξεις,..." into transcripts.
        # Wipe back to None unless the user has manually written a different
        # prompt in the meantime. See:
        #   - medium.com/axinc-ai/prompt-engineering-in-whisper-6bb18003562d
        #   - openai/whisper Discussion #1150
        _poisoned_prompts = {
            (
                "Jarvis. Greek/English voice assistant. "
                "Λέξεις: καιρός, αύριο, Θεσσαλονίκη, Αθήνα, σήμερα, "
                "παίξε, βάλε, μουσική, email."
            ),
            "Jarvis. Greek/English voice assistant.",
        }
        if cfg_json.get("whisper_initial_prompt") in _poisoned_prompts:
            cfg_json["whisper_initial_prompt"] = None
            print(
                "📢 Reverted whisper_initial_prompt to null — prior value "
                "was being echoed in transcripts (prompt poisoning).",
                flush=True,
            )
        # mic_agc_enabled defaulted to True in v2; auto-disable for users
        # still on that default. A user who explicitly wrote `true` after
        # opting in remains unaffected — we mark them via _agc_v2_default
        # so this only fires once, and we never touch a future explicit
        # `true` they may write after this migration.
        if "_agc_v2_default" not in cfg_json:
            if cfg_json.get("mic_agc_enabled") is True:
                cfg_json["mic_agc_enabled"] = False
                print(
                    "📢 Disabled mic AGC by default — interfered with "
                    "Whisper's internal mel-spectrogram normalisation.",
                    flush=True,
                )
            cfg_json["_agc_v2_default"] = True
        cfg_json["_config_version"] = 3
        modified = True

    # Migration v4: ASR reliability upgrade — Phase A defaults.
    # Synthesised from 3 AI consultations + production logs (Greek detected
    # as French/German due to FP16 underflow + lax thresholds). We only
    # auto-bump values that match the v2/v3 default; explicit user overrides
    # remain untouched.
    if migration_version < 4:
        # float16 → int8_float16. Saves ~3 GB VRAM, 1.5-2× speed, <0.2% WER.
        # Verified across RTX 30/40/50. We only migrate `float16` (the v2
        # default) — users who explicitly chose something else stay put.
        if cfg_json.get("whisper_compute_type") == "float16":
            cfg_json["whisper_compute_type"] = "int8_float16"
            print(
                "📢 Upgraded Whisper compute type: float16 → int8_float16 "
                "(smaller VRAM + faster, verified across RTX 30/40/50)",
                flush=True,
            )
        # beam_size: only set if currently missing or explicitly = 5 (the
        # historical hard-coded value). Greedy decoding (1) avoids GSP
        # firmware crashes on Blackwell AND reduces silence hallucinations.
        if cfg_json.get("whisper_beam_size") in (None, 5):
            cfg_json["whisper_beam_size"] = 1
            print(
                "📢 Set Whisper beam_size to 1 (greedy) — eliminates the "
                "decoder's hallucination feedback loop on silent input.",
                flush=True,
            )
        # no_speech_threshold: 0.4 → 0.6 (only if at the v3 default).
        if cfg_json.get("whisper_no_speech_threshold") == 0.4:
            cfg_json["whisper_no_speech_threshold"] = 0.6
            print(
                "📢 Raised whisper_no_speech_threshold: 0.4 → 0.6 (filters "
                "more 'Thank you'/'Okay' hallucinations on silence).",
                flush=True,
            )
        # compression_ratio_threshold: 2.0 → 1.35 (only if at OpenAI default).
        if cfg_json.get("whisper_compression_ratio_threshold") == 2.0:
            cfg_json["whisper_compression_ratio_threshold"] = 1.35
            print(
                "📢 Tightened whisper_compression_ratio_threshold: 2.0 → "
                "1.35 (catches repetition hallucinations earlier).",
                flush=True,
            )
        # vad_silero_threshold: 0.5 → 0.7 (and seed hysteresis fields). Only
        # touch threshold if at the v2/v3 default.
        if cfg_json.get("vad_silero_threshold") == 0.5:
            cfg_json["vad_silero_threshold"] = 0.7
            cfg_json.setdefault("vad_silero_neg_threshold", 0.4)
            cfg_json.setdefault("vad_silero_min_speech_ms", 300)
            cfg_json.setdefault("vad_silero_min_silence_ms", 400)
            cfg_json.setdefault("vad_silero_speech_pad_ms", 400)
            print(
                "📢 Upgraded Silero VAD: threshold 0.5 → 0.7 with hysteresis "
                "0.4 offset (catches Greek codas, drops breathing noise).",
                flush=True,
            )
        cfg_json["_config_version"] = 4
        modified = True

    # Migration v5: emergency rollback of two Phase A values that turned
    # out to be too aggressive for the user's PD200X dynamic mic + Greek
    # speech. Observed in production: only 0.3-0.5 s of audio reached
    # Whisper for 1.5-3 s utterances ("Jarvis, ποιος είναι ο καιρός στη
    # Θεσσαλονίκη" was captured as just "Javi"). Root cause: Silero VAD
    # at 0.7 onset rejects Greek fricatives / unaspirated plosives that
    # sit at probability ~0.5-0.6 on a dynamic mic; no_speech_threshold
    # 0.6 then filtered the borderline short fragments that survived.
    if migration_version < 5:
        if cfg_json.get("vad_silero_threshold") == 0.7:
            cfg_json["vad_silero_threshold"] = 0.5
            cfg_json["vad_silero_neg_threshold"] = 0.3  # also retune hysteresis
            print(
                "📢 Rolled back Silero VAD onset: 0.7 → 0.5 (was rejecting "
                "Greek phonemes on dynamic mic). Hysteresis offset: 0.3.",
                flush=True,
            )
        if cfg_json.get("whisper_no_speech_threshold") == 0.6:
            cfg_json["whisper_no_speech_threshold"] = 0.5
            print(
                "📢 Eased whisper_no_speech_threshold: 0.6 → 0.5 (was "
                "filtering short quiet Greek utterances).",
                flush=True,
            )
        cfg_json["_config_version"] = 5
        modified = True

    # Migration v6: bump endpoint_silence_ms 800 → 1200. Pairs with the
    # silence-frame-inclusion fix in listener.py. With silence frames now
    # included in the audio sent to Whisper, the user can pause longer
    # mid-sentence (for breath / thinking) without losing context. Extending
    # endpoint to 1200 ms gives natural conversational pauses room to
    # breathe without finalising the utterance prematurely.
    if migration_version < 6:
        if cfg_json.get("endpoint_silence_ms") == 800:
            cfg_json["endpoint_silence_ms"] = 1200
            print(
                "📢 Extended endpoint_silence_ms: 800 → 1200 ms (gives "
                "natural mid-sentence pauses room before finalising).",
                flush=True,
            )
        cfg_json["_config_version"] = 6
        modified = True

    # Migration v7: forward the legacy name-based audio device keys into the
    # new endpoint-id selection scheme. The old keys held only a name-ish
    # string (`tts_output_device` for the speaker, `wispr_mic_device` for the
    # wake mic); copy any NON-EMPTY legacy value into the matching
    # `audio_*_name` key so the user's prior choice survives. The matching
    # `*_endpoint_id` is left blank on purpose: resolve_endpoint_to_sd_index
    # falls back to the name and the id is re-learned on next selection. We do
    # NOT seed from the OS default here (that is Phase 2) and we never clobber
    # an already-present new-key value.
    if migration_version < 7:
        def _forward(legacy_key: str, new_name_key: str, label: str) -> None:
            if cfg_json.get(new_name_key):
                return  # already chosen / partially migrated — leave it
            legacy_val = cfg_json.get(legacy_key)
            if legacy_val in (None, "", "null"):
                return  # nothing to carry forward
            cfg_json[new_name_key] = str(legacy_val)
            print(
                f"📢 Carried forward {label} device "
                f"\"{legacy_val}\" to the new endpoint-id selection "
                f"(name fallback resolves it).",
                flush=True,
            )

        _forward("tts_output_device", "audio_output_name", "audio output")
        _forward("wispr_mic_device", "audio_input_name", "audio input")
        cfg_json["_config_version"] = 7
        modified = True

    # Save migrated config
    if modified:
        if _save_json(cfg_path, cfg_json):
            pass  # Silent success
        else:
            print("   ⚠️ Could not save config migration (using new settings in memory).", flush=True)

    return cfg_json


def load_config() -> Dict[str, Any]:
    """
    Load and return the merged configuration dictionary.

    Returns defaults merged with any values from the config file.
    Unlike load_settings(), this returns the raw dict instead of a Settings object.
    """
    cfg_path_env = os.environ.get("JARVIS_CONFIG_PATH")
    cfg_path = Path(cfg_path_env).expanduser() if cfg_path_env else default_config_path()
    cfg_json = _load_json(cfg_path)

    # Apply config migrations for version upgrades
    if cfg_json:
        cfg_json = _migrate_config(cfg_path, cfg_json)

    defaults = get_default_config()
    return {**defaults, **cfg_json}


def _ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(value)]


def _ensure_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    # Accept list of pairs like [{"name":..., ...}] and convert to dict by name if present
    try:
        if isinstance(value, list):
            out: Dict[str, Any] = {}
            for item in value:
                if isinstance(item, dict):
                    key = str(item.get("name")) if item.get("name") is not None else None
                    if key:
                        out[key] = {k: v for k, v in item.items() if k != "name"}
            if out:
                return out
    except Exception:
        pass
    return {}


def get_default_config() -> Dict[str, Any]:
    """Returns the default configuration values."""
    return {
        # Database & Storage
        "db_path": _default_db_path(),
        "sqlite_vss_path": None,

        # LLM & AI Models
        "ollama_base_url": "http://127.0.0.1:11434",
        "ollama_embed_model": "nomic-embed-text",
        "ollama_chat_model": DEFAULT_CHAT_MODEL,
        "llm_chat_timeout_sec": 180.0,
        "llm_tools_timeout_sec": 300.0,
        # Cheap distil passes should fail fast — a hung digest call would
        # block the reply loop per tool call, amplified by agentic turns.
        "llm_digest_timeout_sec": 8.0,
        "llm_embedding_timeout_sec": 60.0,
        "llm_profile_select_timeout_sec": 30.0,
        # Cap the main chat generation at 512 tokens per turn (num_predict) so
        # length/latency are bounded on small local models. -1.0 temperature
        # means "leave the model default untouched".
        "llm_chat_max_tokens": 512,
        "llm_chat_temperature": -1.0,

        # Profiles & Behavior
        "active_profiles": ["developer", "business", "life"],
        "use_stdin": False,

        # Screen Capture
        "allowlist_bundles": [
            "com.apple.Terminal",
            "com.googlecode.iterm2",
            "com.microsoft.VSCode",
            "com.jetbrains.intellij",
        ],


        # Text-to-Speech
        "tts_enabled": True,
        "tts_engine": "piper",  # "piper" (default) or "chatterbox"
        "tts_voice": None,
        "tts_rate": 200,  # Words per minute (WPM), 200=normal
        "tts_chatterbox_device": "cuda",  # "cuda" (recommended), "auto", or "cpu"
        "tts_chatterbox_audio_prompt": None,  # Path to audio file for voice cloning
        "tts_chatterbox_exaggeration": 0.5,  # Emotion exaggeration (0.0-1.0+)
        "tts_chatterbox_cfg_weight": 0.5,  # CFG weight for quality/speed trade-off
        "tts_chatterbox_steps": 300,  # Tier 1.2: max_new_tokens for t3 (300 = ~2.5s/sentence on RTX 5070 Ti)
        "tts_streaming_enabled": True,  # Sentence-by-sentence Piper playback for faster time-to-first-audio

        # Piper TTS
        "tts_piper_model_path": None,  # Path to .onnx voice model
        "tts_piper_speaker": None,  # Speaker ID for multi-speaker models
        "tts_piper_length_scale": 0.65,  # Speed: <1.0 faster, >1.0 slower (0.65 = ~30% faster)
        "tts_piper_noise_scale": 0.8,  # Audio variation (higher = more expressive)
        "tts_piper_noise_w": 1.0,  # Phoneme width variation (higher = more lively)
        "tts_piper_sentence_silence": 0.2,  # Post-sentence silence in seconds

        # Voice Input & Audio
        "voice_device": None,
        "sample_rate": 16000,
        "voice_min_energy": 0.02,

        # Audio Device Selection (explicit + remembered by endpoint id).
        # All empty by default = "not selected". Phase 2 seeds the OS default
        # once on first run; this layer never silently follows the OS default.
        "audio_output_endpoint_id": "",
        "audio_output_name": "",
        "audio_input_endpoint_id": "",
        "audio_input_name": "",

        # Voice Collection & Timing
        "voice_block_seconds": 4.0,
        "voice_collect_seconds": 4.5,
        "voice_max_collect_seconds": 180.0,

        # Wake Word Detection
        "wake_word": "jarvis",
        "wake_aliases": ["joris", "charis", "chavis", "jar is", "jaivis", "jervis", "jarvus", "jarviz", "javis", "jairus", "jarryst", "chyrus"],
        "wake_fuzzy_ratio": 0.78,

        # Whisper Speech Recognition
        # `large-v3-turbo` is ~2-5x faster than large-v3 and roughly the speed
        # of medium while retaining ~95% of large-v3 accuracy. The listener
        # has a built-in fallback to large-v3 → medium if turbo isn't
        # supported by the installed faster-whisper (≥1.1.0 required).
        # STT backend selection — "whisper" runs faster-whisper locally; "wispr" uses
        # the Wispr Flow desktop app via a push-to-talk bridge (openWakeWord + Silero VAD
        # + Ctrl+Win simulation). "wispr" gives better quality + lower local VRAM but
        # sends audio to Wispr's cloud and loses Greek wake aliases.
        "stt_backend": "whisper",
        "wispr_wake_model": "hey_jarvis_v0.1",
        "wispr_wake_threshold": 0.1,
        "wispr_wake_gain": 1.0,
        # Ungained int16 RMS below which a wake frame is treated as silence and
        # the TRIGGER is skipped (the model is still fed every frame). 0.0 = off:
        # the recall-tuned far-field model rejects silence itself, and a non-zero
        # floor must stay below far-field RMS (~100-200 on the PD200X at 2-3 m) or
        # it drops distant wakes. Opt back into a guard via config if ever needed.
        "wispr_wake_rms_floor": 0.0,
        "wispr_silence_ms": 800,
        "wispr_min_dictation_sec": 2.0,
        "wispr_max_dictation_sec": 30,
        "wispr_clipboard_wait_sec": 6.0,
        "wispr_hot_window_sec": 0.0,
        "wispr_suppress_autotype": True,
        "wispr_closed_loop_enabled": True,
        "wispr_hands_free_combo": ["ctrl", "cmd", "space"],
        "wispr_min_tap_gap_sec": 0.5,
        "wispr_confirm_timeout_sec": 1.2,
        "wispr_clipboard_grace_sec": 2.0,
        "wispr_erase_max_chars": 300,
        "wispr_barge_in_interrupt": True,
        "wispr_mic_device": None,

        "whisper_model": "large-v3-turbo",
        "whisper_backend": "auto",  # "auto" (MLX on Apple Silicon, else faster-whisper), "mlx", or "faster-whisper"
        "whisper_device": "auto",  # "cuda" (recommended if available), "auto", or "cpu" (only for faster-whisper)
        # int8_float16: 8-bit weight quantization with FP16 activations.
        # Verified across RTX 30/40/50 series, ~3 GB VRAM savings (frees room
        # for Ollama LLM), 1.5-2× speed, <0.2% WER vs float16. Fallback chain
        # downgrades to plain int8 / float32 if unsupported.
        "whisper_compute_type": "int8_float16",
        "whisper_vad": True,
        "whisper_min_confidence": 0.3,  # Filter low-confidence segments (hallucinations)
        # 0.5 — middle-ground: aggressive enough to filter most YouTube
        # residue ("Thank you", "Ciao") on silence, lenient enough to keep
        # short quiet legitimate speech. We tried 0.6 (Calm-Whisper paper)
        # but it filtered borderline quiet Greek phonemes from a dynamic mic.
        # The downstream Calm-Whisper exact-match blocklist catches anything
        # this leaks through.
        "whisper_no_speech_threshold": 0.5,
        "whisper_min_audio_duration": 0.15,
        "whisper_min_word_length": 1,
        # 1.35 (was 2.0) — much stricter compression-ratio guard. Whisper's
        # canonical 2.0 was tuned for long-form transcription; for short
        # command-style utterances, anything compressing more than ~1.35× is
        # almost certainly looping ("don't don't don't"). Per AI #3 research.
        "whisper_compression_ratio_threshold": 1.35,
        # Greedy decoding (beam_size=1). Two reasons: (a) command-style ASR
        # processes short utterances independently — beam search just explores
        # more "plausible" hallucinations on silence; (b) known GSP firmware
        # crash with Blackwell + multi-stream beam search.
        "whisper_beam_size": 1,
        # Temperature fallback schedule. Whisper retries decoding with these
        # temperatures when the primary (T=0.0) hits compression/no-speech
        # gates. Climbing schedule helps the model break out of repetition
        # loops on ambiguous input.
        "whisper_temperature_fallback": [0.0, 0.2, 0.4],
        # faster-whisper API: drops segments where Whisper appears to be
        # hallucinating during silence (heuristic based on token timing vs
        # audio energy). 2.0 is the conservative production default.
        "whisper_hallucination_silence_threshold": 2.0,
        # Whisper's `initial_prompt` is interpreted as "the start of the
        # transcript the model has been writing" — NOT as instructions. A
        # long or instruction-style prompt (e.g. listing vocabulary words)
        # gets memorised and echoed back as transcription. See:
        #   - medium.com/axinc-ai/prompt-engineering-in-whisper-6bb18003562d
        #   - openai/whisper Discussion #1150
        # Default to None: rely on the `language=` hint (sticky language
        # lock + `whisper_default_language` bootstrap) for EL/EN bias.
        # A user may set a SHORT speech-style prompt (e.g. "Γεια σου Jarvis.")
        # but never an instructional one.
        "whisper_initial_prompt": None,
        "whisper_allowed_languages": ["el", "en"],
        # Force this language on every transcribe call BEFORE the sticky
        # lock has consensus (i.e. the first few utterances). None = auto-
        # detect. Recommended: set to "el" if your daily use is primarily
        # Greek, or "en" if primarily English — it removes the first-
        # utterance ambiguity that can land Whisper on a wrong language
        # (e.g. detecting Greek as German on quiet input).
        "whisper_default_language": None,

        # Voice Activity Detection (VAD)
        "vad_enabled": True,
        # Silero is the neural VAD default — Picovoice 2026 benchmark shows
        # ~4× lower error rate than WebRTC at the same false-positive rate,
        # especially for speech onset (fixes "missing the start of the word").
        # Auto-falls back to webrtc when silero-vad isn't installed.
        "vad_backend": "silero",
        "vad_aggressiveness": 2,                # webrtc backend only
        # Silero hysteresis. Earlier we tried 0.7/0.4 (strict onset) — that
        # was too aggressive for the user's PD200X dynamic mic + Greek
        # speech: unaspirated plosives (π, τ, κ) and fricatives (θ, φ, χ,
        # σ) sit at Silero probability ~0.5-0.6 on that mic, so a 0.7 onset
        # rejected most of every Greek utterance. 0.5 onset / 0.3 offset
        # is gentler: lets quiet Greek phonemes start an utterance, then
        # stays open through softer trailing sounds.
        "vad_silero_threshold": 0.5,            # onset — moderate
        "vad_silero_neg_threshold": 0.3,        # offset — permissive (small hysteresis spread)
        # The following three fields are RESERVED for a future migration to
        # silero-vad's get_speech_timestamps() chunked API. The current
        # per-frame SileroVAD wrapper does not consume them — they have no
        # effect at runtime today. Documented so users who set them know.
        "vad_silero_min_speech_ms": 300,
        "vad_silero_min_silence_ms": 400,
        "vad_silero_speech_pad_ms": 400,
        "vad_frame_ms": 20,
        # 400 ms pre-roll buffers more lead-in audio so VAD-triggered
        # transcription includes the first phoneme. No latency cost — the
        # pre-roll fills in parallel and is consumed only when speech begins.
        "vad_pre_roll_ms": 400,
        # 1200 (was 800) — give the user more breathing room mid-sentence
        # before the listener finalises an utterance. With endpoint at 800 ms,
        # natural conversational pauses ("Jarvis,......ποιος είναι...") were
        # triggering early termination, especially for bilingual code-switching
        # where the user may pause to translate. Costs 400 ms of extra latency
        # after the user's LAST word — acceptable trade-off for far fewer
        # mid-sentence cuts.
        "endpoint_silence_ms": 1200,
        "max_utterance_ms": 12000,
        "tts_max_utterance_ms": 3000,  # Shorter timeout during TTS for quick stop detection

        # Microphone input preprocessing — AGC is OPT-IN.
        # Whisper's feature extractor already normalises the mel spectrogram
        # ([-1, 1], near-zero mean), so external AGC duplicates that work
        # and the soft-clip changes the energy envelope the encoder expects.
        # Worse, in quiet moments the AGC amplifies the noise floor ~10×
        # which lifts background hum into the VAD trigger band. We saw
        # measurable regressions in real-world Greek transcription when
        # this was on, so it now defaults off. Enable only when the mic
        # genuinely under-drives at normal positioning. See:
        #   - huggingface.co/docs/transformers/en/model_doc/whisper
        "mic_agc_enabled": False,
        "mic_agc_target_rms": 0.1,
        "mic_agc_max_gain": 10.0,

        # UI/UX Features
        "tune_enabled": True,
        "hot_window_enabled": True,
        "hot_window_seconds": 3.0,
        "echo_energy_threshold": 2.0,
        "echo_tolerance": 0.3,  # Time tolerance for echo detection timing

        # Audio Wake Word Detection
        # Intent Judge (LLM-based intent classification)
        # Always used when available, falls back to simple wake word detection
        "llm_thinking_enabled": False,  # Enable thinking/reasoning mode for chat (slower but may improve quality)
        "intent_judge_model": "gemma4:e2b",  # Model for intent judging (needs reasoning ability)
        "intent_judge_timeout_sec": 15.0,  # Max time to wait for intent judge response
        "intent_judge_thinking_enabled": False,  # Enable thinking for intent judge (adds latency to wake detection)

        # Transcript Buffer - used for both retention and context passed to intent judge
        # 120s (2 min) provides enough ambient speech context for intent judging
        # in group conversations. Separate from dialogue memory.
        "transcript_buffer_duration_sec": 120.0,

        # Reminders (time-triggered spoken + tray reminders)
        "reminders_enabled": True,
        "reminder_check_interval_sec": 2.0,
        "reminder_grace_window_sec": 300.0,
        "reminder_default_snooze_min": 5,
        "reminder_speak_on_fire": True,
        "reminder_parse_timeout_sec": 8.0,

        # Memory lifecycle (TTL / pruning / monthly consolidation)
        "memory_ttl_enabled": False,
        "memory_ttl_default_days": 0,
        "memory_weekly_prune_enabled": True,
        "memory_weekly_prune_min_age_days": 30,
        "memory_monthly_consolidation_enabled": True,
        "memory_archive_delete_raw": True,

        # Memory & Dialogue
        # dialogue_memory_timeout drives the short-term memory window AND the forced
        # diary update interval. After a diary update, enrichment retrieves older context.
        "dialogue_memory_timeout": 300.0,
        "memory_enrichment_max_results": 3,
        "memory_enrichment_source": "all",  # "all", "diary", or "graph"
        # Keep the memory-injection window open for the first 4 agentic turns
        # before dropping late-arriving recalled memory.
        "memory_injection_max_turns": 4,
        # Tool carryover: cap re-injected prior tool turns + chars per entry.
        "tool_carryover_max_turns": 2,
        "tool_carryover_per_entry_chars": 1200,
        # None = auto (on for small models ≤7B, off for large). Set true/false to force.
        "memory_digest_enabled": None,
        # Distil raw tool results (e.g. webSearch extracts) into a short
        # attributed fact note for small models. Defaults to off: the extra
        # None = auto (on for small models ≤7B, off for large). Set true/false to force.
        # Auto-on for small models mitigates fetch_web_page's 50k-char payloads
        # blowing the 8192 num_ctx window before the main model sees them.
        "tool_result_digest_enabled": None,

        # Agentic Loop
        "agentic_max_turns": 8,
        "tool_selection_strategy": "llm",
        # Empty string = reuse intent_judge_model (small, fast, already warm
        # for wake-word paths), falling back to ollama_chat_model only if the
        # judge model isn't set. Override to decouple routing from both —
        # useful when you want routing on a dedicated smaller model.
        "tool_router_model": "",
        # Empty string = reuse intent_judge_model, falling through to
        # ollama_chat_model only if the judge isn't set. Override to pin the
        # evaluator to a dedicated small/fast model.
        "evaluator_model": "",
        # None = auto (on for small models, off for large). Set true/false to force.
        "evaluator_enabled": None,
        # Cap the number of toolSearchTool invocations per reply.
        "tool_search_max_calls": 3,
        # Cap the number of evaluator-driven nudges per reply.
        "evaluator_nudge_max": 2,
        # Task-list planner (see src/jarvis/reply/planner.spec.md). Empty
        # model string = reuse tool_router_model → intent_judge_model →
        # ollama_chat_model.
        "planner_model": "",
        "planner_enabled": True,
        "planner_timeout_sec": 6.0,

        # Stop Commands
        "stop_commands": ["stop", "quiet", "shush", "silence", "enough", "shut up"],
        "stop_command_fuzzy_ratio": 0.8,

        # Location Services
        "location_enabled": True,
        "location_cache_minutes": 60,
        "location_ip_address": None,
        "location_auto_detect": True,
        # When behind CGNAT (100.64.0.0/10), attempt a privacy-light external DNS query to discover true public IP.
        # Uses a single OpenDNS resolver lookup of myip.opendns.com over DNS (no HTTP services). Disable to avoid any external request.
        "location_cgnat_resolve_public_ip": True,

        # Web Search
        "web_search_enabled": True,
        "brave_search_api_key": "",
        "wikipedia_fallback_enabled": True,

        # Vision & Screen Interaction Engine (off by default)
        "vision_enabled": False,
        "vision_model": "qwen2.5vl:3b",
        "vision_default_mode": "assist",
        "vision_auto_whitelist": ["notepad.exe", "WindowsTerminal.exe", "explorer.exe", "spotify.exe"],
        "vision_auto_blacklist": ["chrome.exe", "msedge.exe", "firefox.exe", "1password.exe", "keepass.exe"],
        "vision_pending_ttl_sec": 120,
        "vision_keep_alive": "5m",
        "vision_max_width": 1280,
        "vision_timeout_sec": 20.0,

        # Dictation (hold-to-dictate, WisprFlow-like)
        "dictation_enabled": True,
        "dictation_hotkey": _default_dictation_hotkey(),
        "dictation_filler_removal": False,
        "dictation_thinking_enabled": False,  # Enable thinking for dictation filler removal (adds latency)
        "dictation_custom_dictionary": [],

        # MCP Integration (external servers Jarvis can use). No defaults.
        "mcps": {},
    }


def export_example_config(include_db_path: bool = False) -> Dict[str, Any]:
    """Returns example config suitable for JSON export (with adjusted db_path)."""
    config = get_default_config().copy()
    if not include_db_path:
        # Use a user-friendly path for examples
        config["db_path"] = "~/.local/share/jarvis/jarvis.db"
    return config


def load_settings() -> Settings:
    # Load environment for debug toggles and optional config file path only
    load_dotenv(override=False)

    # Resolve config path
    cfg_path_env = os.environ.get("JARVIS_CONFIG_PATH")
    cfg_path = Path(cfg_path_env).expanduser() if cfg_path_env else default_config_path()
    cfg_dir = cfg_path.parent
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Load JSON configuration (non-debug settings)
    cfg_json = _load_json(cfg_path)

    # Apply config migrations for version upgrades
    if cfg_json:
        cfg_json = _migrate_config(cfg_path, cfg_json)

    # Get defaults and merge with JSON (JSON wins)
    defaults = get_default_config()
    merged: Dict[str, Any] = {**defaults, **cfg_json}

    # Build Settings. Some fields support env var overrides.
    # Env overrides: JARVIS_VOICE_DEBUG, JARVIS_WHISPER_BACKEND
    voice_debug = os.environ.get("JARVIS_VOICE_DEBUG", "0") == "1"
    # Audio dump is off by default. Enable via config.json OR
    # JARVIS_VOICE_DEBUG_SAVE_AUDIO=1 env var for a one-shot diagnostic session.
    voice_debug_save_audio = (
        os.environ.get("JARVIS_VOICE_DEBUG_SAVE_AUDIO", "0") == "1"
        or bool(merged.get("voice_debug_save_audio", False))
    )

    # Normalize/convert fields
    db_path = str(merged.get("db_path") or _default_db_path())
    sqlite_vss_path = merged.get("sqlite_vss_path")
    allowlist_bundles = _ensure_list(merged.get("allowlist_bundles"))

    ollama_base_url = str(merged.get("ollama_base_url"))
    ollama_embed_model = str(merged.get("ollama_embed_model"))
    ollama_chat_model = str(merged.get("ollama_chat_model"))
    use_stdin = bool(merged.get("use_stdin", False))
    active_profiles = _ensure_list(merged.get("active_profiles"))
    tts_enabled = bool(merged.get("tts_enabled", True))
    tts_engine = str(merged.get("tts_engine", "piper")).lower()
    if tts_engine not in ("piper", "chatterbox"):
        tts_engine = "piper"  # Default to piper if invalid value
    tts_voice_val = merged.get("tts_voice")
    tts_voice = None if tts_voice_val in (None, "", "null") else str(tts_voice_val)
    tts_rate_val = merged.get("tts_rate")
    try:
        tts_rate = None if tts_rate_val in (None, "", "null") else int(tts_rate_val)
    except Exception:
        tts_rate = None
    tts_chatterbox_device = str(merged.get("tts_chatterbox_device", "cuda")).lower()
    if tts_chatterbox_device not in ("cuda", "auto", "cpu"):
        tts_chatterbox_device = "cuda"  # Default to cuda if invalid value
    tts_chatterbox_audio_prompt_val = merged.get("tts_chatterbox_audio_prompt")
    tts_chatterbox_audio_prompt = None if tts_chatterbox_audio_prompt_val in (None, "", "null") else str(tts_chatterbox_audio_prompt_val)
    tts_chatterbox_exaggeration = float(merged.get("tts_chatterbox_exaggeration", 0.5))
    tts_chatterbox_cfg_weight = float(merged.get("tts_chatterbox_cfg_weight", 0.5))
    tts_chatterbox_steps = int(merged.get("tts_chatterbox_steps", 300))
    tts_output_device_val = merged.get("tts_output_device", None)
    if tts_output_device_val in (None, "", "null"):
        tts_output_device = None
    else:
        tts_output_device = str(tts_output_device_val)
    tts_streaming_enabled = bool(merged.get("tts_streaming_enabled", True))

    # Piper TTS settings
    tts_piper_model_path_val = merged.get("tts_piper_model_path")
    tts_piper_model_path = None if tts_piper_model_path_val in (None, "", "null") else str(tts_piper_model_path_val)
    tts_piper_speaker_val = merged.get("tts_piper_speaker")
    try:
        tts_piper_speaker = None if tts_piper_speaker_val in (None, "", "null") else int(tts_piper_speaker_val)
    except Exception:
        tts_piper_speaker = None
    tts_piper_length_scale = float(merged.get("tts_piper_length_scale", 0.65))
    tts_piper_noise_scale = float(merged.get("tts_piper_noise_scale", 0.8))
    tts_piper_noise_w = float(merged.get("tts_piper_noise_w", 1.0))
    tts_piper_sentence_silence = float(merged.get("tts_piper_sentence_silence", 0.2))

    voice_device_val = merged.get("voice_device")
    voice_device = None if voice_device_val in (None, "", "default", "system") else str(voice_device_val)

    # Audio device selection (endpoint-id scheme). Normalise each to a string;
    # empty / null collapses to "" so downstream code treats "" uniformly as
    # "not selected" (never None).
    def _audio_str(key: str) -> str:
        val = merged.get(key, "")
        if val in (None, "", "null"):
            return ""
        return str(val)

    audio_output_endpoint_id = _audio_str("audio_output_endpoint_id")
    audio_output_name = _audio_str("audio_output_name")
    audio_input_endpoint_id = _audio_str("audio_input_endpoint_id")
    audio_input_name = _audio_str("audio_input_name")
    voice_block_seconds = float(merged.get("voice_block_seconds", 4.0))
    voice_collect_seconds = float(merged.get("voice_collect_seconds", 2.5))
    voice_max_collect_seconds = float(merged.get("voice_max_collect_seconds", 60.0))
    wake_word = str(merged.get("wake_word", "jarvis")).strip().lower()
    wake_aliases = [a.strip().lower() for a in _ensure_list(merged.get("wake_aliases")) if a.strip()]
    wake_fuzzy_ratio = float(merged.get("wake_fuzzy_ratio", 0.78))
    # STT backend selection (Phase B of Wispr-bridge rollout)
    stt_backend = str(merged.get("stt_backend", "whisper")).lower()
    if stt_backend not in ("whisper", "wispr"):
        stt_backend = "whisper"  # Defensive default
    wispr_wake_model = str(merged.get("wispr_wake_model", "hey_jarvis_v0.1"))
    try:
        wispr_wake_threshold = float(merged.get("wispr_wake_threshold", 0.1))
    except (TypeError, ValueError):
        wispr_wake_threshold = 0.1
    try:
        wispr_wake_gain = float(merged.get("wispr_wake_gain", 1.0))
    except (TypeError, ValueError):
        wispr_wake_gain = 1.0
    try:
        wispr_wake_rms_floor = float(merged.get("wispr_wake_rms_floor", 0.0))
    except (TypeError, ValueError):
        wispr_wake_rms_floor = 0.0
    try:
        wispr_silence_ms = int(merged.get("wispr_silence_ms", 800))
    except (TypeError, ValueError):
        wispr_silence_ms = 800
    try:
        wispr_min_dictation_sec = float(merged.get("wispr_min_dictation_sec", 2.0))
    except (TypeError, ValueError):
        wispr_min_dictation_sec = 2.0
    try:
        wispr_max_dictation_sec = int(merged.get("wispr_max_dictation_sec", 30))
    except (TypeError, ValueError):
        wispr_max_dictation_sec = 30
    try:
        wispr_clipboard_wait_sec = float(merged.get("wispr_clipboard_wait_sec", 6.0))
    except (TypeError, ValueError):
        wispr_clipboard_wait_sec = 6.0
    try:
        wispr_hot_window_sec = float(merged.get("wispr_hot_window_sec", 0.0))
    except (TypeError, ValueError):
        wispr_hot_window_sec = 0.0
    wispr_suppress_autotype = bool(merged.get("wispr_suppress_autotype", True))
    wispr_mic_device_val = merged.get("wispr_mic_device", None)
    if wispr_mic_device_val in (None, "", "null"):
        wispr_mic_device = None
    else:
        # Accept either int index or string substring of device name
        try:
            wispr_mic_device = int(wispr_mic_device_val)
        except (TypeError, ValueError):
            wispr_mic_device = str(wispr_mic_device_val)

    # Closed-loop sync + guards
    wispr_closed_loop_enabled = bool(merged.get("wispr_closed_loop_enabled", True))
    _combo_raw = merged.get("wispr_hands_free_combo", ["ctrl", "cmd", "space"])
    if isinstance(_combo_raw, (list, tuple)) and _combo_raw:
        wispr_hands_free_combo = [str(k).strip().lower() for k in _combo_raw if str(k).strip()]
        if not wispr_hands_free_combo:
            wispr_hands_free_combo = ["ctrl", "cmd", "space"]
    else:
        wispr_hands_free_combo = ["ctrl", "cmd", "space"]
    try:
        wispr_min_tap_gap_sec = float(merged.get("wispr_min_tap_gap_sec", 0.5))
    except (TypeError, ValueError):
        wispr_min_tap_gap_sec = 0.5
    try:
        wispr_confirm_timeout_sec = float(merged.get("wispr_confirm_timeout_sec", 1.2))
    except (TypeError, ValueError):
        wispr_confirm_timeout_sec = 1.2
    try:
        wispr_clipboard_grace_sec = float(merged.get("wispr_clipboard_grace_sec", 2.0))
    except (TypeError, ValueError):
        wispr_clipboard_grace_sec = 2.0
    try:
        wispr_erase_max_chars = int(merged.get("wispr_erase_max_chars", 300))
    except (TypeError, ValueError):
        wispr_erase_max_chars = 300
    wispr_barge_in_interrupt = bool(merged.get("wispr_barge_in_interrupt", True))

    whisper_model = str(merged.get("whisper_model", "large-v3-turbo"))
    whisper_backend = os.environ.get("JARVIS_WHISPER_BACKEND", "").lower() or str(merged.get("whisper_backend", "auto")).lower()
    if whisper_backend not in ("auto", "mlx", "faster-whisper"):
        whisper_backend = "auto"
    whisper_device = str(merged.get("whisper_device", "auto")).lower()
    if whisper_device not in ("cuda", "auto", "cpu"):
        whisper_device = "auto"
    whisper_compute_type = str(merged.get("whisper_compute_type", "int8_float16"))
    whisper_vad = bool(merged.get("whisper_vad", True))
    # New: compression-ratio threshold, initial prompt, allowed languages.
    _crt_raw = merged.get("whisper_compression_ratio_threshold", 1.35)
    whisper_compression_ratio_threshold: Optional[float]
    if _crt_raw in (None, "", "null"):
        whisper_compression_ratio_threshold = None
    else:
        try:
            whisper_compression_ratio_threshold = float(_crt_raw)
        except (TypeError, ValueError):
            whisper_compression_ratio_threshold = 1.35
    _ip_raw = merged.get("whisper_initial_prompt", None)
    whisper_initial_prompt: Optional[str]
    if _ip_raw in (None, "", "null"):
        whisper_initial_prompt = None
    else:
        whisper_initial_prompt = str(_ip_raw)
    _allowed_raw = merged.get("whisper_allowed_languages", ["el", "en"])
    whisper_allowed_languages = (
        [str(x).strip().lower() for x in _allowed_raw if str(x).strip()]
        if isinstance(_allowed_raw, list)
        else ["el", "en"]
    )
    # Language priority — first language wins fallback ties. Defaults to
    # whisper_allowed_languages (in order), so user just needs to put their
    # primary language first in `whisper_allowed_languages` to fix Greek
    # mis-detection.
    _priority_raw = merged.get("language_priority", whisper_allowed_languages)
    language_priority = (
        [str(x).strip().lower() for x in _priority_raw if str(x).strip()]
        if isinstance(_priority_raw, list)
        else list(whisper_allowed_languages)
    )
    _default_lang_raw = merged.get("whisper_default_language", None)
    whisper_default_language: Optional[str]
    if _default_lang_raw in (None, "", "null", "auto"):
        whisper_default_language = None
    else:
        whisper_default_language = str(_default_lang_raw).strip().lower() or None
    # Decoder strategy knobs (Phase A).
    try:
        whisper_beam_size = max(1, int(merged.get("whisper_beam_size", 1)))
    except (TypeError, ValueError):
        whisper_beam_size = 1
    _temp_raw = merged.get("whisper_temperature_fallback", [0.0, 0.2, 0.4])
    if isinstance(_temp_raw, list) and _temp_raw:
        try:
            whisper_temperature_fallback = [max(0.0, float(t)) for t in _temp_raw]
        except (TypeError, ValueError):
            whisper_temperature_fallback = [0.0, 0.2, 0.4]
    else:
        # Single float supplied — wrap into a one-element schedule.
        try:
            whisper_temperature_fallback = [max(0.0, float(_temp_raw))]
        except (TypeError, ValueError):
            whisper_temperature_fallback = [0.0, 0.2, 0.4]
    _hst_raw = merged.get("whisper_hallucination_silence_threshold", 2.0)
    whisper_hallucination_silence_threshold: Optional[float]
    if _hst_raw in (None, "", "null"):
        whisper_hallucination_silence_threshold = None
    else:
        try:
            whisper_hallucination_silence_threshold = float(_hst_raw)
        except (TypeError, ValueError):
            whisper_hallucination_silence_threshold = 2.0
    voice_min_energy = float(merged.get("voice_min_energy", 0.02))
    vad_enabled = bool(merged.get("vad_enabled", True))
    vad_backend = str(merged.get("vad_backend", "silero")).strip().lower()
    if vad_backend not in ("silero", "webrtc"):
        vad_backend = "silero"
    vad_aggressiveness = int(merged.get("vad_aggressiveness", 2))
    try:
        vad_silero_threshold = float(merged.get("vad_silero_threshold", 0.5))
    except (TypeError, ValueError):
        vad_silero_threshold = 0.5
    # Clamp Silero threshold into the [0, 1] probability range.
    if vad_silero_threshold < 0.0:
        vad_silero_threshold = 0.0
    elif vad_silero_threshold > 1.0:
        vad_silero_threshold = 1.0
    try:
        vad_silero_neg_threshold = float(merged.get("vad_silero_neg_threshold", 0.3))
    except (TypeError, ValueError):
        vad_silero_neg_threshold = 0.3
    # Hysteresis sanity: offset MUST be <= onset, else collapse to no hysteresis.
    if vad_silero_neg_threshold > vad_silero_threshold:
        vad_silero_neg_threshold = vad_silero_threshold
    try:
        vad_silero_min_speech_ms = max(0, int(merged.get("vad_silero_min_speech_ms", 300)))
    except (TypeError, ValueError):
        vad_silero_min_speech_ms = 300
    try:
        vad_silero_min_silence_ms = max(0, int(merged.get("vad_silero_min_silence_ms", 400)))
    except (TypeError, ValueError):
        vad_silero_min_silence_ms = 400
    try:
        vad_silero_speech_pad_ms = max(0, int(merged.get("vad_silero_speech_pad_ms", 400)))
    except (TypeError, ValueError):
        vad_silero_speech_pad_ms = 400
    vad_frame_ms = int(merged.get("vad_frame_ms", 20))
    vad_pre_roll_ms = int(merged.get("vad_pre_roll_ms", 400))
    endpoint_silence_ms = int(merged.get("endpoint_silence_ms", 1200))
    max_utterance_ms = int(merged.get("max_utterance_ms", 12000))
    tts_max_utterance_ms = int(merged.get("tts_max_utterance_ms", 3000))
    mic_agc_enabled = bool(merged.get("mic_agc_enabled", False))
    try:
        mic_agc_target_rms = float(merged.get("mic_agc_target_rms", 0.1))
    except (TypeError, ValueError):
        mic_agc_target_rms = 0.1
    try:
        mic_agc_max_gain = float(merged.get("mic_agc_max_gain", 10.0))
    except (TypeError, ValueError):
        mic_agc_max_gain = 10.0
    sample_rate = int(merged.get("sample_rate", 16000))
    tune_enabled = bool(merged.get("tune_enabled", True))
    hot_window_enabled = bool(merged.get("hot_window_enabled", True))
    hot_window_seconds = float(merged.get("hot_window_seconds", 3.0))
    echo_energy_threshold = float(merged.get("echo_energy_threshold", 2.0))
    echo_tolerance = float(merged.get("echo_tolerance", 0.3))

    # Intent Judge - always used when available
    intent_judge_model = str(merged.get("intent_judge_model", "gemma4:e2b"))
    intent_judge_timeout_sec = float(merged.get("intent_judge_timeout_sec", 10.0))

    # Transcript Buffer - ambient speech context for intent judge (separate from dialogue)
    transcript_buffer_duration_sec = float(merged.get("transcript_buffer_duration_sec", 120.0))

    # Reminders
    reminders_enabled = bool(merged.get("reminders_enabled", True))
    reminder_check_interval_sec = max(1.0, min(5.0, float(merged.get("reminder_check_interval_sec", 2.0))))
    reminder_grace_window_sec = max(0.0, float(merged.get("reminder_grace_window_sec", 300.0)))
    reminder_default_snooze_min = max(1, int(merged.get("reminder_default_snooze_min", 5)))
    reminder_speak_on_fire = bool(merged.get("reminder_speak_on_fire", True))
    reminder_parse_timeout_sec = max(1.0, float(merged.get("reminder_parse_timeout_sec", 8.0)))

    # Memory lifecycle
    memory_ttl_enabled = bool(merged.get("memory_ttl_enabled", False))
    memory_ttl_default_days = max(0, int(merged.get("memory_ttl_default_days", 0)))
    memory_weekly_prune_enabled = bool(merged.get("memory_weekly_prune_enabled", True))
    memory_weekly_prune_min_age_days = max(1, int(merged.get("memory_weekly_prune_min_age_days", 30)))
    memory_monthly_consolidation_enabled = bool(merged.get("memory_monthly_consolidation_enabled", True))
    memory_archive_delete_raw = bool(merged.get("memory_archive_delete_raw", True))

    # Dialogue memory window and forced diary update share this duration
    dialogue_memory_timeout = float(merged.get("dialogue_memory_timeout", 300.0))
    memory_enrichment_max_results = int(merged.get("memory_enrichment_max_results", 3))
    memory_enrichment_source = str(merged.get("memory_enrichment_source", "all")).lower()
    if memory_enrichment_source not in ("all", "diary", "graph"):
        memory_enrichment_source = "all"
    memory_injection_max_turns = max(1, int(merged.get("memory_injection_max_turns", 4)))
    tool_carryover_max_turns = max(0, int(merged.get("tool_carryover_max_turns", 2)))
    tool_carryover_per_entry_chars = max(200, int(merged.get("tool_carryover_per_entry_chars", 1200)))
    _digest_raw = merged.get("memory_digest_enabled", None)
    memory_digest_enabled: Optional[bool]
    if _digest_raw is None:
        memory_digest_enabled = None
    else:
        memory_digest_enabled = bool(_digest_raw)
    _tool_digest_raw = merged.get("tool_result_digest_enabled", None)
    tool_result_digest_enabled: Optional[bool]
    if _tool_digest_raw is None:
        tool_result_digest_enabled = None
    else:
        tool_result_digest_enabled = bool(_tool_digest_raw)
    agentic_max_turns = int(merged.get("agentic_max_turns", 8))
    tool_selection_strategy = str(merged.get("tool_selection_strategy", "llm")).lower()
    if tool_selection_strategy not in ("all", "keyword", "embedding", "llm"):
        tool_selection_strategy = "llm"
    tool_router_model = str(merged.get("tool_router_model", "") or "").strip()
    evaluator_model = str(merged.get("evaluator_model", "") or "").strip()
    _eval_raw = merged.get("evaluator_enabled", None)
    evaluator_enabled: Optional[bool]
    if _eval_raw is None:
        evaluator_enabled = None
    else:
        evaluator_enabled = bool(_eval_raw)
    planner_model = str(merged.get("planner_model", "") or "").strip()
    planner_enabled = bool(merged.get("planner_enabled", True))
    try:
        planner_timeout_sec = float(merged.get("planner_timeout_sec", 6.0))
    except (TypeError, ValueError):
        planner_timeout_sec = 6.0
    try:
        tool_search_max_calls = int(merged.get("tool_search_max_calls", 3))
    except (TypeError, ValueError):
        tool_search_max_calls = 3
    if tool_search_max_calls < 0:
        tool_search_max_calls = 0
    try:
        evaluator_nudge_max = int(merged.get("evaluator_nudge_max", 2))
    except (TypeError, ValueError):
        evaluator_nudge_max = 2
    if evaluator_nudge_max < 0:
        evaluator_nudge_max = 0
    location_enabled = bool(merged.get("location_enabled", True))
    location_cache_minutes = int(merged.get("location_cache_minutes", 60))
    location_ip_address_val = merged.get("location_ip_address")
    location_ip_address = None if location_ip_address_val in (None, "", "null") else str(location_ip_address_val)
    location_auto_detect = bool(merged.get("location_auto_detect", True))
    location_cgnat_resolve_public_ip = bool(merged.get("location_cgnat_resolve_public_ip", True))
    web_search_enabled = bool(merged.get("web_search_enabled", True))
    brave_search_api_key = str(merged.get("brave_search_api_key", "") or "").strip()
    wikipedia_fallback_enabled = bool(merged.get("wikipedia_fallback_enabled", True))
    vision_enabled = bool(merged.get("vision_enabled", False))
    vision_model = str(merged.get("vision_model", "qwen2.5vl:3b") or "qwen2.5vl:3b").strip()
    vision_default_mode = str(merged.get("vision_default_mode", "assist") or "assist").strip().lower()
    _vw = merged.get("vision_auto_whitelist", [])
    vision_auto_whitelist = list(_vw) if isinstance(_vw, list) else []
    _vb = merged.get("vision_auto_blacklist", [])
    vision_auto_blacklist = list(_vb) if isinstance(_vb, list) else []
    vision_pending_ttl_sec = int(merged.get("vision_pending_ttl_sec", 120) or 120)
    vision_keep_alive = str(merged.get("vision_keep_alive", "5m") or "5m").strip()
    _vmw = merged.get("vision_max_width", 1280)
    vision_max_width = int(_vmw) if isinstance(_vmw, (int, float)) and _vmw else None
    vision_timeout_sec = max(1.0, float(merged.get("vision_timeout_sec", 20.0) or 20.0))
    dictation_enabled = bool(merged.get("dictation_enabled", True))
    dictation_hotkey = str(merged.get("dictation_hotkey", _default_dictation_hotkey())).strip()
    dictation_filler_removal = bool(merged.get("dictation_filler_removal", False))
    raw_dict = merged.get("dictation_custom_dictionary", [])
    dictation_custom_dictionary = list(raw_dict) if isinstance(raw_dict, list) else []
    mcps = _ensure_dict(merged.get("mcps"))
    if not mcps:
        # Back-compat / UI-sync: config.json (and the React "Services" tab)
        # store servers as a LIST under `mcp_servers`
        # [{id, name, command, args, env}, ...], but the runtime wants a
        # DICT keyed by id with {command, args, env}. Without this conversion
        # cfg.mcps stays empty → "No MCP servers configured" → Spotify /
        # weather / gmail / etc. tools never load (e.g. "next track" cannot
        # actually control the player, so Jarvis says it can't help).
        _servers = merged.get("mcp_servers")
        if isinstance(_servers, list):
            for _srv in _servers:
                if isinstance(_srv, dict) and _srv.get("id") and _srv.get("command"):
                    mcps[str(_srv["id"])] = {
                        "command": _srv.get("command"),
                        "args": _srv.get("args", []),
                        "env": _srv.get("env", {}),
                    }
    whisper_min_confidence = float(merged.get("whisper_min_confidence", 0.4))
    whisper_no_speech_threshold = float(merged.get("whisper_no_speech_threshold", 0.5))
    whisper_min_audio_duration = float(merged.get("whisper_min_audio_duration", 0.3))
    whisper_min_word_length = int(merged.get("whisper_min_word_length", 2))
    llm_chat_timeout_sec = float(merged.get("llm_chat_timeout_sec", 180.0))
    llm_tools_timeout_sec = float(merged.get("llm_tools_timeout_sec", 300.0))
    llm_digest_timeout_sec = float(merged.get("llm_digest_timeout_sec", 8.0))
    llm_embedding_timeout_sec = float(merged.get("llm_embedding_timeout_sec", 60.0))
    llm_profile_select_timeout_sec = float(merged.get("llm_profile_select_timeout_sec", 30.0))
    llm_chat_max_tokens = int(merged.get("llm_chat_max_tokens", 512))
    llm_chat_temperature = float(merged.get("llm_chat_temperature", -1.0))

    return Settings(
        # Database & Storage
        db_path=db_path,
        sqlite_vss_path=sqlite_vss_path,

        # LLM & AI Models
        ollama_base_url=ollama_base_url,
        ollama_embed_model=ollama_embed_model,
        ollama_chat_model=ollama_chat_model,
        llm_chat_timeout_sec=llm_chat_timeout_sec,
        llm_tools_timeout_sec=llm_tools_timeout_sec,
        llm_digest_timeout_sec=llm_digest_timeout_sec,
        llm_embedding_timeout_sec=llm_embedding_timeout_sec,
        llm_profile_select_timeout_sec=llm_profile_select_timeout_sec,
        llm_chat_max_tokens=llm_chat_max_tokens,
        llm_chat_temperature=llm_chat_temperature,

        # Profiles & Behavior
        active_profiles=active_profiles,
        use_stdin=use_stdin,
        voice_debug=voice_debug,
        voice_debug_save_audio=voice_debug_save_audio,

        # Screen Capture
        allowlist_bundles=allowlist_bundles,

        # Text-to-Speech
        tts_enabled=tts_enabled,
        tts_engine=tts_engine,
        tts_voice=tts_voice,
        tts_rate=tts_rate,
        tts_chatterbox_device=tts_chatterbox_device,
        tts_chatterbox_audio_prompt=tts_chatterbox_audio_prompt,
        tts_chatterbox_exaggeration=tts_chatterbox_exaggeration,
        tts_chatterbox_cfg_weight=tts_chatterbox_cfg_weight,
        tts_chatterbox_steps=tts_chatterbox_steps,
        tts_output_device=tts_output_device,
        tts_streaming_enabled=tts_streaming_enabled,

        # Piper TTS
        tts_piper_model_path=tts_piper_model_path,
        tts_piper_speaker=tts_piper_speaker,
        tts_piper_length_scale=tts_piper_length_scale,
        tts_piper_noise_scale=tts_piper_noise_scale,
        tts_piper_noise_w=tts_piper_noise_w,
        tts_piper_sentence_silence=tts_piper_sentence_silence,

        # Voice Input & Audio
        voice_device=voice_device,
        sample_rate=sample_rate,
        voice_min_energy=voice_min_energy,

        # Audio Device Selection (endpoint-id scheme)
        audio_output_endpoint_id=audio_output_endpoint_id,
        audio_output_name=audio_output_name,
        audio_input_endpoint_id=audio_input_endpoint_id,
        audio_input_name=audio_input_name,

        # Voice Collection & Timing
        voice_block_seconds=voice_block_seconds,
        voice_collect_seconds=voice_collect_seconds,
        voice_max_collect_seconds=voice_max_collect_seconds,

        # Wake Word Detection
        wake_word=wake_word,
        wake_aliases=wake_aliases,
        wake_fuzzy_ratio=wake_fuzzy_ratio,

        # STT backend selection + Wispr Flow bridge settings
        stt_backend=stt_backend,
        wispr_wake_model=wispr_wake_model,
        wispr_wake_threshold=wispr_wake_threshold,
        wispr_wake_gain=wispr_wake_gain,
        wispr_wake_rms_floor=wispr_wake_rms_floor,
        wispr_silence_ms=wispr_silence_ms,
        wispr_min_dictation_sec=wispr_min_dictation_sec,
        wispr_max_dictation_sec=wispr_max_dictation_sec,
        wispr_clipboard_wait_sec=wispr_clipboard_wait_sec,
        wispr_hot_window_sec=wispr_hot_window_sec,
        wispr_suppress_autotype=wispr_suppress_autotype,
        wispr_mic_device=wispr_mic_device,
        wispr_closed_loop_enabled=wispr_closed_loop_enabled,
        wispr_hands_free_combo=wispr_hands_free_combo,
        wispr_min_tap_gap_sec=wispr_min_tap_gap_sec,
        wispr_confirm_timeout_sec=wispr_confirm_timeout_sec,
        wispr_clipboard_grace_sec=wispr_clipboard_grace_sec,
        wispr_erase_max_chars=wispr_erase_max_chars,
        wispr_barge_in_interrupt=wispr_barge_in_interrupt,

        # Whisper Speech Recognition
        whisper_model=whisper_model,
        whisper_backend=whisper_backend,
        whisper_device=whisper_device,
        whisper_compute_type=whisper_compute_type,
        whisper_vad=whisper_vad,
        whisper_min_confidence=whisper_min_confidence,
        whisper_no_speech_threshold=whisper_no_speech_threshold,
        whisper_min_audio_duration=whisper_min_audio_duration,
        whisper_min_word_length=whisper_min_word_length,
        whisper_compression_ratio_threshold=whisper_compression_ratio_threshold,
        whisper_initial_prompt=whisper_initial_prompt,
        whisper_allowed_languages=whisper_allowed_languages,
        language_priority=language_priority,
        whisper_default_language=whisper_default_language,
        whisper_beam_size=whisper_beam_size,
        whisper_temperature_fallback=whisper_temperature_fallback,
        whisper_hallucination_silence_threshold=whisper_hallucination_silence_threshold,

        # Voice Activity Detection (VAD)
        vad_enabled=vad_enabled,
        vad_backend=vad_backend,
        vad_aggressiveness=vad_aggressiveness,
        vad_silero_threshold=vad_silero_threshold,
        vad_silero_neg_threshold=vad_silero_neg_threshold,
        vad_silero_min_speech_ms=vad_silero_min_speech_ms,
        vad_silero_min_silence_ms=vad_silero_min_silence_ms,
        vad_silero_speech_pad_ms=vad_silero_speech_pad_ms,
        vad_frame_ms=vad_frame_ms,
        vad_pre_roll_ms=vad_pre_roll_ms,
        endpoint_silence_ms=endpoint_silence_ms,
        max_utterance_ms=max_utterance_ms,
        tts_max_utterance_ms=tts_max_utterance_ms,

        # Microphone preprocessing
        mic_agc_enabled=mic_agc_enabled,
        mic_agc_target_rms=mic_agc_target_rms,
        mic_agc_max_gain=mic_agc_max_gain,

        # UI/UX Features
        tune_enabled=tune_enabled,
        hot_window_enabled=hot_window_enabled,
        hot_window_seconds=hot_window_seconds,
        echo_energy_threshold=echo_energy_threshold,
        echo_tolerance=echo_tolerance,
        # Intent Judge - always used when available
        intent_judge_model=intent_judge_model,
        intent_judge_timeout_sec=intent_judge_timeout_sec,

        # Transcript Buffer
        transcript_buffer_duration_sec=transcript_buffer_duration_sec,

        # Reminders
        reminders_enabled=reminders_enabled,
        reminder_check_interval_sec=reminder_check_interval_sec,
        reminder_grace_window_sec=reminder_grace_window_sec,
        reminder_default_snooze_min=reminder_default_snooze_min,
        reminder_speak_on_fire=reminder_speak_on_fire,
        reminder_parse_timeout_sec=reminder_parse_timeout_sec,

        # Memory lifecycle
        memory_ttl_enabled=memory_ttl_enabled,
        memory_ttl_default_days=memory_ttl_default_days,
        memory_weekly_prune_enabled=memory_weekly_prune_enabled,
        memory_weekly_prune_min_age_days=memory_weekly_prune_min_age_days,
        memory_monthly_consolidation_enabled=memory_monthly_consolidation_enabled,
        memory_archive_delete_raw=memory_archive_delete_raw,

        # Memory & Dialogue
        dialogue_memory_timeout=dialogue_memory_timeout,
        memory_enrichment_max_results=memory_enrichment_max_results,
        memory_enrichment_source=memory_enrichment_source,
        memory_injection_max_turns=memory_injection_max_turns,
        tool_carryover_max_turns=tool_carryover_max_turns,
        tool_carryover_per_entry_chars=tool_carryover_per_entry_chars,
        memory_digest_enabled=memory_digest_enabled,
        tool_result_digest_enabled=tool_result_digest_enabled,
        agentic_max_turns=agentic_max_turns,
        tool_selection_strategy=tool_selection_strategy,
        tool_router_model=tool_router_model,
        evaluator_model=evaluator_model,
        evaluator_enabled=evaluator_enabled,
        tool_search_max_calls=tool_search_max_calls,
        evaluator_nudge_max=evaluator_nudge_max,
        planner_model=planner_model,
        planner_enabled=planner_enabled,
        planner_timeout_sec=planner_timeout_sec,

        # Location Services
        location_enabled=location_enabled,
        location_cache_minutes=location_cache_minutes,
        location_ip_address=location_ip_address,
        location_auto_detect=location_auto_detect,
        location_cgnat_resolve_public_ip=location_cgnat_resolve_public_ip,

        # Web Search
        web_search_enabled=web_search_enabled,
        brave_search_api_key=brave_search_api_key,
        wikipedia_fallback_enabled=wikipedia_fallback_enabled,

        # Vision
        vision_enabled=vision_enabled,
        vision_model=vision_model,
        vision_default_mode=vision_default_mode,
        vision_auto_whitelist=vision_auto_whitelist,
        vision_auto_blacklist=vision_auto_blacklist,
        vision_pending_ttl_sec=vision_pending_ttl_sec,
        vision_keep_alive=vision_keep_alive,
        vision_max_width=vision_max_width,
        vision_timeout_sec=vision_timeout_sec,

        # Dictation
        dictation_enabled=dictation_enabled,
        dictation_hotkey=dictation_hotkey,
        dictation_filler_removal=dictation_filler_removal,
        dictation_custom_dictionary=dictation_custom_dictionary,

        # MCP Integration
        mcps=mcps,
    )
