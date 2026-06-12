# Wake-word Recording Studio — spec

Guided, resumable recording sessions that produce **trainer-ready wake-word
data** (real positives, known-text negatives, phonetic-trap hard negatives and
room-ambience beds) for custom openWakeWord training. Greek-first CLI, generic
over the wake phrase — anyone can use it to train their own voice/phrase.

## Principles

- **The session plan is the source of truth.** `session_plan.build_plan()` is
  deterministic: stable `prompt_id`s, config-driven counts (`PlanConfig`).
  Tests assert counts follow the config, never hardcoded totals.
- **Guided means QC at capture time.** Every take is analysed on the spot
  (`qc.analyse`): clipping, condition-aware level floor (a 4.5 m clip is
  legitimately quieter than a 0.3 m one — see `RMS_FLOORS_DBFS`), and a
  did-you-actually-speak gate. Bad takes re-prompt immediately (max 3 auto
  redos, then kept with `qc_ok: false` in the manifest).
- **Resume over restart.** Stopping (`q`) is safe at any point. A prompt is
  complete once any take is saved; `remaining_items()` = plan minus the
  manifest's completed `prompt_id`s, across days.
- **Auditable data.** Every clip gets a manifest row with the EXACT text
  spoken, language, distance, noise condition, style, level stats and
  timestamp. "What was I reading in clip 0142?" must always be answerable.
- **Privacy.** Recordings and manifests live under
  `~/.local/share/jarvis/wakeword/studio_sessions/` — never inside the repo,
  never committed. Only the tool + reading script ship.

## Clip contract (trainer compatibility)

16 kHz, mono, 16-bit PCM WAV, ≥ 1.0 s — identical to the v1 pipeline
(`_split_wakeword.py` / `_inject_real_positives.py` validation). Reading/trap
takes are edge-trimmed with 150 ms context pads (`qc.trim_pad`); positives keep
their fixed window (2.8 s); beds are long-form ambience.

## Programme structure (default `PlanConfig` ≈ 75 min)

| Block | Items | Conditions |
|---|---|---|
| Quiet bed | 1 × 4 min | room tone, no speech |
| Clean positives | 5 distances × 14 styles/reps | normal/fast/slow/loud/soft/sleepy/question |
| Clean reading | all 40 script lines | EL + EN, known text |
| Traps | 12 trap lines × 3 | phonetic near-misses, quiet |
| Per music condition (med/loud/speech-bg) | positives at 1 m + 3 m, reading subset, 3-min bed | one setup banner per condition |

Setup banners (move to distance X / start Spotify at volume Y) appear **only
when the condition changes**, so the user moves once per block.

## Reading script (`reading_script.json`)

- `kind: read` — natural sentences in BOTH product languages, phonetically
  diverse, biased towards assistant-style commands (they surround real wakes).
- `kind: trap` — hard negatives phonetically near the wake phrase ("hey
  Travis", "σέρβις", mid-sentence "Jarvis", …). **Traps must never contain the
  wake phrase itself** (test-enforced). Bare "Jarvis" is a NON-wake by user
  decision (2026-06-12): only "Hey Jarvis" wakes.

## Safety rails

- On startup the studio probes `127.0.0.1:38130/api/state`; if the Jarvis
  daemon is listening it warns loudly (it would wake on every recorded
  "Hey Jarvis") and asks for explicit confirmation.
- `--simulate [--auto]` synthesises speech-like audio so the entire flow
  (plan → QC → manifest → resume → export) runs headless for testing. The
  audio stack (`sounddevice`) is imported lazily — pure modules stay
  importable without it.

## Trainer hand-off

`manifest.export_positives_for_trainer(session, out)` buckets positive takes
into `out/<distance>_<noise>/` (e.g. `3m_music_med/`) matching the injector's
per-folder holdout/weighting model. Negatives/traps/beds are NOT exported by
it — they feed the negative/background side of training via the v2 training
flow (separate step, WSL side).

## Tests

`tests/test_wakeword_studio.py` — QC behaviours (clipping/quiet/no-speech/
trim-pad/WAV format), shipped-script validity, plan determinism + config-driven
counts + full clean coverage of the script, manifest round-trip (Greek text),
resume semantics, export bucketing. The interactive CLI is exercised via the
simulate path.
