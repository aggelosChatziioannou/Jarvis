# Wispr Flow closed-loop sync — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans (in-session, intricate single-file integration) to implement this plan. Steps use checkbox (`- [ ]`) syntax. TDD: failing test first, minimal impl, green, commit.

**Goal:** Make the Jarvis ↔ Wispr Flow start/stop coupling a verified closed loop that self-corrects instead of permanently inverting, and fix the clipboard capture drops.

**Architecture:** A new `WisprStateProbe` reads Wispr's real recording state from its overlay window (pywin32, fail-open → `None`). The bridge becomes level-seeking (`_ensure_recording(target)`): tap only when observed != target, confirm the tap, self-correct on failure, reconcile at startup and on no-capture. Plus cheap always-on guards (configurable hotkey, min inter-tap gap) and clipboard-sequence capture.

**Tech Stack:** Python 3.11, pytest (`-m unit`), pywin32 (`win32gui`/`win32process`)+`psutil` (already vendored, see `vision/safety.py`), pynput (existing), `WisprConfig` dataclass.

**Spec:** `docs/superpowers/specs/2026-05-30-wispr-closed-loop-sync-design.md`
**Test command:** `.venv\Scripts\python.exe -m pytest tests/ -m unit`
**Pre-existing base-commit failures (do NOT attribute to this work):** ~11 across hot_window/enrichment/mcp_client/updater/VRAM.

---

## File Structure

- Create `src/jarvis/listening/wispr_state.py` — `MicUsageReader` seam (default = `winreg` mic-consent reader), `WisprStateProbe.is_recording()/available()`. One responsibility: report whether Wispr is capturing the mic (= recording), fail-open. (Window enumeration rejected by characterisation; see spec §4.4.)
- Create `scripts/characterise_wispr_overlay.py` — one-off live characterisation of the overlay discriminator.
- Modify `src/jarvis/listening/wispr_bridge.py` — inject probe; `_ensure_recording`; startup reconciliation; no-capture force-off + reason; `on_wispr_unavailable`; configurable combo; min inter-tap gap; clipboard-sequence capture.
- Modify `src/jarvis/listening/listener.py` — `_on_wispr_dictation_end(captured, reason=None)`; wire `on_wispr_unavailable`.
- Modify `src/jarvis/config.py` — declare 7 new + 2 undeclared `wispr_*` fields (dataclass + DEFAULTS + builder + constructor).
- Modify `src/jarvis/listening/listening.spec.md` — Wispr bridge closed-loop section.
- Tests: `tests/test_wispr_state.py` (new), `tests/test_wispr_bridge.py` (extend), `tests/test_config_models.py` (extend).

---

## Chunk 1: Characterisation + config

### Task 0: Characterise the overlay discriminator (live, not CI)

**Files:** Create `scripts/characterise_wispr_overlay.py`

