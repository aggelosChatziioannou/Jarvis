# Reminder Subsystem Spec

Covers the time-triggered reminder feature: the `reminders` store, natural-language
time parsing, the poll-loop firing tick, delivery (TTS + tray toast + HUD event), and
the four reminder tools. Reminders are scheduled actions, **not** memory — they never
touch the graph/diary memory system.

## Key principles

- **Local-first / privacy.** Reminders live in SQLite at `cfg.db_path` (the same
  `jarvis.db`); parsing uses the local `dateparser` and, only when needed, the local
  Ollama model. No cloud.
- **No separate scheduler.** Firing reuses the daemon's existing poll loop
  (`daemon.py` `main()`), throttled by `reminder_check_interval_sec` (1–5 s). No
  APScheduler, no background scheduler thread, no extra persistence layer.
- **Fail-open.** Every firing tick is wrapped so a parser/DB/croniter error can never
  crash the daemon or the voice pipeline. Missing optional deps degrade, they don't break
  (no `dateparser` → LLM fallback; no `croniter` → recurring reminders park as `missed`).
- **Parsing fails closed.** If no time can be resolved, no reminder is created — a
  wrong-time reminder is never invented.
- **British English, emoji-prefixed user output, `debug_log` at flow points** (channel
  `"reminders"`), per project conventions.

## Data model (`reminders` table, owned by `ReminderStore`)

`id` (UUID), `text`, `trigger_at` (UTC ISO), `recurring_rule` (NULL or 5-field cron),
`status`, `snooze_until` (UTC ISO), `created_at`, `source`. Timestamps are normalised to
UTC on write so lexical ordering equals chronological ordering (DST-safe); they are
returned as tz-aware datetimes. `ReminderStore` opens its **own** connection + lock so the
firing tick never contends on the shared memory `Database` lock (WAL keeps them coherent).

### Status lifecycle

```
pending  --(due, within grace)-->            delivered:
            one-time   -> completed
            recurring  -> pending (next cron occurrence)
pending  --(due, beyond grace)--> missed (silent)        # daemon was offline
pending/snoozed --(cancel)--> cancelled                  # inert
pending  --(snooze)--> snoozed --(snooze_until elapses)--> re-fires
```

One-time reminders are terminal after first due. Recurring reminders re-arm to the next
**strictly-future** cron occurrence computed from *now*, so occurrences missed while the
daemon was offline are skipped, not replayed.

## Firing contract

`firing.fire_due_reminders(store, cfg, tts, now, deliver=...)` runs once per throttled poll
tick. It selects `due()` (pending past `trigger_at`, or snoozed past `snooze_until`),
applies the grace window (`reminder_grace_window_sec`, default 300 s), delivers within
grace, and transitions status. **Idempotent:** a fired reminder is immediately moved out of
the `due()` predicate (completed / missed / rescheduled-to-future), so it can't fire twice
across consecutive ticks. The tick does no blocking I/O on the hot path (TTS enqueues; the
toast is a `print`).

## Parsing contract (`parser.parse_when`)

Cheapest path first: (1) recurrence — a leading/standalone `every`/`κάθε` with a resolvable
weekday or daily marker + time becomes a cron string; (2) `dateparser` resolves EL/EN
relative and EN absolute phrases to a future instant; (3) a strict, low-temperature LLM
fallback (warm router-model chain, fenced untrusted input) returns an ISO datetime, a cron
string, or `NONE`. The EN/EL recurrence table is a deterministic fast path for the two
declared product languages; other languages still resolve via dateparser (multilingual) or
the LLM fallback, so the assistant is not limited to EN/EL.

## Delivery (`delivery.speak_and_toast`) — core/desktop decoupling

The single seam that touches output. Core **never imports Qt / desktop_app**. A fired
reminder:
1. speaks via core TTS (`get_tts_engine().speak("Reminder: …")`), gated by
   `reminder_speak_on_fire`;
2. emits a tray toast over stdout IPC — a `__REMINDER__:<json>` line (mirroring the
   `__DIARY__:` precedent). The desktop app's log reader parses it and shows a native
   `QSystemTrayIcon` toast **on its GUI thread**. The IPC JSON is ASCII-escaped so a cp1252
   Windows console can't crash on non-Latin text;
3. publishes a `reminderFired` field via `api_server.publish_state` for the React HUD.

Each channel is best-effort; a failure in one never blocks the others.

## Tools

`createReminder`, `listReminders`, `cancelReminder`, `snoozeReminder` — each exposes a
single optional `text` property (planner fast-path), opens its own `ReminderStore`, and
returns raw data (no LLM formatting), per the tool contract. `createReminder` computes a
recurring reminder's first fire via `croniter` and fails closed on unparseable time.

## Configuration

`reminders_enabled`, `reminder_check_interval_sec` (clamped 1–5), `reminder_grace_window_sec`,
`reminder_default_snooze_min`, `reminder_speak_on_fire`, `reminder_parse_timeout_sec`. All
have safe defaults and are read via `getattr`, so the feature works even before config is
written.

## Known v1 limitations

- `createReminder` stores the full phrase as the reminder text (the spoken body may include
  the time words). Separating "what" from "when" in a long sentence leans on the LLM
  fallback.
- `snoozeReminder` snoozes the soonest active reminder; re-pending a just-fired (completed)
  one-time reminder is a future enhancement.
