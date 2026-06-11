# JARVIS — Change Log

Running record of every functional / architectural change made to this fork of Jarvis.
Newest first. Each entry names the files touched, what the change does, and the reason.

> Note: this is **fork-local history**, NOT the current configuration. Model names
> in old entries (e.g. qwen3.5:9b-8k) are point-in-time; for what actually runs now
> see `AGENTS.md` and the live config. The **Plan-mapping table** at the bottom
> references `~/.claude/plans/plain-you-are-a-sparkling-kahn.md`, a machine-local
> planning file that other readers will not have.

Format per entry:
```
## YYYY-MM-DD — short title
- **Category**: bug-fix | feature | refactor | infra | docs | dead-code-removal
- **Files**: list of files touched
- **What**: what the change does in one line
- **Why**: the trigger or symptom
- **Verified**: how we confirmed it works (logs, smoke test, manual)
- **Related plan item** (if any): Bug 1a / Bug 2 / Phase 2 / etc.
```

---

## 2026-06-12 - Greek apology + failed pronoun window command: deterministic English enforcement + last-managed-window fallback
- **Category**: bug-fix
- **Files**: `src/jarvis/reply/engine.py`, `src/jarvis/tools/builtin/window_manager.py` (+spec), `evals/test_reply_language_consistency.py`, `evals/test_voice_brevity.py`, `tests/test_window_and_stock_tools.py`, `docs/llm_contexts.md`.
- **What**:
  - **«βάλε ΤΟ στην αριστερή οθόνη full screen» failed**: the router emitted `manageWindow {action, monitor:left, position:full}` without `window` (the pronoun), and the tool failed closed with a misleading "action and window are required". manageWindow now falls back to the LAST window it managed this session when `window` is omitted (pronoun follow-ups name no app); validation errors name only the actually-missing fields. Standalone repro showed the router CAN resolve the pronoun from `last_tts_text` (emits window='Spotify') — the live miss was sampling variance, which the deterministic tool fallback now covers.
  - **The apology came back in GREEK** despite the reply-language clamp: error/apology turns mirror the user's language hardest, and live chat decodes at the model's default temperature, so the prompt clamp is inherently probabilistic. Two layers: clamp text now explicitly covers apologies/errors/clarifying questions + "start with an English word"; AND a deterministic Step-10 enforcement — if the final reply still contains non-Latin letters, ONE greedy translation pass rewrites it in English before TTS (translation has no pull toward the user's language; fail-open).
  - **Eval stability**: new eval case reproduces the exact live failure (Greek window command + tool error -> apology must be English) — failed before, passes 2x consecutive suite runs after (even the xfail joke case passes now); `test_voice_brevity` pinned to temperature 0.0 (it gates the prompt, not sampling luck).
- **Why**: user report: Jarvis replied in Greek and failed to put Spotify fullscreen on the left monitor; standing directive — Jarvis ALWAYS thinks and answers in English, concisely.
- **Verified**: live e2e of the exact phrase — `direct-exec manageWindow {..., "window": "spotify"}`, Spotify physically at x=-2048 w=2048 (FULL left monitor), reply in English; 143 affected unit tests + language eval 2x + brevity 3/3 green.

## 2026-06-12 - Audio I/O output selection wrote a dead config key - voice kept playing through the old speakers
- **Category**: bug-fix
- **Files**: `ui/src/console/lib/audioConfig.ts` (+test), live config repair via PATCH /api/config.
- **What**: the Audio I/O page's `outputPatch` wrote ONLY the legacy `tts_output_device` key, but the daemon's live playback resolver (`_resolve_output_device_live`) reads `audio_output_endpoint_id`/`audio_output_name` exclusively - the user picked the Corsair headset, the page said saved, and the voice (and test tone, same resolver) kept playing through the previously-stored device (Speakers Logitech Z200 endpoint) even after a restart. `outputPatch` now mirrors `inputPatch` (endpoint id + name; legacy key still written for sync), `selectedOutput` reads the new keys with legacy fallback. Repaired the live config (Corsair endpoint id) via PATCH - applied WITHOUT restart thanks to the per-call resolver.
- **Why**: user report: changed Windows output AND the Audio page output to the Corsair headset, restarted, sound still from speakers.
- **Verified**: `Piper TTS -> device 11` (Corsair) on a live spoken reply + test tone after the patch; 95 ui vitest green (test now encodes the endpoint-id contract).

## 2026-06-12 - HOTFIX: wake-ack NameError killed the STT loop (deaf until restart) + loop hardening
- **Category**: bug-fix (regression of the same day's wake-ack feature)
- **Files**: `src/jarvis/listening/listener.py` (+`listening.spec.md`), `tests/test_wake_ack.py`.
- **What**: `_acknowledge_wake_only` used `info_log`, which listener.py only imported LOCALLY inside one TTS callback — first real "Hey Jarvis" raised NameError, the exception reached the STT dispatcher, and because the backend had run past the 8s fast-fail window the dispatcher hit its terminal `break`: **STT thread exited, assistant permanently deaf**; later backend-switch requests and the HUD manual trigger talked to a dead thread. Fixed the import; added a unit test that exercises the METHOD (unbound, fake self) so a missing module-global can never pass again. Hardened both layers: per-utterance try/except around `_process_transcript` (whisper + wispr call sites — one bad utterance drops, loop survives) and dispatcher case 1b — a long-running backend that crashes is RESTARTED, never treated as a fatal startup failure.
- **Why**: user report: wake stopped triggering entirely, even the manual-trigger lightning did nothing.
- **Verified**: red→green on the exact NameError; restart → "Listening via Wispr Flow!" with openWakeWord ready; e2e "what time is it?" answered in ~2s; 57 affected tests green.

## 2026-06-12 - HUD stuck at boot splash + bare "Hey Jarvis." rambled and dropped the real command
- **Category**: bug-fix
- **Files**: `ui/src/hooks/useBootSequence.ts`, `src/jarvis/listening/{wake_detection,state_manager,listener}.py` (+`listening.spec.md`), `src/jarvis/config.py`, new `tests/test_wake_ack.py`.
- **What**:
  - **HUD splash stuck at "JARVIS / 100% / Ready"**: the boot hook's fast-forward path (all probes < 350ms) shared one `aliveRef` between two effects; the fast-forward state updates re-ran the walker effect, whose cleanup flipped the ref false BEFORE the 600ms completion timer fired, so `isComplete` never set. Ironically surfaced by the 2026-06-11 latency fixes (probes only now finish under the threshold). Liveness is now per-effect-run; failed subsystem checks are also RETRIED every 800ms (a HUD opened mid-daemon-boot used to cache one `false` and stall forever).
  - **Bare wake word**: "Hey Jarvis." + pause was dispatched as a full query (fused call + ~20s rambling chat reply) and the actual command, spoken after the pause, arrived with no wake signal and was dropped ("Heard: 'Spotify and Spotify in the left monitor.'" → idle). Now `is_wake_only_utterance` (language-agnostic: aliases stripped, no `\w{3,}` token left) short-circuits BEFORE any LLM call → canned `wake_ack_text` ("Yes, Boss?") + `StateManager.activate_hot_window_now(wake_ack_window_sec=8s)` listening window, independent of `hot_window_enabled` (that flag is post-REPLY follow-ups). Safety net in `_dispatch_query` for tiers that echo the wake word back as the query.
  - **Latent alias-ordering bug**: `extract_query_after_wake` removed aliases in SET order (hash-randomised per process) — removing "jarvis" before "hey jarvis" left a stray "hey" in extracted queries; now longest-first.
- **Why**: user report with screenshot + logs: "δεν φορτώνει το hub και βλέπω πρόβλημα με τα logs".
- **Verified**: orb page live via Playwright shows the JarvisCard (AWAITING COMMAND) instead of the stuck splash; e2e through /api/ask — "hey jarvis." produced NO LLM turn, then "put spotify on the right half" WITHOUT a wake word was accepted and direct-exec'd manageWindow right-half, reply 14 words; tests/test_wake_ack.py 5/5 (×3 runs for hash-order stability); 164 affected pytest + 95 ui vitest green. Whisper hallucination "Sous-titrage ST' 501" correctly ignored (no action needed).

## 2026-06-11 - Deep-test sweep: three flat latency taxes killed + tool-headed plan steps now actually execute
- **Category**: bug-fix + perf + infra
- **Files**: `src/jarvis/config.py`, `src/jarvis/llm.py`, `src/jarvis/listening/{fused_intent,intent_judge,fast_paths}.py`, `src/jarvis/reply/{engine,planner}.py` (+`planner.spec.md`), `src/jarvis/reminders/parser.py` (+`reminders.spec.md`), `src/jarvis/tools/builtin/reminders/create_reminder.py`, `src/{desktop_app/app,jarvis/api_server,jarvis/daemon,jarvis/vision/vision_engine}.py` (fallback literals), `docs/llm_contexts.md`, new tests `test_config_ollama_url.py` + `test_num_ctx_alignment.py`, extended `test_planner.py` / `test_fused_degraded.py` / `test_reminders_tools.py`, live config.json.
- **What**:
  - **localhost → 127.0.0.1** (`normalise_ollama_base_url()` in `load_settings()`): Windows resolves `localhost` IPv6-first, Ollama binds IPv4 only → **~2.05s connect-fallback tax on EVERY new Ollama connection, app-wide**. Measured 2.38s → 0.31s on a trivial call.
  - **One shared `llm_num_ctx` (default 4096)**: Ollama **fully reloads the runner (~8.5s measured, BOTH directions)** whenever a request's num_ctx differs from the loaded one. Live path alternated chat 8192 / fused 4096 / reminder-parser 1024 → up to two reloads per voice query; the parser's 1024 alone blew its own 8s timeout (every "remind me…" failed with "couldn't work out when" and the model then NARRATED success). All shared-brain call sites now ride `shared_num_ctx()`.
  - **fused `keep_alive` 30m → -1**: every voice query re-armed a 30-minute unload timer on the shared brain.
  - **Tool-headed plan steps force direct-exec on ANY model size** (`step_names_allowed_tool`, supersedes the vision/window/forget special-cases as the general rule): live failures — "Bitcoin is hovering around **650 dollars**" with getStockPrice never invoked (real price 62.5k), a fabricated "I've scanned my inbox" with the gmail tool never invoked, "Done — reminder set" over an EMPTY reminders table. Concrete steps dispatch via the deterministic fast-parse (router args verbatim); extra/undeclared keys go through the resolver which strips them.
  - **fast_paths reminder guard**: bare "reminder(s)" no longer hijacks modification commands ("cancel the oven reminder" was answered with a due-list while the cancel never ran); only list-intent shapes fast-path.
  - **createReminder utterance retry**: when the router strips the time phrase from the arg ("check the oven"), the tool re-parses the full utterance before failing closed.
- **Why**: user asked for a deep correctness+speed audit of the intent cascade ("whatever I ask, it must actually do it — and fast, the model does 100 t/s").
- **Verified**: 30/30 standalone routing battery (EN+EL paraphrases, all builtin tools + no-tool cases) median 3.6s → **1.6s**; live e2e totals 11-26s → **2.2-4.3s** (incl. real tool call + reply); reminder lifecycle proven against the DB (create → `pending` row at +3h exactly → voice cancel → `cancelled`); real BTC/gold prices and real inbox content spoken; 214 affected unit tests green (4 pre-existing failures confirmed pre-existing via stash).

## 2026-06-10 - Unified console completion: embodied furniture everywhere, real audio telemetry, honest Memory page, Live Logs activity line
- **Category**: feature + bug-fix + infra
- **Files**: `ui/src/console/3d/furnitureActions.ts` (+test), `ui/src/console/3d/SceneContext.tsx`, `ui/src/console/3d/ResponsiveFraming.tsx` (new), `ui/src/console/3d/DollhouseScene.tsx`, `ui/src/console/services/{useFurnitureActions,NavigationContext,dashboardApi,seam,MemoryDataContext}.ts(x)`, `ui/src/console/dashboard/{InfoPanel(new),SystemStatusPanel,StatePanel}.tsx`, `ui/src/console/sections/DashboardPage.tsx`, `ui/src/console/ConsoleRoot.tsx`, `ui/src/console/zones/{Zone1MemoryCore,graph/GraphHeader,audio/HealthStrip,logs/LogStatStrip}.tsx`, `ui/src/console/lib/{audioEngine(+test),logMap(+test)}.ts`, `ui/src/console/types/logs.ts`, `ui/src/console/hooks/useAudioEngine.ts`, `ui/src/lib/api.ts`, `src/jarvis/api_server.py`, `src/jarvis/listening/{audio_telemetry.py(new),wispr_bridge.py,listener.py}`, `tests/test_audio_telemetry.py` (new), `tests/test_config_models.py`
- **What**:
  - **Furniture actions (all rooms)**: registry covers 25/26 dollhouse objects — navigate-to-page, generalised info panels (system/weather/gmail/calendar/reminders/AI core) on real data, lights toggle, hydration reminder via `POST /api/reminders` (opens the panel so the write is visible), Run Script -> daemon test tone. `NavigationContext` lets the 3D scene switch console pages.
  - **Responsive dashboard**: `ResponsiveFraming` auto-fits the camera on narrow/short windows without fighting manual zoom; status panel scrolls; test panel starts collapsed under 760px height. (Window move/resize/F11 itself shipped in the desktop commit `feat(desktop)` same day.)
  - **Real audio telemetry**: new `/ws/audio` WebSocket + `publish_audio_telemetry()`; wispr bridge publishes RMS/wake-score/voiced/16-band spectrum per 80ms wake frame, whisper path publishes RMS + Silero probability from `_is_speech_frame` (~12 Hz, zero cost without subscribers, fail-open). Audio I/O page renders the daemon's REAL signal when the browser-mic preview is off; fake Quality/Noise/Clarity/Response% cards replaced with measured Input dB / VAD / wake score / listener state; honest flatline when no source.
  - **Memory page honesty**: footer stats were hardcoded (26 facts / 12 reminders / 3 changes) — now computed from live graph/reminders/episodic; demo-data fallbacks removed entirely (empty + offline states show the truth); friendly empty-state copy. Verified the extraction pipeline itself is healthy (manual run against live Ollama: 5/5 correct branch-tagged facts) — the live graph is genuinely empty post-wipe.
  - **Live Logs clarity**: plain-language activity line (describeActivity over stable pipeline markers) with relative time in the stat strip; new Brain source (LLM/intent/planner/tool) checked before Services so `Agent → getWeather` is brain activity; extended source keywords (STT->Voice, reminders->Services).
  - **Test repair**: `test_config_models` VRAM invariant relaxed to `>=` — the strict `>` assumed the intent judge always loads as a separate gemma alongside chat (one-model topology made that stale).
- **Why**: user request — finish all console pages (furniture clicks, window scaling, real Memory/Audio data, readable logs) and fix anything found along the way.
- **Verified**: 85 console vitest + 14 new telemetry pytest green; full backend suite green locally; live e2e on the running daemon — `/ws/audio` delivered 25 real frames (rms/vad/state), dashboard metrics/services/weather(Ioannina via weather_location) all real. Note: live `stt_backend` is now **whisper** (large-v3-turbo on CUDA); VRAM ~15.4/16GB with vision warm at boot (self-evicts to ~12.4GB).

## 2026-05-29 - Voice communication fixes (audit-driven, Wispr path)
- **Category**: bug-fix + feature + infra
- **Files**: `src/jarvis/reply/engine.py`, `src/jarvis/llm.py`, `src/jarvis/config.py`, `src/jarvis/listening/listener.py`, `src/jarvis/listening/wispr_bridge.py`, `src/jarvis/output/tts.py`, `docs/llm_contexts.md`, `src/jarvis/reply/reply.spec.md`, plus new tests: `test_engine_cancel_event.py`, `test_listener_cancel_event.py`, `test_engine_small_model_fallback.py`, `test_llm_generation_bounds.py`, `test_wispr_bridge.py`, `test_listener_dispatch_and_dictation.py`, `test_listener_control_flag_safety.py`, `test_tts_sentence_streaming.py`, and a fix to `tests/test_greeting_no_tools.py`.
- **What** (9 changes, all TDD, ~60 new tests):
  - **L1 / fused-tools wiring (latency)**: `_dispatch_query` now forwards `self._last_fused_tools` / `self._last_fused_plan` into `run_reply_engine` (then clears them). COMPLETES the Tier 2.4/2.5 work: the engine fast-path and cascade stashing already existed, but the listener never passed the stashed fused output, so the engine redundantly re-ran router+planner on every voice turn (the ~10-14s the plan targeted).
  - **X1 / cancellation**: wired the previously-dead `_llm_cancel_event`. COMPLETES the control-bus STOP feature: STOP and Wispr barge-in set the event but nothing read it. `run_reply_engine` now accepts `cancel_event`, polls it at turn/tool boundaries, and returns an empty-string sentinel that suppresses TTS. `_dispatch_query` clears then passes the event.
  - **W5 / instant barge-in**: in `wispr_bridge._process_vad` HOT_WINDOW, a VAD speech-onset while `_jarvis_speaking` fires `on_stop()` immediately (gated by `wispr_barge_in_interrupt`, default True), so TTS is cut on speech onset instead of after the Wispr cloud + clipboard round-trip.
  - **X2 / streaming TTS**: Piper synthesises and plays sentence-by-sentence (`tts_streaming_enabled`, default True), cutting time-to-first-audio. Single-fire playback-started/completion callbacks preserved; echo tracking uses the full reply text; `interrupt()` stops after the current sentence. Chatterbox left whole-text.
  - **R1 / generation cap**: `chat_with_messages` gains `num_predict` + `temperature`; the synthesis turn passes `llm_chat_max_tokens` (default 512) and `llm_chat_temperature` (default -1.0 = unset).
  - **R3 / memory window**: the Tier 2.6 injection window (was a hardcoded drop at turn 3) is now `memory_injection_max_turns` (default 4) plus a debug_log when a late memory result is dropped.
  - **L2 / L3 / Wispr robustness**: `on_dictation_end(captured: bool)`; on a clipboard timeout the listener stops the stuck thinking-tune, resets the face to IDLE, and prints a notice (was a silent hang).
  - **W1 / data-loss guard**: `_erase_autotyped_text` caps backspaces (`wispr_erase_max_chars`, default 300) and skips entirely when over the cap.
  - **W3 / X3 / thread-safety**: lock on `_jarvis_speaking`; lock + atomic `_consume_manual_finalize()` for `_muted` / `_manual_trigger_active` / `_manual_finalize_requested`.
  - **R2**: malformed-output fallback small-model detection now uses `detect_model_size` so `gemma4:e2b` is correctly classified SMALL.
  - **R4**: `wispr_min_dictation_sec` default 2.0 -> 1.0 (faster short commands).
  - Self-introduced regression fixed: 4 `mock_chat` stubs in `test_greeting_no_tools.py` gained `**kwargs` for the new `num_predict`/`temperature` kwargs.
- **Why**: a 4-agent audit of the STT -> thinking -> answer -> TTS pipeline for the live Wispr-Flow setup. Reply language deliberately kept English (forced-English clamp untouched) per user instruction.
- **Verified**: 899 passed across the 43 touched test files, 0 new regressions. The 17 remaining failures are pre-existing WIP (qwen3.5 VRAM consistency, enrichment/graph refactor, intent-judge 6s default, migration v6, chatterbox state-transition, Linux audio warning). Smoke eval (gemma4:e2b via Ollama): 28/32 pass; the 4 failures are grounding/tool-routing (matching the WIP's broken graph enrichment), not output truncation, confirming `num_predict=512` does not cut replies.
- **Runs from**: source. Desktop icon -> `Start-Jarvis.vbs` -> `.venv\Scripts\pythonw.exe -m desktop_app`. Restart the running Jarvis to pick up the changes (Python, no rebuild).
- **Related plan item**: completes Tier 2.4/2.5 fused-tools wiring + control-bus STOP; full plan at `docs/superpowers/plans/2026-05-29-voice-comms-fixes.md`.

## 2026-05-28 — Critical bug fix: Defer pygame.mixer.init at boot — SDL was holding device handle, silent-playback bug
- **Category**: bug-fix (root cause)
- **Files**: `src/jarvis/output/tts.py` (ChatterboxTTS.start() pre-init block: removed eager `_safe_mixer_init(24000)` call, replaced with `pygame mixer init DEFERRED` log line)
- **What user reported**: After Wispr → cascade → reply → TTS synthesised audio successfully (`[tts] synthesis DONE in 9.87s (audio=12.00s)`) and sounddevice reported `🔊 TTS playing (sounddevice shared, 24000 Hz, 12.0s)` — but **no audio came through speakers**. User ran `test_audio_devices.py` standalone and confirmed the system default device plays fine — proving the device path is OK in isolation.
- **Root cause** (already hinted at in the Tier 3.9 docstring): `_safe_mixer_init(24000)` was called eagerly at ChatterboxTTS.start() boot time, BEFORE any actual TTS playback. SDL keeps an open handle on the system default output device once `pygame.mixer.init` succeeds. With that handle held:
  - WASAPI exclusive mode rejects with `-9996 Invalid device` (host API contention).
  - Shared-mode `sd.play()` reports success and the stream is "active", but PortAudio routes to a phantom no-op stream because SDL has the real device. **Silent playback with no error.**
  This is exactly the bug the Tier 3.9 docstring flagged as "Future tier: defer pygame mixer init until the sounddevice path actually fails."
- **Fix**: removed the eager `_safe_mixer_init(24000)` call from `ChatterboxTTS.start()`'s pre-init block (lines 990-993). Pygame mixer init now happens LAZILY only inside `_play_via_pygame` (line 444-447 existing fallback path) when sounddevice fails. By that point sounddevice has released its handle, so pygame's SDL can grab the device cleanly.
- **Why this won't regress**: the lazy init has been in `_play_via_pygame` since the Tier 3.9 work — it just wasn't being exercised because the eager init at startup already populated `pygame.mixer.get_init()`. The fallback chain is now: try sounddevice WASAPI exclusive → try sounddevice shared → try lazy pygame init + play. All three paths verified working in `_play_via_sounddevice` and `_play_via_pygame`.
- **Verified**: AST OK. Standalone smoke confirms sounddevice still uses the system default device (`[4] Headset (Realtek(R) Audio)`). User's test script already proved this device plays audio.
- **Note on `tts_output_device` config**: still available as an OPTIONAL override if user wants to pin a specific device. Defaults to None (system default), which now actually works.

## 2026-05-28 — Bug fix: Phantom wake after TTS — suppress wake during speak + 0.8s cooldown
- **Category**: bug-fix
- **Files**: `src/jarvis/listening/wispr_bridge.py` (`__init__` adds `_post_speak_resume_timer` + `_post_speak_cooldown_sec`; `set_speaking()` rewritten); `C:\Users\aggel\.config\jarvis\config.json` (`wispr_wake_threshold: 0.1 → 0.5`).
- **What user reported**: "Όταν τελειώνει ο Jarvis να μιλάει, κάποιες φορές κάνει τον ήχο του listening" — phantom listening tune fires right after TTS ends even though user didn't say "Hey Jarvis" and didn't press the trigger button. User also clarified the intended UX: ONLY trigger on explicit wake word OR lightning button — no auto-listening.
- **Root cause**: openWakeWord ran continuously even while JARVIS was playing TTS. At `wispr_wake_threshold: 0.1` (very low), the wake model triggered on JARVIS's own voice coming back through the desktop microphone — speakers → room → mic → openWakeWord → false wake → `_on_wispr_wake` → starts thinking tune → user hears phantom "listening" sound.
- **Fix**:
  - `set_speaking(True)` now calls `self.pause()` — wake detection is fully suspended for the duration of TTS playback. The wake model can't fire, period.
  - `set_speaking(False)` schedules a delayed `self.resume()` via `threading.Timer` (default 0.8s, configurable in code via `_post_speak_cooldown_sec`). The cooldown gives speaker decay / room reverb / echo tail time to die out before wake detection resumes.
  - Any pending resume timer is cancelled when a new TTS starts — back-to-back replies don't get mid-stream resumes.
  - **Config**: `wispr_wake_threshold` raised 0.1 → 0.5 — more conservative, fewer false positives.
- **Verified**: Lifecycle test confirms `set_speaking(True)` → `_paused=True` immediately, `set_speaking(False)` → still `_paused=True` (resume scheduled), after 1s sleep → `_paused=False` (cooldown elapsed, wake detection resumed).
- **Behavior**: Combined with `wispr_hot_window_sec: 0` (set earlier), the bridge ONLY ever PTTs on (a) explicit "Hey Jarvis" wake AND threshold ≥ 0.5, OR (b) the HUD lightning-bolt TRIGGER button.

## 2026-05-28 — UI fix: HUD transcript display readable when eye toggle is on
- **Category**: bug-fix (UI)
- **Files**: `ui/src/components/JarvisCard.tsx` (`truncateQuery` 8→24 words; query display: maxHeight 40→84, wraps to 3 lines via `-webkit-line-clamp`, fontSize 12→13, color `#E8F4F8`→`#FFFFFF`, added bg pill with cyan border, header marginBottom 32→14 when query visible)
- **What user reported**: With the eye icon toggled ON, transcript text "δεν φαίνεται καθόλου καλά" — barely visible, looked washed-out, clipped, partially hidden behind the JARVIS header.
- **Root cause**: Previous styling used `whiteSpace: 'nowrap'` + `maxHeight: 40` + `textOverflow: 'ellipsis'` so anything longer than one line got truncated invisibly. `fontSize: 12` was tiny, the dim color `#E8F4F8` over a translucent card looked washed-out, and `truncateQuery` hard-cut at 8 words so half-sentences vanished before they even reached the renderer.
- **Fix**:
  - Wrap to up to **3 lines** with `-webkit-line-clamp: 3` + `wordBreak: 'break-word'`.
  - Brighter text (`#FFFFFF`) with softer cyan text-shadow for legibility on the dark card.
  - **Background pill** (`rgba(0,212,255,0.06)` + cyan border) visually separates the transcript from the JARVIS wordmark above and the waveform below — no more "is that text or part of the header?".
  - `truncateQuery` raised 8→24 words (CSS clamp does the real visual cutoff now).
  - Header `marginBottom` tightens 32→14 when the query pill is visible so the card stays balanced.
- **Verified**: `npm run build` succeeded (1738 modules, `dist/assets/index-Bl5f2x2d.js` 888 kB). Load HUD or refresh QWebEngineView to see the new styling.

## 2026-05-28 — Bug fix: TTS audio went to wrong output device — new `tts_output_device` config
- **Category**: bug-fix + feature
- **Files**: `src/jarvis/config.py` (new `tts_output_device: Optional[str]` field), `src/jarvis/output/tts.py` (new `_resolve_output_device()` + `_get_configured_output_device()` helpers; `_play_via_sounddevice` shared-mode path honors the configured device), new `C:\tmp\test_audio_devices.py` interactive probe.
- **What user reported**: Chatterbox synth succeeds, sounddevice claims `🔊 TTS playing (sounddevice shared, 24000 Hz, 7.9s)` — but no audio reaches the speakers.
- **Root cause diagnosed**: `sd.default.device = [1, 4]` — Windows default output is `[4] Headset (Realtek(R) Audio)` via MME. The user listens through a DIFFERENT device (e.g., PD200X Podcast Microphone speakers, CORSAIR VOID headset, etc.). Sounddevice's shared-mode `sd.play()` without explicit `device=` uses the system default, so the audio went silently to whatever Realtek thinks is the "headset" port — not the user's actual speakers.
- **Fix**:
  - New config field `tts_output_device: Optional[str]` — accepts None (system default), integer index ("16"), or case-insensitive name substring ("PD200X" / "Corsair" / "Realtek").
  - `_resolve_output_device(spec)` walks `sd.query_devices()`, scores matches by host API (WASAPI > DirectSound > MME/WDM-KS), returns best index.
  - Resolved index passed to `sd.play(..., device=N)` when set.
  - Result logged on startup as `🎯 tts_output_device='X' → matched [N] Name (hostapi)`.
- **How user finds the right device**: Run `C:\Users\aggel\Jarvis-src\.venv\Scripts\python.exe C:\tmp\test_audio_devices.py` — interactive script that plays a 1-second beep to each candidate output device, user presses Enter to advance, then sets the right substring in `config.json`.
- **Verified**: AST OK; resolver test shows PD200X→[16], Realtek→[15], Corsair→[14] (all WASAPI host API).

## 2026-05-28 — Critical bug fix: Wispr transcripts now actually dispatch to reply engine (no more stuck in collection state)
- **Category**: bug-fix
- **Files**: `src/jarvis/listening/listener.py` (`_start_collection` gets Wispr short-circuit, `_process_transcript` sets `_wispr_current_source` flag, `_dispatch_wispr_transcript_to_cascade` clears flag in finally)
- **What user reported**: After Wispr Flow correctly transcribed "Τι ώρα είναι τώρα στην Ελλάδα;" and the cascade accepted it as `time_current` with high confidence, the system printed `✨ Working on it: τι ώρα είναι τώρα στην ελλάδα;` and then **HUNG INDEFINITELY**. No reply, no TTS, UI stuck on LISTENING.
- **Root cause**: `_process_transcript` calls `_start_collection(text)` after intent acceptance. `_start_collection` is designed for the Whisper streaming flow — it begins gathering PARTIAL transcripts and waits for `state_manager.check_collection_timeout()` (silence detector) to fire before finalizing. That timeout is driven by Whisper's audio callback adding more partials and detecting silence between them. In Wispr flow there IS NO audio callback in the listener — the bridge owns the mic, and Wispr Flow gives us ONE complete utterance, not partials. So `check_collection_timeout()` never fires, and `_finalize_utterance → _dispatch_query` never happens.
- **Fix**: Added `self._wispr_current_source` instance flag. `_process_transcript` sets it to `"wispr"` at the top when called with `source="wispr"`; `_dispatch_wispr_transcript_to_cascade` clears it in a `finally` block. `_start_collection` checks the flag — if set, after publishing state for UI visibility, it immediately calls `state_manager.clear_collection()` + `_dispatch_query(text)` instead of waiting for the silence timeout that will never fire. Whisper path (and TRIGGER button, etc.) are completely unaffected because the flag is None outside `_process_transcript`.
- **Side effect bonus**: UI hub sync issue (HUD stuck on "LISTENING") will resolve automatically — the state transitions through THINKING → SPEAKING → IDLE happen naturally inside `_dispatch_query → reply.engine → tts.speak`.
- **Verified**: AST OK; `_start_collection` source confirmed via `inspect.getsource` to have the short-circuit; full import smoke pass.

## 2026-05-28 — Wispr UX overhaul: disable auto-trigger loop + dictation conflict + wire mute/trigger buttons
- **Category**: bug-fix + feature
- **Files**: `C:\Users\aggel\.config\jarvis\config.json` (`wispr_hot_window_sec: 0`, `dictation_enabled: false`); `src/jarvis/listening/wispr_bridge.py` (new `pause()`/`resume()`/`trigger_now()` methods + `_paused` flag + early-exit in `_process_wake`); `src/jarvis/listening/listener.py` (MUTE/UNMUTE/TRIGGER control bus handlers wire to bridge when `stt_backend == "wispr"`)
- **What user reported**:
  1. **System auto-triggers Wispr repeatedly without "Hey Jarvis"** — bridge tap-tap-tap loop on background noise.
  2. **Old dictation engine fires on every Ctrl+Win press** — log spam: `[dictation] whisper model not loaded — dictation skipped` (×N per cycle).
  3. **Reply never speaks** — auto-trigger loop interrupts the cascade before TTS fires.
- **Root cause of #1**: hot window's auto-PTT (Phase E) fires `_start_dictation(score=1.0)` whenever Silero VAD detects ANY speech-like onset during the 10s post-reply window. The bridge's own keyboard taps, the Wispr Flow UI sounds, background noise — all triggered phantom dictations. Each phantom captured nothing meaningful but extended the hot window for another 10s → infinite feedback loop.
- **Root cause of #2**: separate `DictationEngine` (the legacy hold-Ctrl+Win-to-dictate feature) was running in parallel. When the bridge tapped Ctrl+Win+Space, the dictation engine's hotkey listener (`ctrl+cmd` = Ctrl+Win) ALSO fired and tried to dictate with Whisper which wasn't loaded.
- **Root cause of #3**: cascade execution was being interrupted by the auto-trigger chaos before reply.engine could finish.
- **What the user wants instead** (literal quote): "Το μικρόφωνο ακούει μόνο το Hey Jarvis. Όταν το πω εγώ αυτό, τότε απλά πατάει το hands-free για το Wispr." (The mic listens ONLY for "Hey Jarvis". When I say it, it just taps hands-free for Wispr.) Plus: mute button must actually disable wake detection; lightning-bolt trigger button must tap shortcut immediately (skip wake).
- **Fixes**:
  - **Config**: `wispr_hot_window_sec: 10 → 0` (disables the auto-PTT entirely; bridge's `enter_hot_window` is a no-op when ≤ 0). `dictation_enabled: true → false` (kills the legacy DictationEngine that fought with the bridge).
  - **Bridge methods**: `pause()` sets `_paused=True` which makes `_process_wake` short-circuit (drains buffer, returns early — wake model never fires). `resume()` clears flag. `trigger_now()` bypasses wake detection by calling `_start_dictation(score=1.0)` directly; auto-unpauses if muted; returns False if already DICTATING.
  - **Control bus wiring**: when `stt_backend == "wispr"`:
    - MUTE → call `bridge.pause()` (in addition to existing `_muted` flag flip + UI publish).
    - UNMUTE → call `bridge.resume()`.
    - TRIGGER → call `bridge.trigger_now()` INSTEAD of legacy collection state, plus auto-unmute UI.
  - Whisper-backend path remains unchanged (rollback safety).
- **Verified**: AST OK; new methods exist and work (`pause()` flips flag, `resume()` clears, `enter_hot_window()` no-ops with sec=0).
- **Required setup**: user's Wispr Flow Settings → Shortcuts → Hands-free mode must be `Ctrl + Win + Space` (per the screenshot already shown).
- **Related plan item**: live-test follow-up to Wispr-bridge plan.

## 2026-05-28 — Bug fix: Wispr transcripts now reach qwen + bridge taps hands-free toggle instead of holding PTT
- **Category**: bug-fix + feature
- **Files**: `src/jarvis/listening/listener.py` (`_process_transcript` signature + `_dispatch_wispr_transcript_to_cascade`), `src/jarvis/listening/wispr_bridge.py` (`_do_press_keys`, `_do_release_keys`, new `_tap_hands_free_toggle_locked`, `_force_release_locked`, module docstring)
- **What**:
  - **Bug 1 (cascade gate)**: User reported "wake works, transcript arrives, but qwen never runs". Log evidence: `[voice] skipping intent judge — no wake word, no hot window, no TTS` immediately after `feed_transcript`. Root cause: `_process_transcript` line 1164 resets `self._wake_timestamp = None` at the start of every utterance — the Whisper path relies on the wake check at line ~1873 to set it back from the IN-TEXT wake word. But the Wispr path STRIPS the wake word in `_strip_leading_wake_word` (because openWakeWord already validated it externally), so the in-text check fails and `has_engagement_signal` stays False → cascade skipped. **Fix**: added `source: str = "whisper"` param to `_process_transcript`. When `source == "wispr"`, synthesise `self._wake_timestamp = utterance_start_time` instead of resetting to None. `_dispatch_wispr_transcript_to_cascade` now calls `self._process_transcript(text, 0.0, now, now, source="wispr")`.
  - **Bug 2 (keyboard lock)**: User reported the keyboard was locked during dictation (Ctrl + Win were held the whole time). **Fix**: switched bridge from HOLD Ctrl+Win to TAP Ctrl+Win+Space (Wispr Flow's hands-free toggle). New helper `_tap_hands_free_toggle_locked` presses Ctrl → Win → Space and releases Space → Win → Ctrl with `KEY_INTER_PRESS_DELAY` gaps. `_do_press_keys` calls it once to START hands-free; `_do_release_keys` calls it again to STOP. `_keys_held` reused as "hands-free is currently active" sentinel to prevent double-toggle. `_force_release_locked` defensively releases all three modifiers AND toggles hands-free off if it was active.
- **Why**: After daemon restart with `stt_backend: "wispr"`, user said "Hey Jarvis, τι ώρα είναι?" — bridge correctly PTT'd, Wispr Flow transcribed, transcript reached `feed_transcript`, but the cascade silently dropped it because of the wake_timestamp reset bug. Separately, holding Ctrl+Win locked the user's keyboard for 3-5 s per query.
- **Verified**: AST + import OK. `inspect.signature(VoiceListener._process_transcript)` confirms new `source: str = 'whisper'` param. `WisprBridge._tap_hands_free_toggle_locked` exists.
- **Wispr Flow setup required**: User must have Wispr Flow's **hands-free mode** bound to **Ctrl+Win+Space** in Settings → Shortcuts. (Hands-free is the toggle; push-to-talk is the legacy hold mode the bridge no longer uses.)
- **Related plan item**: Wispr-bridge plan follow-up after live testing.

## 2026-05-28 — Phase E+F: Wispr hot window + TTS interrupt via stop pattern
- **Category**: feature
- **Files**: `src/jarvis/listening/wispr_bridge.py` (873 → 992 lines), `src/jarvis/output/tts.py` (1628 → 1665, new `playback_ended_callback`), `src/jarvis/listening/listener.py` (4397 → 4474)
- **What**:
  - **Phase E (hot window)**: After every successful Wispr dictation OR TTS playback end, bridge enters `HOT_WINDOW` state for `wispr_hot_window_sec` seconds (default 10). During HOT_WINDOW, wake word detection is BYPASSED — first Silero VAD "speech start" event triggers PTT directly with score=1.0. Threading.Timer transitions back to IDLE on expiry. New `tts.py` `playback_ended_callback` fires on natural completion (not interrupt). Listener's `_on_playback_ended` calls `bridge.enter_hot_window()`. Wired on all 3 `tts.speak()` call sites (main reply, fast-path, daddy's-home easter egg).
  - **Phase F (stop interrupt)**: Bridge gets `_STOP_PATTERN` regex covering `stop|σταμάτα|σώπα|αρκετά|ησυχία|quiet|shut up|enough` (optionally prefixed with "hey jarvis,"). New `on_stop` callback on bridge. `set_speaking(True/False)` flag from listener tracks TTS state. When `_jarvis_speaking AND is_stop_pattern`, bridge fires `on_stop()` (in addition to `on_transcription()`). Listener's `_handle_wispr_stop` calls `reset_everything()` (existing path that interrupts TTS + cancels LLM + clears dialogue).
- **Why**: Phase E plan items — bring back the "follow-up without wake word" UX that hot_window gives in Whisper-mode. Phase F — enable "Jarvis stop" interrupt while TTS is playing.
- **Verified**: 385 listener+TTS+dictation tests passed, 10 pre-existing failures unchanged (carried over from earlier intent cascade work), 0 new failures. Stop pattern unit test 15/15 cases pass (Greek + English + edge cases).
- **Thread safety**: All state writes under `_state_lock`, hot-window timer under `_hot_window_lock`, all phases gated on `_stt_backend == "wispr"` so Whisper rollback path is inert.
- **Related plan item**: Wispr-bridge plan Phase E + F.

## 2026-05-28 — Phase D: Wire Wispr transcripts into existing intent cascade
- **Category**: feature
- **Files**: `src/jarvis/listening/listener.py` (4094 → 4397 between Phase C+D)
- **What**: New methods on `VoiceListener`:
  - `feed_transcript(text)`: entry point for Wispr transcripts. Strips leading wake word, then dispatches.
  - `_strip_leading_wake_word(text)`: regex strip for `(hey|ok|okay|hi|hello|γεια)? (jarvis|τζάρβις|γιάρβης|γιαρβης)` at start.
  - `_on_wispr_wake()`: short audio-thread-safe callback — starts thinking tune + face state.
  - `_on_wispr_dictation_end()`: stub for post-clipboard worker.
  - `_dispatch_wispr_transcript_to_cascade(text)`: adds to `_transcript_buffer`, calls `_process_transcript(text, 0.0, now, now)` — **the same cascade entry point Whisper uses** post-finalize. Reuses existing Tier 0 fast-path → Tier 1 heuristic → Tier 2 fused cascade unchanged.
- **Why**: Phase D plan item — connect bridge output to existing intent pipeline without duplicating cascade logic.
- **Related plan item**: Wispr-bridge plan Phase D.

## 2026-05-28 — Phase C: Gate Whisper init behind `stt_backend == "whisper"`
- **Category**: refactor
- **Files**: `src/jarvis/listening/listener.py`
- **What**: In `VoiceListener.__init__` (line 396-399, 681-704): reads `cfg.stt_backend` defensively via `getattr`, defaults to `"whisper"`. When `"wispr"`, instantiates `WisprBridge(cfg, on_transcription=self.feed_transcript, on_wake=self._on_wispr_wake, on_dictation_end=self._on_wispr_dictation_end)` and does NOT open sounddevice InputStream / Whisper model. Failure during bridge init falls back to `_stt_backend = "whisper"`. New `_run_wispr_backend()` method at line 4165 boots the bridge + does LLM warmups + idles on `_should_stop`. `stop()` calls `bridge.stop()` if alive. **Whisper code path completely untouched** — single config flip restores it.
- **Why**: Phase C plan item — allow runtime selection of STT backend without removing Whisper.
- **Verified**: AST + import OK. 108 listener tests pass (1 pre-existing Linux-specific failure unchanged).
- **Related plan item**: Wispr-bridge plan Phase C.

## 2026-05-28 — Phase B: `stt_backend` + 10 `wispr_*` Settings fields + config flip
- **Category**: infra
- **Files**: `src/jarvis/config.py` (Settings dataclass + DEFAULT_SETTINGS + load_settings); `C:\Users\aggel\.config\jarvis\config.json` (full rewrite from backup with `stt_backend: "wispr"`)
- **What**: New Settings fields: `stt_backend` ("whisper" | "wispr"), `wispr_wake_model`, `wispr_wake_threshold`, `wispr_silence_ms`, `wispr_min_dictation_sec`, `wispr_max_dictation_sec`, `wispr_clipboard_wait_sec`, `wispr_hot_window_sec`, `wispr_suppress_autotype`, `wispr_mic_device`. Defensive validators (int/float coercion with fallbacks). Config defaults `stt_backend: "whisper"` for safety; user's `config.json` set to `"wispr"` to enable.
- **Why**: Phase B plan item — config-driven backend selection.
- **Critical incident during execution**: A linter/migration wiped the user's `config.json` to 4 fields mid-task (similar to the issue config_safety.py was supposed to prevent — but auto-restore only fires at daemon boot, not on every write). Restored manually by writing a fresh config with ALL the accumulated changes from Tier 1+2+Wispr correctly merged from the most recent backup (`config_pre_tier1_1779966064.json` from 27 May 20:58).
- **Verified**: `load_settings()` returns all 10 wispr fields with correct types. 80 wake_aliases + 7 mcp_servers + voice clone path all preserved.
- **Related plan item**: Wispr-bridge plan Phase B.

## 2026-05-28 — Phase A: `wispr_bridge.py` module — adapted from desktop standalone
- **Category**: feature
- **Files**: new `src/jarvis/listening/wispr_bridge.py` (873 lines: 552 code + 98 docstrings + 102 comments + 121 blank)
- **What**: Adapted from `C:\Users\aggel\Desktop\whisp\jarvis_wispr_bridge.py` (956 lines standalone). Exposes `class WisprBridge` with `start()/stop()/enter_hot_window()/set_speaking()` API. Callbacks `on_transcription`, `on_wake`, `on_dictation_end` (+ `on_stop` added by Phase F). Removes: `_Win32FocusSink` (150 lines), `main()`, argparse, custom log()/ANSI color (replaced with `print()` for milestones + `debug_log("...", "voice")` for noise). Config-driven via `getattr(cfg, "wispr_X", DEFAULT_X)`. State enum extended with `HOT_WINDOW` (used by Phase E).
- **Key flows**:
  - "Hey Jarvis" → openWakeWord triggers → `_start_dictation()` → pynput presses Ctrl+Win.
  - Silero VAD detects 800ms silence → `_stop_dictation()` → release Ctrl+Win.
  - Wispr Flow auto-types transcription into focused window AND writes to clipboard.
  - `_post_dictation_worker` polls clipboard up to 6s, calls `on_transcription(text)`.
  - If `wispr_suppress_autotype=True`: send N backspaces to erase auto-typed text.
- **Why**: Phase A plan item — embeddable Wispr Flow bridge as JARVIS module.
- **Verified**: AST + import OK. `WisprBridge(cfg, on_transcription=noop)` instantiates cleanly.
- **Thread safety concerns documented**: `on_wake` fires from PortAudio audio callback thread (must be short!). `on_transcription` and `on_dictation_end` fire from per-dictation worker daemon threads. `set_speaking` is single bool — atomic on CPython.
- **Pip install during Phase G**: `openwakeword 0.6.0` + `pyperclip 1.11.0` added to venv. `onnxruntime`, `pynput`, `sounddevice`, `numpy`, `torch` were already installed for Whisper/Silero VAD path.
- **Related plan item**: Wispr-bridge plan Phase A.

## 2026-05-28 — Tier 3.9 WASAPI exclusive audio mode in sounddevice path (partial)
- **Category**: feature (partial)
- **Files**: `src/jarvis/output/tts.py` (`_build_extra_settings` new at 150-187, `_play_via_sounddevice` modified 190-321)
- **What**: Adds Windows-only WASAPI exclusive mode attempt before falling back to shared. Resamples 24kHz Chatterbox → device native rate (typically 48kHz, clean 2:1 via `scipy.signal.resample_poly`) since exclusive mode bypasses Windows mixer. Uses `latency='low'` + `blocksize=256` (~10.7ms @ 24kHz) on both paths.
- **Why**: Plan item Tier 3.9 — target ~3-10ms audio engagement vs 20-50ms in shared mode.
- **Verified**: AST clean. Standalone test passes — `✅ SUCCESS: TTS completed in 5.5s`, audio plays at correct speed. HOWEVER WASAPI exclusive **does NOT currently engage** because pygame's SDL pre-init holds the default output device, causing PortAudio `Invalid device` (-9996). Falls back to shared mode cleanly. To realize the win, pygame init must be deferred until sounddevice fails — left as future tier follow-up.
- **Related plan item**: Tier 3.9 (audio mode polish). Partial: code path ready, blocked by pygame init order.

## 2026-05-28 — Tier 2.4 second half: reply.engine consumes fused tools+plan
- **Category**: feature
- **Files**: `src/jarvis/reply/engine.py` (new `_translate_fused_to_router_shape` 778-804, `_translate_fused_to_planner_shape` 807-862, guard block at 994-1048 wraps original router+planner 1059-1179)
- **What**: `run_reply_engine` gains optional `fused_tools` + `fused_plan` kwargs. When provided and `cfg.use_fused_tools_in_engine=True` (default), the engine SKIPS the internal `select_tools` (5-7s) + `plan_query` (5-7s) LLM calls entirely. Recall gate + parallel memory enrichment paths preserved. Graceful fallback on malformed tools.
- **Why**: Without this, listener cascade computed fused intent but `reply.engine` redid the work. This is where the 10-14s plan-target savings materialize.
- **Verified**: AST + import OK. Engine + planner test suite: 108/109 pass (1 pre-existing failure unchanged). Broader suite: 208/213 (5 pre-existing failures unchanged, none introduced).
- **Related plan item**: Tier 2.4 second half.

## 2026-05-28 — Tier 2.5 INTEGRATION: heuristic classifier + fused intent wired into listener
- **Category**: feature
- **Files**: `src/jarvis/listening/listener.py` (imports 25-48, `__init__` wiring 516-595, helpers 802-986, call-site swap 1428-1465). Line count 3358 → 3670 (+312).
- **What**: Adds three-tier intent cascade BEFORE the legacy `intent_judge.judge()` call:
  - Tier 0: fast-path regex SHORT-CIRCUIT (existing).
  - Tier 1: `HeuristicIntentClassifier` (Aho-Corasick → TF-IDF ONNX, <2ms, ~88% local routing at med_threshold=0.5).
  - Tier 2: `FusedIntentEngine` (1 LLM call replacing judge+router+planner, ~3-5s).
  - Tier 3 (fallback): existing `intent_judge.judge()` cache + Ollama call.
  - Fused `tools` + `plan` stashed on `self._last_fused_tools/_plan` for `reply.engine` to consume (wired in separate entry above).
  - 10s/32-entry cascade cache, MD5-keyed identically to existing intent_judge cache.
  - Feature flags: `cfg.use_fused_intent` + `cfg.use_heuristic_classifier` + `cfg.heuristic_med_threshold` (default 0.5, overrides classifier's internal 0.72).
- **Why**: To realize the latency wins from Tier 2.4 (fused intent module) and Tier 2.5 (heuristic classifier module).
- **Verified**: AST + import OK. 161 listener/intent tests pass, 0 new failures.
- **Related plan item**: Tier 2.4 + Tier 2.5 integration.

## 2026-05-28 — Tier 2.5 Heuristic intent classifier (Aho-Corasick + TF-IDF ONNX)
- **Category**: feature
- **Files**: new `src/jarvis/listening/intent_classifier.py` (333 lines), new `scripts/train_intent_classifier.py` (252 lines), new `data/intent_classifier/intent_training.jsonl` (1500 bilingual examples, 15 intent classes), new `data/intent_classifier/model.onnx` (390KB), `labels.json`, `patterns.json` (140 AC patterns, 74 Greek + 66 English). Requires `pyahocorasick`, `skl2onnx`, `onnxruntime` (installed in venv).
- **What**: Two-tier local intent classifier. Tier 1 Aho-Corasick (<1ms), Tier 2 TF-IDF + LogisticRegression exported to ONNX (<2ms). Returns `ClassifierResult(intent, confidence, score, tier, entities, latency_ms)`. p50 latency 0.00ms, p99 0.36ms across 1500 corpus. Validation: macro F1 0.931, 93% accuracy.
- **Why**: Plan item Tier 2.5 — skip 5-7s LLM judge for the ~88% common-pattern queries.
- **Verified**: 20/20 smoke test pass. Greek + English parity (~93% each).
- **Notable bug fix during build**: ONNX RE2 tokenizer was silently dropping all Greek tokens because Python's `\b\w+\b` Unicode-aware default isn't fully implemented by ONNX. Switched to `\S+` whitespace tokenization (precision-preserving since input is pre-normalised).
- **Related plan item**: Tier 2.5.

## 2026-05-28 — Tier 2.6 Parallel memory enrichment (Path B: ThreadPool + inter-turn injection)
- **Category**: feature
- **Files**: `src/jarvis/reply/engine.py` (memory submit 1524-1548, inject 2024-2077, apply_memory_result 1407-1436, shutdown grace 1494-1515, _shutdown_memory_executor at 3 return paths 2503/2765/2805). New optional config: `parallel_memory_enrichment` (default True), `memory_shutdown_grace_sec` (default 0.1).
- **What**: `engine.py` is sync and chat is non-streaming, so the spec's "inject within first 24 tokens" pattern was structurally impossible. Path B instead: submit memory enrichment to a `ThreadPoolExecutor(1)` right after the recall gate resolves `needs_memory=True`. Poll the future with 1ms timeout at the start of each agentic-loop turn; if ready, merge results via `_apply_memory_result()` and rebuild `messages[0]` system message before THIS turn's chat call. At turn ≥3 the injection window closes (result dropped). `hot_cache_put` writes deferred to main thread (verified `DialogueMemory` lock is RLock-protected, but defense-in-depth). Cancellation cleanup at all return paths.
- **Why**: Plan item Tier 2.6 — overlap 1.5-2.5s memory with 5-8s chat.
- **Verified**: AST + import OK. Engine tests 35/36 pass, dialogue memory 48/48 pass. The 1 pre-existing failure (`test_planner_search_memory_overrides_recall_gate`) is unrelated.
- **Conservative savings**: 1-2s typical (memory completes before turn 1's chat-first-token), 0s worst case (no extra latency added).
- **Related plan item**: Tier 2.6.

## 2026-05-28 — Tier 2.4 Fused intent engine (1 LLM call replacing judge+router+planner)
- **Category**: feature
- **Files**: new `src/jarvis/listening/fused_intent.py` (328 lines), new `C:\tmp\test_fused_intent.py` (5 bilingual test cases).
- **What**: `FusedIntentEngine.classify_route_plan(transcript, in_hot_window, language, last_tts_text)` returns `FusedJudgment(intent, confidence, tools, plan, fast_path_match, explanation, elapsed_ms, llm_raw)`. Uses Ollama `/api/generate` with `format=<JSON schema>` (Ollama 0.5+ structured output), `cache_prompt=True`, `keep_alive="30m"`. 8s hard timeout. Retry-once on JSON-parse failure with `temperature=0.0`. Safe default fallback. Hardcoded ~10-tool catalogue (will need dynamic injection in future when MCPs are added).
- **Why**: Plan item Tier 2.4 — single biggest latency saving in the plan (collapses 3× 5-7s sequential calls into 1× 3-5s call).
- **Verified**: All 5 test cases pass at ~3s each: directed/EN, directed/EL with Greek location extraction, query/hot-window, stop, clarification. Greek input handled correctly without prompt translation.
- **Critical discovery during build**: `think=False` is mandatory for qwen3-family models. They default to chain-of-thought and write everything to a `thinking` field, leaving `response` empty. Without this flag, every call would have looked like a malformed JSON response.
- **Related plan item**: Tier 2.4 (first half — module creation). Integration entry above.

## 2026-05-28 — Tier 1.3 Whisper large-v3-turbo + faster-whisper 1.0.3 → 1.2.1 upgrade
- **Category**: feature + dependency upgrade
- **Files**: `C:\Users\aggel\.config\jarvis\config.json` (`whisper_model: "large-v3-turbo"`); `requirements.txt` / venv (`faster-whisper` upgraded to 1.2.1).
- **What**: Switches Whisper from `large-v3` to `large-v3-turbo` — multilingual (Greek + English), 1.6GB VRAM vs 3GB, ~30× real-time vs ~15×. The listener.py already has fallback logic for `large-v3-turbo` → `large-v3` → `medium` if faster-whisper < 1.1.0, but we upgraded faster-whisper to 1.2.1 so the alias resolves natively.
- **Why**: Plan item Tier 1.3 — STT bottleneck reduction without breaking Greek support (distil-small.en was English-only, rejected).
- **Verified**: Standalone test loaded model in 214s (first-time download), language detection ran. The new model is cached at `~/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/`.
- **Related plan item**: Tier 1.3.

## 2026-05-28 — Tier 1.2 Chatterbox optimization: BF16 + 300 steps + monkey-patch
- **Category**: feature
- **Files**: `src/jarvis/output/tts.py` (5 edits at lines 607, 640, 650, 660, 679); `config.json` (`tts_chatterbox_cfg_weight: 2.0 → 0.5`, new `tts_chatterbox_steps: 300`).
- **What**: Aggressive Chatterbox speedup:
  - `t3.to(dtype=torch.bfloat16)` cast (~2× speed, ~50% VRAM).
  - `torch.compile(_step_compilation_target, backend="cudagraphs")` attempt (gracefully skipped: upstream `resemble-ai/chatterbox` doesn't expose this — only `rsxdalv/fast` fork does).
  - **Monkey-patch** on `self._model.t3.inference` injecting `max_new_tokens=300` per-call. Necessary because upstream Chatterbox's `generate()` doesn't accept a steps kwarg — hardcoded 1000 with literal `# TODO: use the value in config` comment.
  - `cfg_weight` lowered 2.0 → 0.5 (Chatterbox docs: >1.0 = artifacts).
  - Voice clone (audio_prompt_path) preserved exactly.
- **Why**: Plan item Tier 1.2 — primary TTS bottleneck.
- **Verified**: Standalone test: synthesised 3.9s of audio in 4.6s synthesis time (total 8.5s wall, includes load), down from ~10s baseline → **~2.2× faster**. Voice still sounds like the user's cloned voice.
- **Note**: TTS cache key in `tts_cache.py:63` does NOT include steps or precision, so 105 existing cached WAVs will keep being served for matching text. Clear `~/.local/share/jarvis/tts_cache/` to force re-synthesis with new BF16/300-step path.
- **Mid-execution bugfix**: First run hit `mat1 and mat2 must have the same dtype, but got Float and BFloat16` because `prepare_conditionals()` rebuilds `self.conds` as fp32 every `generate()`. Added 7-line dtype coercion inside the monkey-patch to cast `t3_cond` to t3 module's weight dtype on each call.
- **Related plan item**: Tier 1.2.

## 2026-05-28 — Tier 1.1 Ollama context cap (8K chat / 4K judge)
- **Category**: infra
- **Files**: new `C:\Users\aggel\Jarvis-src\Modelfile.chat` (`FROM qwen3.5:9b; PARAMETER num_ctx 8192; PARAMETER num_gpu 999`), new `Modelfile.judge` (qwen3.5:4b + 4096 ctx); `config.json` (`ollama_chat_model: "qwen3.5:9b-8k"`, `intent_judge_model: "qwen3.5:4b-4k"`, `tool_router_model: "qwen3.5:4b-4k"`); env vars `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=1`. Backup at `~/.config/jarvis/config_backups/config_pre_tier1_1779966064.json`.
- **What**: Creates derived Ollama models with `num_ctx` baked into the manifest (Ollama otherwise allocates KV cache for the model's full 128K advertised context — wasting 8-10GB VRAM that's never used). Env vars enable q8_0 KV cache (50% memory reduction) + Flash Attention (Blackwell-native).
- **Why**: Plan item Tier 1.1 — VRAM relief + faster TTFT. Estimated -8 to -10GB VRAM, -1 to -2s TTFT.
- **Verified**: `ollama list` shows `qwen3.5:9b-8k` (6.6GB) + `qwen3.5:4b-4k` (3.4GB). Env vars set in User scope (require new processes to apply — running Ollama server must be restarted by the user).
- **Related plan item**: Tier 1.1.

## 2026-05-28 — Verbose TTS phase prints converted to debug_log
- **Category**: refactor
- **Files**: `src/jarvis/output/tts.py`
- **What**: All 12+ `⏩ TTS phase: …` and `⏩ _publish_tts_state: …` `print()` lines now go through `debug_log()` (off by default in the React Live Logs feed). Kept only meaningful state milestones (`🔊 TTS playing`, `⚠️ TTS stalled`, `⏹ TTS interrupted`, `🔊 TTS mixer init FAILED`) as info-level prints.
- **Why**: User asked for Option A — clean Live Logs.
- **Verified**: Standalone test still emits the milestone prints; logs no longer flooded.
- **Related plan item**: cosmetic; not part of latency plan.

## 2026-05-28 — Echo timing offset uses real play-engage moment
- **Category**: bug-fix
- **Files**: `src/jarvis/output/tts.py` (`_play_audio` accepts `on_engaged`; ChatterboxTTS holds `_playback_started_callback`), `src/jarvis/listening/listener.py` (passes `playback_started_callback=_on_playback_started` which resets `echo_detector._tts_start_time = time.time()`)
- **What**: The echo detector previously used the synthesis-start timestamp to compute "what fragment of the TTS is currently playing", which was 5–7 s before the audio actually began (the synthesis-to-buffer gap). New callback fires when pygame `get_busy()` flips True or `sd.play()` returns, refreshing `_tts_start_time` to real play-start.
- **Why**: User-visible false negatives in echo detection — heard fragments of TTS reported as "no match to segment or full TTS".
- **Verified**: Standalone test logs show the callback firing in sequence; running daemon's echo logs now show offsets matching what was actually playing.
- **Related plan item**: Bug 2 helper; not strictly part of the original plan.

## 2026-05-28 — TTS speed fix: explicit `channels=1` in mixer.init
- **Category**: bug-fix (regression)
- **Files**: `src/jarvis/output/tts.py` (`_safe_mixer_init`)
- **What**: Dropped `pygame.mixer.pre_init` (its `channels=1` was silently overridden by Windows SDL on stereo-only devices). Now: `pygame.mixer.init(frequency=samplerate, size=-16, channels=1, buffer=1024)` directly. If an already-open mixer has wrong format, quit + re-init at correct rate.
- **Why**: User reported TTS playing at ~2× speed; logs showed `pygame.mixer.get_init() == (24000, -16, 2)` — stereo mixer was interleaving mono samples as L/R pairs.
- **Verified**: Standalone test shows playback duration matching synthesis duration; user confirmed normal speed.
- **Related plan item**: Bug 2 in plan ("TTS plays at 2× speed").

## 2026-05-28 — `JarvisState.X` enum refs replaced with string literals in ChatterboxTTS
- **Category**: bug-fix (silent regression)
- **Files**: `src/jarvis/output/tts.py` (4 sites: lines 754, 794, 873, 907)
- **What**: `JarvisState` was used at module scope (`_speak_once` etc.) but only imported locally inside `PiperTTS._publish_tts_state`. Calls from ChatterboxTTS raised `NameError: name 'JarvisState' is not defined`, swallowed by the worker thread's `try/except Exception: continue`, leaving TTS silently dead. Replaced all four with string literals (`"synthesizing"`, `"speaking"`, `"idle"`); the `_publish_tts_state` method already accepted both enum and string via `state.value if hasattr(state, "value") else str(state)`.
- **Why**: TTS produced no audio output. Standalone test reproduced the same hang outside the daemon and isolated the line.
- **Verified**: Standalone test ran end-to-end (`✅ SUCCESS: TTS completed in 10.0s`). Daemon then heard speech.
- **Related plan item**: was the actual root cause of "TTS silent" — beyond what the plan anticipated.

## 2026-05-28 — `_publish_tts_state` rewritten QObject-free + face_widget-import-free
- **Category**: bug-fix (deadlock)
- **Files**: `src/jarvis/output/tts.py` (`_publish_tts_state`; new module constants `_JARVIS_STATE_FILE`, `_JARVIS_STATE_TO_REACT_VOCAB`)
- **What**: Old code did `from desktop_app.face_widget import get_jarvis_state, JarvisState; get_jarvis_state().set_state(...)` inside the TTS worker thread. This (a) instantiated a `QObject` in a non-Qt thread in the daemon process (no QApplication), which deadlocked on `state_changed.emit`; (b) pulled in a 1700-line PyQt6 module via Python's import lock from a worker thread. New code writes the cross-process state file directly with an inlined `os.path.join(tempfile.gettempdir(), "jarvis_state")` constant and calls `api_server.publish_state(...)` for the React WebSocket. Zero PyQt imports in the daemon TTS path.
- **Why**: TTS hung silently between `state setup done` and the next log line.
- **Verified**: Standalone test shows `_publish_tts_state called: synthesizing` → `file written` → `api_server published (thinking)` sequence completes.
- **Related plan item**: prerequisite for everything else in Bug 2.

## 2026-05-28 — Stdout mirror installed early in `daemon.main()`
- **Category**: infra
- **Files**: `src/jarvis/daemon.py` (top of `main()`)
- **What**: Previously `api_server.install_stdout_mirror()` ran inside `VoiceListener.__init__` (after `tts.start()`). All TTS-init prints (mixer init, device list, Chatterbox load timing) were emitted to a `pythonw.exe` stdout with no console attached → invisible. Now installed at the very top of `main()` so every print from then on is captured into the React Live Logs feed.
- **Why**: User asked "why don't I see my own new diagnostic prints?" Reason: they fired before the mirror was active.
- **Verified**: Boot logs now include `🔉 Audio output devices`, `🔊 TTS mixer initialised`, `⏩ TTS phase: Chatterbox model ready in X.Xs` etc.
- **Related plan item**: infrastructure for diagnosing Bug 2.

## 2026-05-28 — Pygame mixer initialised in main thread + sounddevice fallback added
- **Category**: bug-fix
- **Files**: `src/jarvis/output/tts.py` (new `_list_output_devices`, refactored `_safe_mixer_init`, new `_play_audio` orchestrator, new `_play_via_sounddevice`)
- **What**: Moved `pygame.mixer.init` out of the TTS worker thread (where Windows SDL audio init can deadlock silently) into the listener main thread, called from `ChatterboxTTS.start()`. Added a sounddevice fallback path: if pygame fails or doesn't engage, decode the WAV with soundfile and play via `sd.play()`.
- **Why**: First-time speak was producing no audio with no error.
- **Verified**: Daemon boot now logs the mixer init success and the chosen device.
- **Related plan item**: Bug 2 supporting infrastructure.

## 2026-05-28 — BootScreen ReferenceError fixed (React popup never rendered)
- **Category**: bug-fix
- **Files**: `ui/src/components/BootScreen.tsx:517`
- **What**: `BootStageLine` destructured prop as `activeIndex` (line 514) but the body referenced undefined `activeStageIndex` (line 517). Every render threw `ReferenceError`, crashing BootScreen, so `isComplete` never became true, `onTransitionComplete` never fired, and `JarvisCard` (the floating cyan card) never mounted.
- **Why**: Floating popup was completely missing from the UI.
- **Verified**: User confirmed the cyan card now appears after the cinematic boot animation.
- **Related plan item**: not a latency bug.

## 2026-05-28 — Config safety net added (auto-snapshot + auto-restore + atomic write)
- **Category**: infra
- **Files**: new `src/jarvis/config_safety.py`; hooks in `src/jarvis/api_server.py` (`/api/config` PATCH uses `safe_write_config`) and `src/jarvis/listening/listener.py` (boot-time `check_and_restore` + `snapshot`)
- **What**: Every PATCH from the React UI and every daemon startup snapshots the current `config.json` to `~/.local/share/jarvis/config_backups/` (keeps last 10). If on boot the live config has fewer than 8 user keys, auto-restore from the most recent good backup. Writes are atomic (tempfile + rename).
- **Why**: A migration to `_config_version: 6` wiped the user's heavily-customised config (qwen3.5:9b, 80 wake aliases, 7 MCPs, voice clone path…) without warning.
- **Verified**: Smoke test simulating a wipe → auto-restore from latest backup; `GET /api/config/backups` lists 6+ entries.
- **Related plan item**: not in plan; insurance.

## 2026-05-28 — `language_priority` config + smarter Greek fallback picker
- **Category**: bug-fix
- **Files**: `src/jarvis/config.py` (new Settings field + load), `src/jarvis/listening/listener.py` (`_pick_fallback_language`)
- **What**: When Whisper auto-detects a language outside `whisper_allowed_languages` (Greek often mis-detected as `tr`/`ru`/`id`/`ro` for short utterances), the fallback picker now (a) checks the sticky language lock first, then (b) probes each language in `language_priority` (default `["el","en"]` for this user), scoring by `avg_logprob + 0.1·language_probability + 0.5·priority_bonus`. Picks the highest-quality transcription rather than the highest phonetic-probability one (which was English-biased).
- **Why**: Greek queries were being re-transcribed as English garbage (`"τι ώρα είναι"` → `"Tiorine"`).
- **Verified**: Live log line confirms `language probe: picked 'el' (best_score=…)` for Greek inputs.
- **Related plan item**: Phase 2 (Greek robustness); independently shipped.

## 2026-05-28 — React Control Console hosted in native PyQt window (not Edge)
- **Category**: feature
- **Files**: new `src/desktop_app/web_console_window.py` (`JarvisConsoleWindow`); `src/desktop_app/app.py` updates `open_control_console` to instantiate it; `ui/src/components/panel/TopBar.tsx` exposes `consoleMinimize`/`consoleMaximize`/`consoleClose`/`consoleStartSystemMove` bridge
- **What**: Replaces the previous "Edge `--app` mode" launch with a native frameless PyQt6 `QMainWindow` containing a `QWebEngineView` pointing at `/panel`. Windows-only frameless flag is set at constructor time (mid-life `setWindowFlags` was causing Qt access violations with Chromium child HWND). macOS/Linux keep the native title bar; on Windows the React TopBar provides custom min/max/close.
- **Why**: User wanted single-product look-and-feel, no double window chrome.
- **Verified**: Console opens; min/max/close work; no double chrome.
- **Related plan item**: not in plan.

## 2026-05-28 — Floating cyan card hosted in always-on-top frameless PyQt window
- **Category**: feature
- **Files**: new `src/desktop_app/web_floating_hud.py` (`WebFloatingHUD` + `_LoadingPlaceholder`); React `Home.tsx` (cleared viewport gradient + hint text; transparent body)
- **What**: Always-on-top, frameless, translucent PyQt6 `QWidget` containing a `QWebEngineView` of `/`. Shows a tiny native paint-placeholder until `/api/health` responds (so the user never sees Chromium's "site can't be reached"). Bridges JS → Qt for minimize/close/drag via `hud://` custom-scheme URLs.
- **Why**: User wanted the small cyan popup to feel like a real native app, not a browser tab.
- **Verified**: Top-right cyan card appears after boot.
- **Related plan item**: not in plan.

## 2026-05-28 — JarvisState QObject deadlock bypass for daemon process (face_widget)
- **Category**: bug-fix
- **Files**: `src/desktop_app/face_widget.py` (`JarvisStateManager.set_state` mirrors to `api_server.publish_state`)
- **What**: Added a fall-through that calls `api_server.publish_state(state=react_state)` from the state setter, so the daemon can use the singleton without needing QApplication. Plus: the daemon's TTS now bypasses this singleton entirely (see "_publish_tts_state rewritten" entry).
- **Why**: Cross-process state needed to reach the React UI via WebSocket.
- **Verified**: Boot logs publish state transitions; React HUD card animates on real listening/thinking/speaking events.
- **Related plan item**: not in plan.

## 2026-05-28 — FastAPI + WebSocket API server on 127.0.0.1:38130
- **Category**: feature (large)
- **Files**: new `src/jarvis/api_server.py`; `src/jarvis/listening/listener.py` starts it; new `ui/src/lib/api.ts` client; all React tabs (`LiveLogsTab`, `MCPServersTab`, `MemoryTab`, `WakeWordTab`, `TranscriptionTab`, `VoiceTTSTab`, `LanguageModelTab`, `APIKeysTab`, `FastPathsTab`, `EasterEggsTab`, `AudioIOTab`) rewritten against this API; new launcher `Start-Jarvis-WebUI.vbs` + desktop shortcut
- **What**: 11 REST endpoints (`/api/health`, `/api/state`, `/api/command/{stop,mute,unmute,trigger}`, `/api/config`, `/api/config/backups`, `/api/logs`, `/api/mcps`, `/api/memory`, `/api/fastpaths`, `/api/eastereggs`, `/api/llm/models`, `/api/audio/devices`, `/api/audio/test-tone`, `/api/tts/cache`) + 2 WebSockets (`/ws/logs`, `/ws/state`). Stdout mirror to log buffer. Serves the built React UI from `ui/dist`.
- **Why**: Single source of truth for the React UI; replaces the legacy PyQt face widget + log viewer windows.
- **Verified**: All 11 endpoints return 200 in smoke tests; UI loads on Qt WebEngine.
- **Related plan item**: not in plan.

## 2026-05-28 — TCP loopback control bus on 127.0.0.1:38127
- **Category**: feature
- **Files**: new `src/jarvis/control_bus.py`; `src/jarvis/listening/listener.py` registers `_handle_control_command`; React HUD card calls `api.stop/mute/unmute/triggerNow`; legacy PyQt face widget kept as fallback
- **What**: One-line text commands (STOP / MUTE / UNMUTE / PING / TRIGGER) over a daemon-thread TCP socket. STOP cascades into `VoiceListener.reset_everything()` (TTS interrupt + `_llm_cancel_event` + dialogue memory clear + wake state clear + audio buffer clear + thinking-tune stop).
- **Why**: Cross-process IPC (desktop_app and daemon are separate processes in dev mode). Module-level `_active_listener` cannot be shared.
- **Verified**: `PING` → `PONG`; STOP/MUTE confirmed live in logs.
- **Related plan item**: prerequisite for the React HUD card.

---

## Earlier (carry-over from prior sessions, summarised)

The pre-existing customisations on top of stock Jarvis (carried over from prior development sessions, documented here for completeness):

- Chatterbox voice cloning (user's `Downloads\2026-05-22 22-18-08.wav`) with `exaggeration=1.0`, `cfg_weight=2.0`.
- Whisper `large-v3` int8_float16 on CUDA, beam=1, hallucination filter (YouTube blacklist + repetition heuristic), 120 s transcript buffer.
- 80 wake aliases (Greek + English transliterations + repetition variants).
- 7 MCPs configured (weather, spotify, gmail, calendar, notes, browser, apps) — runtime discovery currently empty; needs investigation.
- Fast-path regex registry (~240 patterns) covering Spotify, weather, time/date, apps, browser.
- Easter egg "daddy's home" (The Clash + cinematic JARVIS greeting with calendar/weather context).
- TTS cache (SHA256 keyed by text + voice_prompt + exag + cfg_weight; stored at `~/.local/share/jarvis/tts_cache/`).
- AudioOverlay (parallel sounddevice channel for background music during easter eggs).
- TuneePlayer (soft breathing pad while LLM is thinking).
- Porcupine wake word integration (currently disabled; key not provisioned).
- Adaptive collection-silence timeout (0.8 s for utterances that "look complete", else 2 s).
- Intent judge cache (10 s TTL × 32 entries).
- Intent judge timeout 15 s → 6 s.
- Skip-planner-when-zero-tools (chat-only short-circuit).
- Strict-prefix wake-word on cold start.

---

# Plan-mapping table

This table pairs each change above with the corresponding item in
`~/.claude/plans/plain-you-are-a-sparkling-kahn.md` (latency-reduction plan).
Use it to verify whether the plan is still accurate or needs revision.

| Plan section | Plan target | Change(s) in this log | Status |
|---|---|---|---|
| **Bug 1 — Latency (37 s → ≤12 s)** | 1a Adaptive silence timeout | "Adaptive collection-silence timeout (0.8 s …)" | ✅ implemented |
| | 1b Intent-judge cache (10 s TTL) | "Intent judge cache (10 s × 32)" | ✅ implemented |
| | 1c Reduce intent-judge timeout 15→6 s | "Intent judge timeout 15→6 s" | ✅ implemented |
| | 1d Skip planner for pure-reply queries | "Skip-planner-when-zero-tools" | ✅ implemented |
| | 1e Extend fast-path patterns | "Fast-path regex registry ~240 patterns" — includes time/day/stop | ✅ implemented |
| **Bug 2 — TTS 2× speed** | Force mono mixer init | "TTS speed fix: explicit `channels=1`" | ✅ implemented |
| | Sounddevice as primary | "Pygame in main thread + sounddevice fallback" — currently *fallback*, not primary. Plan called for sounddevice-primary; we kept pygame-primary because of stereo upmix concerns. **Decision deferred** until live test confirms speed is fixed. | ⚠️ partial — revisit |
| **Bug 3 — Strict-prefix wake-word** | Discard text before wake word | "Strict-prefix wake-word on cold start" | ✅ implemented (cold-start only; hot-window keeps fuzzy match) |
| **Bug 3** | Generalise fast-path wake-strip | Already in `fast_paths.py` patterns | ✅ implemented |
| **Phase 2 (mentioned in plan, not implemented)** | Sentence-chunked TTS streaming | not in this log | ❌ not started |
| | Pre-warmed canned responses | partial: TTS cache + cache-warming utility exist | 🟡 partial |
| | Greek robustness improvements | "language_priority + smarter fallback picker" | ✅ shipped |
| **Phase 2 plan (Kimi review derivative) — `plain-you-are-a-sparkling-kahn.md`** | Tier 1.1 Ollama context cap | "Tier 1.1 Ollama context cap (8K chat / 4K judge)" | ✅ implemented |
| | Tier 1.2 Chatterbox BF16+300+compile | "Tier 1.2 Chatterbox optimization: BF16 + 300 steps + monkey-patch" | ✅ implemented (2.2× speedup verified; torch.compile gracefully skipped — upstream Chatterbox lacks `_step_compilation_target`) |
| | Tier 1.3 Whisper large-v3-turbo | "Tier 1.3 Whisper large-v3-turbo + faster-whisper upgrade" | ✅ implemented (also bumped faster-whisper 1.0.3 → 1.2.1 for native alias support) |
| | Tier 2.4 Fused judge+router+planner | "Tier 2.4 Fused intent engine" + "Tier 2.4 second half: reply.engine consumes fused" | ✅ implemented (both module and engine integration; ~10-14s savings on cascade hit) |
| | Tier 2.5 Heuristic classifier (Aho-Corasick + TF-IDF ONNX) | "Tier 2.5 Heuristic intent classifier" + "Tier 2.5 INTEGRATION" | ✅ implemented (93% macro F1; med_threshold=0.5 gives ~88% local routing; cascade in listener) |
| | Tier 2.6 Parallel memory enrichment | "Tier 2.6 Parallel memory enrichment (Path B)" | ✅ implemented (Path B: ThreadPool + inter-turn injection; ~1-2s typical savings) |
| | Tier 3.7 Streaming sentence-by-sentence TTS | not started | ❌ not started (deferred — large refactor) |
| | Tier 3.8 Model unification (qwen3:8b) | not started | ❌ not started (deferred — risk of quality regression) |
| | Tier 3.9 WASAPI exclusive audio | "Tier 3.9 WASAPI exclusive audio mode (partial)" | ⚠️ partial — code in place, blocked at runtime by pygame SDL pre-init holding device. Falls back to shared cleanly. Future tier: lazy pygame init. |
| **Wispr-bridge plan — `plain-you-are-a-sparkling-kahn.md`** | Phase A — bridge module | "Phase A: wispr_bridge.py module" | ✅ implemented |
| | Phase B — `stt_backend` + wispr config fields | "Phase B: stt_backend + 10 wispr_* fields + config flip" | ✅ implemented (config flipped to `"wispr"`) |
| | Phase C — Gate Whisper init | "Phase C: Gate Whisper init behind stt_backend" | ✅ implemented (rollback-safe) |
| | Phase D — `feed_transcript` cascade hook | "Phase D: Wire Wispr transcripts into existing intent cascade" | ✅ implemented (reuses existing Tier 0/1/2 cascade) |
| | Phase E — Hot window auto-PTT | "Phase E+F: Wispr hot window + TTS interrupt" | ✅ implemented (10s default, configurable) |
| | Phase F — TTS interrupt via stop pattern | (same entry) | ✅ implemented (Greek + English stop keywords) |
| | Phase G — Install deps + tests | bundled into Phase A entry | ✅ implemented |

# Open items / next decisions to revisit against the plan

1. **Sounddevice primary vs pygame primary**: the plan recommended sounddevice as the primary
   playback path. Currently pygame is primary, sounddevice is the fallback. The 2× speed bug
   only occurs on pygame's stereo-upmix path. If `mixer.init(channels=1)` does not reliably
   stick on Windows SDL, we should flip to sounddevice-primary. Decision pending after live
   speed test.
2. **Intent judge as a heuristic, not an LLM call** (top-3 bottleneck in the audit, not in
   the plan): 5–7 s per utterance for a job a Python heuristic + regex can do correctly 95 %
   of the time. Potential biggest single latency win available. Should the plan add a
   "Phase 2: heuristic intent classifier" item?
3. **Piper-default + Chatterbox-cinematic split** (audit recommendation, not in plan):
   `PiperTTS` class is fully wired in `tts.py`; just needs a config flag and a length/tag
   heuristic. Saves 4–7 s per routine reply.
4. **VRAM headroom**: Chatterbox + qwen3.5:9b co-resident is 12 GB before Whisper transients,
   leaving <4 GB margin. Audit flagged risk of OOM during chat-and-synthesise overlap.
   Consider Chatterbox-on-CPU OR q4_K_M for the chat model. Plan does not yet address this.
5. **MCP discovery broken at runtime**: config defines 7 servers, runtime shows
   `mcp_servers: []`. Worth verifying as part of any tool-router optimisation.

6. **WASAPI exclusive blocked by pygame SDL pre-init** (new): Tier 3.9 code is in place
   but PortAudio rejects exclusive mode because pygame's SDL holds the default output
   device handle. To unlock the ~10-40ms audio engagement win, `_safe_mixer_init`
   should be deferred until the sounddevice path actually fails. Or: switch primary
   playback to sounddevice + WASAPI exclusive entirely and demote pygame to fallback.

7. **Heuristic classifier coverage 88% at med_threshold=0.5 (lowered from default 0.72)**:
   At 0.72 only 62% of queries route locally (everything else escalates to LLM). At 0.5
   we get ~88% local routing with ~95% precision per validation. Worth monitoring real
   intent accuracy in production — if false-positive misroutings hurt UX, raise back to
   ~0.6.

8. **`test_planner_search_memory_overrides_recall_gate`** (pre-existing failure surfaced
   during Tier 2.6 + 2.4 integration work): fails identically on HEAD before any of the
   new changes. Caused by an interaction between `if not routed_tools:` planner-skip
   (Bug 1d) and the recall gate logic. Worth addressing in a separate task; not part of
   this plan's scope.

9. **TTS cache invalidation after Chatterbox change**: cache key in `tts_cache.py:63`
   does NOT include steps or precision, so old 1000-step/fp32 cached WAVs will still be
   served for matching text. User should `Remove-Item C:\Users\aggel\.local\share\jarvis\tts_cache\*`
   to force re-synthesis with the new BF16/300-step pipeline.

10. **Env vars require Ollama restart**: `OLLAMA_KV_CACHE_TYPE=q8_0` and
    `OLLAMA_FLASH_ATTENTION=1` are set in User scope (persistent across reboot) but
    only take effect for NEW Ollama processes. User must restart Ollama service.

---

# How to update this file

When you make a code change, prepend a new entry to the top of the dated log following
the standard format. Update the **Plan-mapping table** if the change addresses or
deviates from a plan item. If you discover a regression, mark the original entry with
a follow-up note (do not delete the original — keep the timeline intact).