- [ ] **Step 1:** Write a script that, using `win32gui.EnumWindows` + `win32process.GetWindowThreadProcessId` + `psutil`, snapshots every top-level window owned by a `Wispr Flow` process as `(pid, cls, title, visible, w, h, left, top)`. Print snapshot. Then tap `Ctrl+Win+Space` via `pynput`, wait 1.5s, snapshot again (recording), tap again, wait 1.5s, snapshot (idle). Diff the three.
- [ ] **Step 2:** Ensure the Jarvis daemon listener is not running (ports 38130/38127 free) so it cannot interfere. Run: `.venv\Scripts\python.exe -X utf8 scripts/characterise_wispr_overlay.py`. Repeat ≥3 times.
- [ ] **Step 3:** Acceptance: identify the attribute that changes deterministically idle↔recording (candidate: the `Status` overlay's `visible`/`on_screen`/size, or a title change). Record the discriminator in a comment at the top of `wispr_state.py`. If nothing is reliable: record that, and `WisprStateProbe.is_recording()` will always return `None` (feature degrades to guards) — the rest of the plan still ships.
- [ ] **Step 4: Commit** the script.

```bash
git add scripts/characterise_wispr_overlay.py
git commit -m "chore(voice): add Wispr overlay characterisation script"
```

### Task 1: Declare config fields

**Files:** Modify `src/jarvis/config.py` (dataclass field block ~l.170-180; DEFAULTS ~l.758-773; builder ~l.1128-1170; `WisprConfig(...)` constructor ~l.1500-1510). Test `tests/test_config_models.py`.

New: `wispr_closed_loop_enabled: bool = True`, `wispr_hands_free_combo: list[str] = ["ctrl","cmd","space"]`, `wispr_min_tap_gap_sec: float = 0.5`, `wispr_confirm_timeout_sec: float = 1.2`, `wispr_clipboard_grace_sec: float = 2.0`. Declare-only (already read in bridge): `wispr_erase_max_chars: int = 300`, `wispr_barge_in_interrupt: bool = True`. (No `wispr_state_pid_ttl_sec` — the registry probe needs no PID resolution.)

- [ ] **Step 1: Failing test** in `test_config_models.py`: assert a default-built config exposes all 7 fields with the documented defaults, and that round-tripping a config dict preserves a non-default `wispr_hands_free_combo` and `wispr_min_tap_gap_sec`. Assert types (list of str, float, int, bool).
- [ ] **Step 2:** Run → FAIL (AttributeError / missing keys).
- [ ] **Step 3:** Add the fields in all four sites following the existing `wispr_suppress_autotype` pattern exactly (dataclass annotation+default, DEFAULTS entry, builder local read with the same `.get`/coercion idiom, constructor kwarg). Match list/float/int/bool coercion to neighbours.
- [ ] **Step 4:** Run → PASS. Also run the full `-m unit` config tests to ensure no schema/migration test broke.
- [ ] **Step 5: Commit** `feat(voice): declare Wispr closed-loop + guard config fields`.

---

## Chunk 2: WisprStateProbe

### Task 2: Probe with injectable mic-usage reader (TDD, fake)

**Files:** Create `src/jarvis/listening/wispr_state.py`; Test `tests/test_wispr_state.py`.

Interface:
```python
MicUsageReader = Callable[[], bool | None]  # True=Wispr capturing mic, False=not, None=unknown

class WisprStateProbe:
    def __init__(self, reader: MicUsageReader | None = None) -> None: ...
    def is_recording(self) -> bool | None   # wraps reader() in try/except -> None
    def available(self) -> bool             # last reading was a definite True/False
```

Also expose the pure selection helper for unit testing:
```python
def recording_from_consent_rows(rows: list[tuple[str, int, int]]) -> bool | None:
    """rows = [(subkey_name, last_used_start, last_used_stop)]. Filter to Wispr
    entries; pick max-start; recording iff its stop == 0; None if no Wispr row."""
```

- [ ] **Step 1: Failing tests** (fake reader + `recording_from_consent_rows`):
  - reader returns True → `is_recording()` True, `available()` True
  - reader returns False → `is_recording()` False, `available()` True
  - reader returns None → `is_recording()` None, `available()` False
  - reader raises → `is_recording()` None (caught), `available()` False
  - `recording_from_consent_rows`: active-version row (max start, stop==0) → True; same set with a stale `stop==0` on a smaller-start row → still True via the active row; all stops != 0 → False; no Wispr row → None
- [ ] **Step 2:** Run → FAIL (module missing).
- [ ] **Step 3:** Implement `recording_from_consent_rows`, the `WisprStateProbe` wrapper, and fail-open. No real registry here.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** `feat(voice): WisprStateProbe (mic-consent read, fail-open)`.

### Task 3: Real winreg mic-consent reader backend

**Files:** Modify `src/jarvis/listening/wispr_state.py` (add `_registry_mic_reader` as the default when `reader is None`). Opt-in integration test only.

- [ ] **Step 1:** Implement `_registry_mic_reader()` using `winreg` (stdlib): enumerate `HKCU\...\ConsentStore\microphone\NonPackaged` (and the packaged store as fallback), collect `(subkey, LastUsedTimeStart, LastUsedTimeStop)` for Wispr/Flow sub-keys, and return `recording_from_consent_rows(rows)`. Wrap so non-Windows / missing `winreg` / no entry → `None`.
- [ ] **Step 2:** Add `tests/test_wispr_state.py::test_real_reader_smoke` marked `@pytest.mark.integration` (skipped under `-m unit`) asserting it runs and returns `True`/`False`/`None`.
- [ ] **Step 3:** Run `-m unit` → real backend untouched (skipped); fake-reader tests still PASS.
- [ ] **Step 4: Commit** `feat(voice): winreg mic-consent reader backend for WisprStateProbe`.

---

## Chunk 3: Bridge integration

### Task 4: `_ensure_recording` level-seeking + confirm + self-correct

**Files:** Modify `wispr_bridge.py` (constructor: add `state_probe=None`, store; build a no-op probe when closed-loop disabled). Replace the tap-decision in `_do_press_keys`/`_do_release_keys` flow with `_ensure_recording(target)`. Test `tests/test_wispr_bridge.py`.

`_ensure_recording(target)` logic per spec §4.2 (observed=None → today's `_keys_held` path; observed==target → reconcile, no tap; observed!=target → tap, confirm-poll up to `wispr_confirm_timeout_sec`, one re-tap, else return False). Confirm-poll uses injected `clock`/`sleep` seam so tests don't wall-clock wait.

> **Reviewer note (seam):** The bridge currently calls module-level `time.monotonic`/`time.sleep` directly. Task 4 Step 3 MUST add `monotonic: Callable=time.monotonic` and `sleep: Callable=time.sleep` as injectable constructor params, store them, and route both `_ensure_recording`'s confirm-poll AND Task 8's `_key_worker` gap-gate through `self._sleep`/`self._monotonic`. Tests inject a fake clock + a sleep-recorder.
> **Reviewer note (thread):** `_ensure_recording` is *called from* `_do_press_keys`/`_do_release_keys`, which already run on the key-worker thread — so the bounded confirm-poll never blocks the PortAudio callback. Unit tests may call `_ensure_recording` directly.

- [ ] **Step 1: Failing tests** with a `FakeProbe` (scriptable `is_recording` queue) + a tap-recorder:
  - desync heal: probe says recording, target True → **no** tap, `_keys_held` becomes True
  - normal start: probe says not-recording then recording-after-tap → exactly one tap, returns True
  - missed PRESS: probe stays not-recording after tap → one re-tap, then returns False
  - fail-open: probe `None` → exactly one tap (today's behaviour), `_keys_held` toggled
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `_ensure_recording`; route `_do_press_keys`→`_ensure_recording(True)`, `_do_release_keys`→`_ensure_recording(False)` while preserving the `_keys_lock` discipline and the no-op-probe fail-open path.
- [ ] **Step 4:** Run → PASS (+ existing bridge tests green).
- [ ] **Step 5: Commit** `feat(voice): level-seeking _ensure_recording with confirm + self-correct`.

### Task 5: Startup reconciliation

**Files:** `wispr_bridge.py` `start()`. Test `test_wispr_bridge.py`.

- [ ] **Step 1: Failing test:** probe reports recording at `start()` → bridge forces OFF (one tap), `_keys_held` ends False; probe `None` → `_keys_held` stays False, no tap (today). Use a fake to avoid loading real models (guard the reconciliation into a small testable method `_reconcile_initial_state()` called from `start()` so the test targets it without opening audio/models).

> **Reviewer note (synchronous tap):** `_start_dictation` enqueues taps via `_key_queue`; in a non-started test bridge nothing drains the queue. `_reconcile_initial_state()` MUST perform the force-off tap **synchronously** under `_keys_lock` (call `_do_release_keys()`/the locked tap path directly, like `_force_release_locked`), NOT via the queue, so the test observes `_keys_held` deterministically.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `_reconcile_initial_state()`; call after models load, before `audio_stream.start()`. Exempt from min-gap.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** `feat(voice): reconcile Wispr state at bridge startup`.

### Task 6: No-capture force-off + reason propagation

**Files:** `wispr_bridge.py` `_post_dictation_worker` (+ `_dispatch`/callback signature), `listener.py` `_on_wispr_dictation_end`. Tests in both suites.

- [ ] **Step 1: Failing tests:**
  - `_post_dictation_worker` with no clipboard change → fires `on_dictation_end(False, reason="timeout")`; clipboard off → `reason="off"`.
  - when probe still recording at no-capture → `_ensure_recording(False)` invoked (force-off).
  - listener `_on_wispr_dictation_end(False, reason="off")` distinguishes message vs `"timeout"` (assert via a captured notice/log, behaviour not exact string).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Add `reason` to the callback (`on_dictation_end(captured, reason=None)`, default keeps callers working); thread reason through `_post_dictation_worker`; on no-capture call force-off when probe confident; update listener handler signature + branch. **Keep the default/`"timeout"` listener notice containing the substring "transcript"** (existing `test_failed_dictation_prints_notice` asserts it); only the new `reason="off"` branch gets distinct wording. **Update existing W4 bridge-test lambdas** from `lambda captured: ...` to `lambda captured, reason=None: ...` and assert the delivered `(captured, reason)` tuple (behavioural), not just that the callback fired.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** `feat(voice): self-correct + reason on no-capture turns`.

### Task 7: `on_wispr_unavailable` + honest HUD

**Files:** `wispr_bridge.py` (`_start_dictation`: when `_ensure_recording(True)` returns False fire `on_wispr_unavailable`), constructor adds the optional callback; `listener.py` wires it (`_on_wispr_unavailable` → stop tune, notice, face back to idle). Tests both suites.

- [ ] **Step 1: Failing test:** start with a probe that never confirms → `on_wispr_unavailable` fires once and DICTATING is not entered (or is reverted) so the HUD does not falsely show listening; probe `None` → today's immediate-listening path (no `on_wispr_unavailable`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement callback + revert-on-unconfirmed; wire listener handler.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** `feat(voice): surface Wispr-unavailable instead of false listening`.

### Task 8: Configurable combo + min inter-tap gap

**Files:** `wispr_bridge.py` (`_tap_hands_free_toggle_locked` reads `wispr_hands_free_combo` → `pynput` Key map; `_key_worker` enforces `wispr_min_tap_gap_sec`). Tests.

- [ ] **Step 1: Failing tests:** a non-default combo (e.g. `["ctrl","alt","space"]`) is the exact key sequence tapped; two consecutive toggle taps are ≥ `wispr_min_tap_gap_sec` apart (use injected clock/sleep recorder); unknown key name → falls back to default combo + logs.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement a name→`pynput.Key`/char map, combo-driven press/release, and a last-tap timestamp gate in `_key_worker`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Commit** `feat(voice): configurable hands-free combo + min inter-tap gap`.

---

## Chunk 4: Capture-path + spec + verify

### Task 9: Clipboard-sequence capture

**Files:** `wispr_bridge.py` (`_start_dictation` records baseline `GetClipboardSequenceNumber()`; `_post_dictation_worker` dispatches when sequence advanced AND clipboard non-empty; non-Windows/failure → fall back to exact-text diff). Add a small `_clipboard_seq()` helper (Win32, fail → None). Tests.

- [ ] **Step 1: Failing test:** identical re-utterance (clipboard text equals baseline text but sequence advanced) → **dispatched** (today it is dropped). Plus: no change at all (sequence same) → not dispatched, `reason="unchanged"`. Fallback path (seq=None) → behaves as today (text diff).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `_clipboard_seq()` and the sequence-aware dispatch with text-diff fallback.
- [ ] **Step 4:** Run → PASS (existing `test_no_clipboard_change_reports_false` updated to the sequence semantics, kept meaningful; update any W4 `on_dictation_end` lambdas to the `(captured, reason=None)` shape).
- [ ] **Step 5: Commit** `fix(voice): clipboard-sequence capture (dispatch identical re-utterance)`.

### Task 10: Spec + docs

**Files:** `src/jarvis/listening/listening.spec.md` (new Wispr bridge section per spec §7).

- [ ] **Step 1:** Add a "Wispr bridge (openWakeWord push-to-talk) — closed-loop synchronisation" subsection: tap-and-toggle hands-free coupling, `Ctrl+Win+Space` prerequisite + configurability, `WisprStateProbe` contract (`True`/`False`/`None`, fail-open), `_ensure_recording` level-seeking, startup reconciliation, min inter-tap gap, clipboard-sequence capture, and `on_wispr_unavailable`. No `docs/llm_contexts.md` change (no LLM context altered).
- [ ] **Step 2: Commit** `docs(voice): spec the Wispr closed-loop bridge contract`.

### Task 11: Full verification

- [ ] **Step 1:** Run `.venv\Scripts\python.exe -m pytest tests/ -m unit -q`. Confirm all new tests pass and only the known ~11 pre-existing failures remain (diff against the documented base-commit list).
- [ ] **Step 2:** Run `tests/test_wispr_bridge.py` + `tests/test_wispr_state.py` + `tests/test_config_models.py` verbose to confirm green.
- [ ] **Step 3:** (Opt-in, live) re-run the characterisation/integration smoke against running Wispr to sanity-check the real probe path.
- [ ] **Step 4:** Update memory (`wispr-toggle-desync-rootcause` → note the fix shipped) and report.
