"""
Behaviour tests for :class:`jarvis.listening.wispr_bridge.WisprBridge`.

These tests exercise the pure, side-effect-light methods of the bridge
WITHOUT calling :meth:`WisprBridge.start` (which would open an audio
stream and download/load openWakeWord + Silero models). Construction is
cheap, so each test builds a fresh bridge from a stub cfg and lambda
callbacks, then drives individual methods directly.

Coverage:
  W1  _erase_autotyped_text data-loss guard (cap on backspaces)
  W3  thread-safe speaking flag (lock guards set_speaking / dispatch read)
  W4  on_dictation_end(captured: bool) contract
  W5  instant barge-in interrupt on speech onset during TTS
  W6  wake mic resolved from the persisted endpoint id (input flow)
"""

import threading
from types import SimpleNamespace

import pytest

from jarvis.listening.wispr_bridge import State, WisprBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _RecorderKeyboard:
    """Stand-in for pynput's Controller that records key events.

    Lets tests count exactly how many Backspace presses the bridge emits
    without driving a real keyboard.
    """

    def __init__(self):
        self.presses: list = []
        self.releases: list = []

    def press(self, key):
        self.presses.append(key)

    def release(self, key):
        self.releases.append(key)


class _StubVadIterator:
    """Minimal Silero VADIterator stand-in.

    Returns a fixed ``event`` for every call (or ``None``). ``reset_states``
    is a no-op so :meth:`WisprBridge._start_dictation` can call it safely.
    """

    def __init__(self, event=None):
        self._event = event
        self.calls = 0

    def __call__(self, tensor, return_seconds=True):
        self.calls += 1
        return self._event

    def reset_states(self):
        pass


def _make_bridge(**cfg_attrs):
    """Build a WisprBridge from a stub cfg + lambda callbacks.

    Extra keyword args become attributes on the stub cfg, overriding the
    bridge's getattr defaults. Returns the bridge; callers attach their own
    recorders / stubs as needed. Never calls ``start()``.

    Closed-loop sync defaults to OFF here so legacy behaviour tests are
    deterministic (the state probe returns None -> belief-only path, no real
    registry read, no real toggle tap). Tests that exercise the closed loop use
    ``_make_closed_loop_bridge`` instead.
    """
    cfg_attrs.setdefault("wispr_closed_loop_enabled", False)
    cfg = SimpleNamespace(**cfg_attrs)
    bridge = WisprBridge(
        cfg,
        on_transcription=lambda text: None,
    )
    return bridge


class _ScoringWakeModel:
    """Fake openWakeWord model: records every ``predict(frame)`` and returns a
    fixed score, so tests can assert the model is FED (the regression guard)
    independently of whether a frame is loud enough to trigger."""

    def __init__(self, score: float = 0.0):
        self.frames: list = []
        self.score = score

    def predict(self, frame):
        import numpy as np
        self.frames.append(np.asarray(frame).copy())
        return {"hey_jarvis": self.score}


# ===========================================================================
# W7 — closed-loop level-seeking (_ensure_recording) + cheap guards
# ===========================================================================

class _FakeWispr:
    """Simulates Wispr Flow's real recording state and whether our toggle tap
    actually reaches it. ``tap()`` flips the state only when ``tap_works``."""

    def __init__(self, recording: bool = False, tap_works: bool = True):
        self.recording = recording
        self.tap_works = tap_works
        self.taps = 0

    def tap(self) -> None:
        self.taps += 1
        if self.tap_works:
            self.recording = not self.recording


def _make_closed_loop_bridge(fake: "_FakeWispr", **cfg_attrs):
    """Bridge wired to a fake Wispr: the probe reads ``fake.recording`` and the
    toggle tap drives ``fake.tap``. Confirm/gap collapsed to 0 for determinism
    unless overridden."""
    from jarvis.listening.wispr_state import WisprStateProbe

    cfg = SimpleNamespace(
        wispr_closed_loop_enabled=True,
        wispr_confirm_timeout_sec=0.0,
        wispr_min_tap_gap_sec=0.0,
        **cfg_attrs,
    )
    bridge = WisprBridge(
        cfg,
        on_transcription=lambda text: None,
        state_probe=WisprStateProbe(reader=lambda: fake.recording),
        sleep=lambda s: None,
    )
    bridge._tap_hands_free_toggle_locked = fake.tap  # type: ignore[assignment]
    return bridge


@pytest.mark.unit
class TestEnsureRecording:
    """`_ensure_recording(target)` reconciles against Wispr's REAL state and
    taps only when needed, confirming the result — so a missed/extra tap
    self-corrects instead of inverting the mapping for the session."""

    def test_desync_heal_no_tap_when_already_recording(self):
        # Wispr is already recording but belief was False (inverted). Asking to
        # start must NOT tap (that would STOP Wispr); it reconciles belief.
        fake = _FakeWispr(recording=True)
        bridge = _make_closed_loop_bridge(fake)
        bridge._keys_held = False

        assert bridge._ensure_recording(True) is True
        assert fake.taps == 0
        assert fake.recording is True          # still recording
        assert bridge._keys_held is True       # belief reconciled

    def test_normal_start_taps_once_and_confirms(self):
        fake = _FakeWispr(recording=False, tap_works=True)
        bridge = _make_closed_loop_bridge(fake)

        assert bridge._ensure_recording(True) is True
        assert fake.taps == 1
        assert fake.recording is True
        assert bridge._keys_held is True

    def test_missed_press_retaps_then_reports_failure(self):
        # Tap never reaches Wispr (swallowed combo / wrong binding): one
        # corrective re-tap, then honest failure.
        fake = _FakeWispr(recording=False, tap_works=False)
        bridge = _make_closed_loop_bridge(fake)

        assert bridge._ensure_recording(True) is False
        assert fake.taps == 2                  # initial + one corrective re-tap
        assert fake.recording is False

    def test_normal_stop_taps_once(self):
        fake = _FakeWispr(recording=True, tap_works=True)
        bridge = _make_closed_loop_bridge(fake)
        bridge._keys_held = True

        assert bridge._ensure_recording(False) is True
        assert fake.taps == 1
        assert fake.recording is False
        assert bridge._keys_held is False

    def test_fail_open_belief_only_when_probe_unknown(self):
        # Closed-loop disabled -> probe returns None -> exactly today's
        # belief-only behaviour: one START tap, one STOP tap, no double tap.
        taps = []
        cfg = SimpleNamespace(
            wispr_closed_loop_enabled=False,
            wispr_min_tap_gap_sec=0.0,
        )
        bridge = WisprBridge(cfg, on_transcription=lambda t: None,
                             sleep=lambda s: None)
        bridge._tap_hands_free_toggle_locked = lambda: taps.append(1)  # type: ignore

        assert bridge._ensure_recording(True) is True
        assert len(taps) == 1 and bridge._keys_held is True
        assert bridge._ensure_recording(True) is True   # already held
        assert len(taps) == 1                            # no extra tap
        assert bridge._ensure_recording(False) is True
        assert len(taps) == 2 and bridge._keys_held is False


@pytest.mark.unit
class TestHotWindowFollowUpsOffByDefault:
    """The user wants Wispr to open ONLY on the wake word or the lightning
    button, never automatically after a reply. So the hot-window follow-up
    (which reopens Wispr on a bare VAD onset) must be OFF by default."""

    def test_enter_hot_window_is_noop_by_default(self):
        # No wispr_hot_window_sec on the cfg -> falls back to the code default,
        # which must be 0 (off): enter_hot_window leaves the bridge IDLE.
        bridge = _make_bridge()
        assert bridge._state == State.IDLE
        bridge.enter_hot_window()
        assert bridge._state == State.IDLE   # did NOT arm a follow-up window

    def test_default_hot_window_sec_is_zero(self):
        from jarvis.listening.wispr_bridge import DEFAULT_HOT_WINDOW_SEC
        assert DEFAULT_HOT_WINDOW_SEC == 0.0


@pytest.mark.unit
class TestUnconfirmedStart:
    """When a START tap can't be confirmed, the bridge reverts DICTATING and
    fires on_wispr_unavailable instead of leaving a false 'listening'."""

    def test_unconfirmed_start_reverts_and_fires_callback(self):
        fake = _FakeWispr(recording=False, tap_works=False)  # tap never reaches Wispr
        fired = []
        bridge = _make_closed_loop_bridge(fake)
        bridge.on_wispr_unavailable = lambda: fired.append(True)
        bridge._state = State.DICTATING       # _start_dictation already entered it

        bridge._do_press_keys()

        assert fired == [True]
        assert bridge._state == State.IDLE     # reverted

    def test_no_unavailable_when_probe_unknown(self):
        # Fail-open: probe None -> belief-only start succeeds, no callback,
        # state stays as the caller set it.
        fired = []
        bridge = _make_bridge()                # closed-loop off -> probe None
        bridge.on_wispr_unavailable = lambda: fired.append(True)
        bridge._tap_hands_free_toggle_locked = lambda: None  # type: ignore
        bridge._state = State.DICTATING

        bridge._do_press_keys()

        assert fired == []
        assert bridge._state == State.DICTATING


@pytest.mark.unit
class TestStartupReconciliation:
    """At startup the bridge aligns belief with Wispr's real state, forcing a
    stuck-recording Wispr back to a known idle so the first turn isn't inverted."""

    def test_forces_off_when_recording_at_boot(self):
        fake = _FakeWispr(recording=True, tap_works=True)
        bridge = _make_closed_loop_bridge(fake)

        bridge._reconcile_initial_state()

        assert fake.taps == 1            # synchronous force-off tap
        assert fake.recording is False
        assert bridge._keys_held is False

    def test_noop_when_idle_at_boot(self):
        fake = _FakeWispr(recording=False)
        bridge = _make_closed_loop_bridge(fake)

        bridge._reconcile_initial_state()

        assert fake.taps == 0
        assert bridge._keys_held is False

    def test_noop_when_probe_unknown(self):
        taps = []
        bridge = WisprBridge(
            SimpleNamespace(wispr_closed_loop_enabled=False),
            on_transcription=lambda t: None,
            sleep=lambda s: None,
        )
        bridge._tap_hands_free_toggle_locked = lambda: taps.append(1)  # type: ignore

        bridge._reconcile_initial_state()

        assert taps == []
        assert bridge._keys_held is False


@pytest.mark.unit
class TestHandsFreeComboAndGap:
    """Configurable hands-free chord + minimum inter-tap gap (cheap guards)."""

    def test_configurable_combo_is_tapped(self, monkeypatch):
        from pynput.keyboard import Key
        import jarvis.listening.wispr_bridge as wb
        monkeypatch.setattr(wb.time, "sleep", lambda s: None)

        bridge = _make_bridge(wispr_hands_free_combo=["ctrl", "alt", "space"])
        rec = _RecorderKeyboard()
        bridge._keyboard = rec

        bridge._tap_hands_free_toggle_locked()

        assert rec.presses == [Key.ctrl, Key.alt, Key.space]
        assert rec.releases == [Key.space, Key.alt, Key.ctrl]  # reverse order

    def test_unknown_combo_key_falls_back_to_default(self, monkeypatch):
        from pynput.keyboard import Key
        import jarvis.listening.wispr_bridge as wb
        monkeypatch.setattr(wb.time, "sleep", lambda s: None)

        bridge = _make_bridge(wispr_hands_free_combo=["boguskey"])
        rec = _RecorderKeyboard()
        bridge._keyboard = rec

        bridge._tap_hands_free_toggle_locked()

        assert rec.presses == [Key.ctrl, Key.cmd, Key.space]  # default fallback

    def test_min_tap_gap_enforced_between_consecutive_taps(self):
        class _Clock:
            def __init__(self):
                self.t = 1000.0
                self.sleeps = []

            def now(self):
                return self.t

            def sleep(self, s):
                self.sleeps.append(s)
                self.t += s

        clock = _Clock()
        bridge = WisprBridge(
            SimpleNamespace(wispr_min_tap_gap_sec=0.5),
            on_transcription=lambda t: None,
            monotonic=clock.now,
            sleep=clock.sleep,
        )
        bridge._tap_hands_free_toggle_locked = lambda: None  # type: ignore

        bridge._emit_toggle_tap_locked()   # first tap: last_tap_ts was 0 -> no gap
        bridge._emit_toggle_tap_locked()   # immediate second tap -> must wait the gap

        assert clock.sleeps == [0.5]


# ===========================================================================
# W1 — safer auto-type erase (data-loss guard)
# ===========================================================================

@pytest.mark.unit
class TestEraseAutotypedTextGuard:
    """``_erase_autotyped_text`` must cap the number of backspaces it sends
    so a wrong-window focus can't be sprayed with hundreds of deletes."""

    def test_short_text_erases_one_backspace_per_char(self):
        bridge = _make_bridge()
        kb = _RecorderKeyboard()
        bridge._keyboard = kb

        text = "hello world"  # 11 chars, well under the cap
        bridge._erase_autotyped_text(text)

        # Backspace pressed exactly len(text) times (press+release pairs).
        from pynput.keyboard import Key
        assert bridge._keyboard.presses.count(Key.backspace) == len(text)
        assert bridge._keyboard.releases.count(Key.backspace) == len(text)

    def test_over_cap_skips_erasing_entirely(self):
        cap = 300
        bridge = _make_bridge(wispr_erase_max_chars=cap)
        kb = _RecorderKeyboard()
        bridge._keyboard = kb

        text = "x" * (cap + 1)  # one char over the cap
        bridge._erase_autotyped_text(text)

        from pynput.keyboard import Key
        assert bridge._keyboard.presses.count(Key.backspace) == 0
        assert bridge._keyboard.releases.count(Key.backspace) == 0

    def test_at_cap_still_erases(self):
        cap = 50
        bridge = _make_bridge(wispr_erase_max_chars=cap)
        kb = _RecorderKeyboard()
        bridge._keyboard = kb

        text = "y" * cap  # exactly at the cap — should still erase
        bridge._erase_autotyped_text(text)

        from pynput.keyboard import Key
        assert bridge._keyboard.presses.count(Key.backspace) == cap

    def test_empty_text_is_a_noop(self):
        bridge = _make_bridge()
        kb = _RecorderKeyboard()
        bridge._keyboard = kb

        bridge._erase_autotyped_text("")

        assert bridge._keyboard.presses == []
        assert bridge._keyboard.releases == []

    def test_custom_cap_is_honoured(self):
        cap = 5
        bridge = _make_bridge(wispr_erase_max_chars=cap)
        kb = _RecorderKeyboard()
        bridge._keyboard = kb

        bridge._erase_autotyped_text("z" * (cap + 1))

        from pynput.keyboard import Key
        assert bridge._keyboard.presses.count(Key.backspace) == 0


# ===========================================================================
# W8 — capture path: clipboard-sequence detection + no-capture reason/recovery
# ===========================================================================

@pytest.mark.unit
class TestCapturePathReasons:
    """The post-dictation worker reports WHY a turn produced no transcript and
    detects an identical re-utterance via the clipboard sequence number."""

    def test_identical_reutterance_is_dispatched(self, monkeypatch):
        # Same text as the baseline, but the clipboard SEQUENCE advanced — the
        # historical exact-text diff dropped this; sequence detection keeps it.
        import jarvis.listening.wispr_bridge as wb
        monkeypatch.setattr(wb.pyperclip, "paste", lambda: "hello", raising=False)

        ends, transcripts = [], []
        bridge = _make_bridge(
            wispr_clipboard_wait_sec=0.05, wispr_clipboard_grace_sec=0.0,
            wispr_suppress_autotype=False,
        )
        bridge.watch_clipboard = True
        bridge._clipboard_seq = lambda: 6  # advanced past baseline_seq=5
        bridge.on_dictation_end = lambda captured, reason=None: ends.append((captured, reason))
        bridge.on_transcription = lambda t: transcripts.append(t)

        bridge._post_dictation_worker("hello", 5)

        assert transcripts == ["hello"]
        assert ends == [(True, None)]

    def test_unchanged_clipboard_reports_unchanged_reason(self, monkeypatch):
        import jarvis.listening.wispr_bridge as wb
        monkeypatch.setattr(wb.pyperclip, "paste", lambda: "hello", raising=False)

        ends = []
        bridge = _make_bridge(
            wispr_clipboard_wait_sec=0.02, wispr_clipboard_grace_sec=0.0)
        bridge.watch_clipboard = True
        bridge._clipboard_seq = lambda: 5  # never moves from baseline_seq=5
        bridge.on_dictation_end = lambda captured, reason=None: ends.append((captured, reason))

        bridge._post_dictation_worker("hello", 5)

        assert ends == [(False, "unchanged")]

    def test_clipboard_off_reports_off_reason(self):
        ends = []
        bridge = _make_bridge(wispr_clipboard_wait_sec=0.0)
        bridge.watch_clipboard = False
        bridge.on_dictation_end = lambda captured, reason=None: ends.append((captured, reason))

        bridge._post_dictation_worker("", None)

        assert ends == [(False, "off")]


@pytest.mark.unit
class TestNoCaptureForcesOff:
    """A no-capture turn where Wispr is still recording forces it OFF — the
    most diagnostic moment becomes a desync-recovery point."""

    def test_force_off_when_probe_still_recording(self, monkeypatch):
        import jarvis.listening.wispr_bridge as wb
        monkeypatch.setattr(wb.pyperclip, "paste", lambda: "base", raising=False)

        fake = _FakeWispr(recording=True, tap_works=True)
        bridge = _make_closed_loop_bridge(
            fake, wispr_clipboard_wait_sec=0.0, wispr_clipboard_grace_sec=0.0)
        bridge.watch_clipboard = True
        bridge._clipboard_seq = lambda: 5  # unchanged from baseline_seq=5
        bridge.on_dictation_end = lambda captured, reason=None: None

        bridge._post_dictation_worker("base", 5)

        assert fake.taps == 1          # forced OFF
        assert fake.recording is False


# ===========================================================================
# W3 — thread-safe speaking flag
# ===========================================================================

@pytest.mark.unit
class TestSpeakingFlagThreadSafety:
    """``_jarvis_speaking`` is written from the TTS thread and read from the
    post-dictation worker thread; a lock must guard both. Behaviour around
    the flag must be unchanged."""

    def test_speaking_lock_exists(self):
        bridge = _make_bridge()
        assert isinstance(bridge._speaking_lock, type(threading.Lock()))

    def test_set_speaking_toggles_flag(self):
        # Disable hot-window side effects so set_speaking only toggles the flag.
        bridge = _make_bridge(wispr_hot_window_sec=0)

        bridge.set_speaking(True)
        assert bridge._jarvis_speaking is True

        bridge.set_speaking(False)
        assert bridge._jarvis_speaking is False
        # Cancel the post-speak resume timer so it doesn't linger.
        if bridge._post_speak_resume_timer is not None:
            bridge._post_speak_resume_timer.cancel()

    def test_stop_pattern_fires_on_stop_when_speaking(self):
        fired = []
        bridge = _make_bridge(
            wispr_hot_window_sec=0,
            wispr_suppress_autotype=False,  # don't erase during dispatch
        )
        bridge.on_stop = lambda: fired.append(True)

        bridge.set_speaking(True)
        bridge._dispatch_transcription("stop")

        assert fired == [True]
        if bridge._post_speak_resume_timer is not None:
            bridge._post_speak_resume_timer.cancel()

    def test_stop_pattern_does_not_fire_on_stop_when_not_speaking(self):
        fired = []
        bridge = _make_bridge(
            wispr_hot_window_sec=0,
            wispr_suppress_autotype=False,
        )
        bridge.on_stop = lambda: fired.append(True)

        # Never set speaking — flag stays False.
        bridge._dispatch_transcription("stop")

        assert fired == []


# ===========================================================================
# W4 — on_dictation_end(captured: bool) contract
# ===========================================================================

@pytest.mark.unit
class TestDictationEndCapturedContract:
    """``on_dictation_end`` now receives a boolean: True when a clipboard
    transcript was captured within the wait window, False otherwise."""

    def test_no_clipboard_change_reports_false(self, monkeypatch):
        import jarvis.listening.wispr_bridge as wb

        baseline = "BASELINE-CLIP"
        # Clipboard never changes -> no transcript captured.
        monkeypatch.setattr(
            wb.pyperclip, "paste", lambda: baseline, raising=False)

        ends: list = []
        transcripts: list = []
        bridge = _make_bridge(
            wispr_clipboard_wait_sec=0.05, wispr_clipboard_grace_sec=0.0)
        bridge.watch_clipboard = True
        bridge.on_dictation_end = lambda captured, reason=None: ends.append((captured, reason))
        bridge.on_transcription = lambda text: transcripts.append(text)

        bridge._post_dictation_worker(baseline)

        assert ends == [(False, "timeout")]
        assert transcripts == []

    def test_clipboard_change_reports_true_and_dispatches(self, monkeypatch):
        import jarvis.listening.wispr_bridge as wb

        baseline = "BASELINE-CLIP"
        new_text = "the user said something"
        monkeypatch.setattr(
            wb.pyperclip, "paste", lambda: new_text, raising=False)

        ends: list = []
        transcripts: list = []
        bridge = _make_bridge(
            wispr_clipboard_wait_sec=2.0,
            wispr_suppress_autotype=False,  # skip erase during dispatch
        )
        bridge.watch_clipboard = True
        bridge.on_dictation_end = lambda captured, reason=None: ends.append((captured, reason))
        bridge.on_transcription = lambda text: transcripts.append(text)

        bridge._post_dictation_worker(baseline)

        assert ends == [(True, None)]
        assert transcripts == [new_text]

    def test_no_clipboard_branch_reports_false(self):
        # watch_clipboard False -> the worker just sleeps then reports
        # (False, "off").
        ends: list = []
        bridge = _make_bridge(wispr_clipboard_wait_sec=0.01)
        bridge.watch_clipboard = False
        bridge.on_dictation_end = lambda captured, reason=None: ends.append((captured, reason))

        bridge._post_dictation_worker("")

        assert ends == [(False, "off")]


# ===========================================================================
# W5 — instant barge-in interrupt on speech onset during TTS
# ===========================================================================

@pytest.mark.unit
class TestBargeInInterrupt:
    """When JARVIS is speaking and the user starts talking in the hot window,
    fire ``on_stop`` immediately on VAD speech onset rather than waiting for
    the cloud transcription round-trip."""

    def _arm_hot_window(self, bridge):
        """Force the bridge into HOT_WINDOW without timers / clipboard."""
        bridge.watch_clipboard = False  # _start_dictation won't read clipboard
        with bridge._state_lock:
            bridge._state = State.HOT_WINDOW

    def _feed_speech_start(self, bridge):
        """Drive _process_vad with a synthetic VAD 'start' event."""
        import numpy as np
        from jarvis.listening.wispr_bridge import VAD_FRAME_SIZE

        bridge.vad_iterator = _StubVadIterator(event={"start": 0.1})
        frame = np.zeros(VAD_FRAME_SIZE, dtype=np.float32)
        bridge._process_vad(frame)

    def test_barge_in_fires_on_stop_when_speaking(self):
        fired = []
        bridge = _make_bridge(wispr_hot_window_sec=0)  # avoid post-dictation hot window
        bridge.on_stop = lambda: fired.append(True)
        self._arm_hot_window(bridge)
        bridge._jarvis_speaking = True  # JARVIS is mid-speech

        self._feed_speech_start(bridge)

        assert fired == [True]

    def test_barge_in_does_not_fire_when_not_speaking(self):
        fired = []
        bridge = _make_bridge(wispr_hot_window_sec=0)
        bridge.on_stop = lambda: fired.append(True)
        self._arm_hot_window(bridge)
        # _jarvis_speaking stays False (default).

        self._feed_speech_start(bridge)

        assert fired == []

    def test_barge_in_disabled_by_config(self):
        fired = []
        bridge = _make_bridge(
            wispr_hot_window_sec=0,
            wispr_barge_in_interrupt=False,
        )
        bridge.on_stop = lambda: fired.append(True)
        bridge.set_speaking(True)
        # set_speaking(True) calls pause(); re-arm HOT_WINDOW explicitly.
        self._arm_hot_window(bridge)

        self._feed_speech_start(bridge)

        assert fired == []

    def test_barge_in_still_starts_dictation(self):
        """Even when interrupting, the user's words must still be captured:
        the bridge proceeds into DICTATING after firing on_stop."""
        fired = []
        bridge = _make_bridge(wispr_hot_window_sec=0)
        bridge.on_stop = lambda: fired.append(True)
        self._arm_hot_window(bridge)
        bridge._jarvis_speaking = True

        self._feed_speech_start(bridge)

        # on_stop fired AND we transitioned into dictation.
        assert fired == [True]
        with bridge._state_lock:
            assert bridge._state == State.DICTATING


# ===========================================================================
# W6 — wake mic resolved from the persisted endpoint id
# ===========================================================================

@pytest.mark.unit
class TestMicDeviceResolution:
    """The bridge's wake mic comes from the persisted audio-input selection
    (``audio_input_endpoint_id`` + ``audio_input_name``) resolved to a
    sounddevice index via ``audio_devices.resolve_endpoint_to_sd_index(...,
    kind="input")``. ``wispr_mic_device`` is only a final fallback when the new
    keys are empty. An absent device resolves to None (no crash, reconnect
    later) rather than falling through to the legacy key."""

    def test_resolves_mic_from_persisted_endpoint_id(self):
        from unittest.mock import patch

        bridge = _make_bridge(
            audio_input_endpoint_id="{0.0.1.00000000}.{mic-guid}",
            audio_input_name="Microphone (PD200X Podcast Microphone)",
            wispr_mic_device="legacy-name-should-be-ignored",
        )

        with patch(
            "jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
            return_value=18,
        ) as p_resolve:
            idx = bridge._resolve_mic_device()

        assert idx == 18
        p_resolve.assert_called_once()
        call = p_resolve.call_args
        id_arg = call.args[0] if call.args else call.kwargs.get("endpoint_id")
        name_arg = call.args[1] if len(call.args) > 1 else call.kwargs.get("name")
        assert id_arg == "{0.0.1.00000000}.{mic-guid}"
        assert name_arg == "Microphone (PD200X Podcast Microphone)"
        assert call.kwargs.get("kind") == "input"

    def test_absent_device_resolves_to_none_not_legacy_fallback(self):
        """When the new keys are set but the device is currently absent
        (resolve -> None), the bridge yields None (treated as no-device,
        ready to reconnect) and does NOT fall back to ``wispr_mic_device``."""
        from unittest.mock import patch

        bridge = _make_bridge(
            audio_input_endpoint_id="{ep-gone}",
            audio_input_name="Vanished Mic",
            wispr_mic_device="legacy-name-should-be-ignored",
        )

        with patch(
            "jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
            return_value=None,
        ):
            idx = bridge._resolve_mic_device()

        assert idx is None

    def test_falls_back_to_legacy_key_only_when_new_keys_empty(self):
        """With both new keys empty, the legacy ``wispr_mic_device`` value is
        used (matched to an index via the input flow), preserving old configs
        that never recorded an endpoint id."""
        from unittest.mock import patch

        bridge = _make_bridge(
            audio_input_endpoint_id="",
            audio_input_name="",
            wispr_mic_device="PD200X",
        )

        with patch(
            "jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
        ) as p_resolve, patch(
            "jarvis.output.audio_devices.match_name_to_sd_index",
            return_value=7,
        ) as p_match:
            idx = bridge._resolve_mic_device()

        # New-key resolver not consulted (nothing persisted there); legacy
        # name matched on the input flow instead.
        assert idx == 7
        p_resolve.assert_not_called()
        assert p_match.call_args.kwargs.get("kind") == "input"

    def test_no_selection_anywhere_resolves_to_none(self):
        """No new keys and no legacy key -> None (PortAudio default mic)."""
        bridge = _make_bridge(
            audio_input_endpoint_id="",
            audio_input_name="",
        )
        # wispr_mic_device absent on cfg -> getattr default None.
        assert bridge._resolve_mic_device() is None

    def test_start_does_not_crash_when_device_absent(self):
        """If the selected mic is absent at start(), the bridge must not crash:
        it logs and treats it as no-device (ready to reconnect). We stub the
        heavy model loads + the audio stream so only the device-resolution +
        stream-open guard is exercised."""
        from unittest.mock import MagicMock, patch
        import jarvis.listening.wispr_bridge as wb

        bridge = _make_bridge(
            audio_input_endpoint_id="{ep-gone}",
            audio_input_name="Vanished Mic",
        )

        # openWakeWord + Silero are imported/loaded inside start(); make them
        # cheap no-ops so the test never touches the network or real models.
        fake_oww = MagicMock()
        fake_oww.model.Model.return_value = MagicMock()
        fake_oww.utils.download_models.return_value = None

        with patch(
            "jarvis.output.audio_devices.resolve_endpoint_to_sd_index",
            return_value=None,
        ), patch.dict(
            "sys.modules",
            {"openwakeword": fake_oww, "openwakeword.model": fake_oww.model},
        ), patch.object(
            wb.torch.hub, "load",
            return_value=(MagicMock(), [None, None, None, lambda *a, **k: MagicMock()]),
        ), patch.object(wb.sd, "InputStream") as p_stream:
            # Should return without raising even though the device is absent.
            result = bridge.start()

        # No-device path: the bridge does not crash. Either it opened a stream
        # against the OS default (device=None) or it skipped opening entirely —
        # in both cases it must not raise and must not pin a bogus index.
        if p_stream.called:
            assert p_stream.call_args.kwargs.get("device") is None
        assert result in (True, False)  # no exception is the contract
        try:
            bridge.stop()
        except Exception:
            pass


# ===========================================================================
# W7 — live mic reconnect on Core Audio device change
# ===========================================================================

@pytest.mark.unit
class TestMicReconnect:
    """``reconnect()`` re-resolves the wake mic and reopens the input stream
    ONLY when the resolved sounddevice index changes. Driven by the Core Audio
    device watcher so an unplugged mic that returns (or a removed mic) is picked
    up without a daemon restart. Fail-open: never raises."""

    def test_reopens_stream_when_device_changes(self):
        import jarvis.listening.wispr_bridge as wb
        from unittest.mock import MagicMock, patch

        bridge = _make_bridge()
        bridge._started = True
        bridge.device = 5
        old_stream = MagicMock()
        bridge.audio_stream = old_stream
        bridge._resolve_mic_device = lambda: 7  # the chosen mic now maps to 7

        new_stream = MagicMock()
        with patch.object(wb.sd, "InputStream", return_value=new_stream) as p_stream:
            changed = bridge.reconnect()

        assert changed is True
        assert p_stream.call_args.kwargs.get("device") == 7
        new_stream.start.assert_called_once()
        # Old stream retired only AFTER the new one is live.
        old_stream.stop.assert_called_once()
        old_stream.close.assert_called_once()
        assert bridge.device == 7
        assert bridge.audio_stream is new_stream

    def test_noop_when_device_unchanged(self):
        import jarvis.listening.wispr_bridge as wb
        from unittest.mock import MagicMock, patch

        bridge = _make_bridge()
        bridge._started = True
        bridge.device = 5
        bridge.audio_stream = MagicMock()
        bridge._resolve_mic_device = lambda: 5  # same index

        with patch.object(wb.sd, "InputStream") as p_stream:
            changed = bridge.reconnect()

        assert changed is False
        p_stream.assert_not_called()  # no churn when nothing changed
        assert bridge.device == 5

    def test_noop_when_not_started(self):
        bridge = _make_bridge()
        bridge._started = False
        bridge._resolve_mic_device = lambda: 7
        assert bridge.reconnect() is False

    def test_fail_open_keeps_old_stream_when_reopen_raises(self):
        import jarvis.listening.wispr_bridge as wb
        from unittest.mock import MagicMock, patch

        bridge = _make_bridge()
        bridge._started = True
        bridge.device = 5
        old_stream = MagicMock()
        bridge.audio_stream = old_stream
        bridge._resolve_mic_device = lambda: 9

        with patch.object(wb.sd, "InputStream", side_effect=OSError("device busy")):
            changed = bridge.reconnect()

        assert changed is False
        # Reopen failed -> old stream left intact (NOT closed), bridge keeps running.
        old_stream.close.assert_not_called()
        assert bridge.device == 5
        assert bridge.audio_stream is old_stream


# ===========================================================================
# W8 — software wake gain (far-field sensitivity)
# ===========================================================================

@pytest.mark.unit
class TestWakeGain:
    """`wispr_wake_gain` amplifies ONLY the wake-detection copy of the audio
    (so a distant/quiet 'Hey Jarvis' reaches openWakeWord's useful range),
    clipped safely to int16, and never touches the VAD/transcript path."""

    class _RecordingWakeModel:
        def __init__(self):
            self.frames = []

        def predict(self, frame):
            import numpy as np
            self.frames.append(np.asarray(frame).copy())
            return {"hey_jarvis": 0.0}  # below threshold -> no trigger side effects

    def test_gain_scales_only_the_detector_audio(self):
        import numpy as np
        bridge = _make_bridge(wispr_wake_gain=4.0)
        bridge.wake_model = self._RecordingWakeModel()
        bridge._state = State.IDLE
        bridge._paused = False
        bridge._wake_cooldown = 0

        # 0.1 * 32767 * 4 ~= 13107; without gain it would be ~3277.
        bridge._process_wake(np.full(1280, 0.1, dtype=np.float32))

        assert bridge.wake_model.frames, "wake model should receive a frame"
        peak = int(np.abs(bridge.wake_model.frames[0]).max())
        assert 12000 < peak < 14000  # gain applied, not the un-gained ~3277
        # The VAD/transcript path is a separate buffer the gain never touches.
        assert len(bridge._vad_buf) == 0

    def test_gain_clips_safely_to_int16(self):
        import numpy as np
        bridge = _make_bridge(wispr_wake_gain=10.0)
        bridge.wake_model = self._RecordingWakeModel()
        bridge._state = State.IDLE
        bridge._paused = False
        bridge._wake_cooldown = 0

        # 0.5 * 32767 * 10 hugely overshoots int16 -> must clip, not wrap.
        bridge._process_wake(np.full(1280, 0.5, dtype=np.float32))
        peak = int(np.abs(bridge.wake_model.frames[0]).max())
        assert peak <= 32767


# ===========================================================================
# W9 — continuous feeding (stateful openWakeWord must be fed every frame)
# ===========================================================================

@pytest.mark.unit
class TestWakeContinuousFeed:
    """openWakeWord is STATEFUL: its classifier window only advances when
    predict() is called, and needs ~1.3s of CONTINUOUS frames before it
    scores a real wake. So the model must be fed EVERY frame; the RMS floor
    gates only the TRIGGER, never the predict() call. Gating predict() on
    silence starved the window -> 'Hey Jarvis' scored 0.125 then climbed to
    0.929 -> missed wakes (the regression this guards)."""

    def _idle_bridge(self, **cfg):
        bridge = _make_bridge(**cfg)
        bridge._state = State.IDLE
        bridge._user_muted = False
        bridge._speak_paused = False
        bridge._wake_cooldown = 0
        return bridge

    def test_predict_called_on_subfloor_frame(self):
        """THE regression guard: a near-silent frame (RMS << floor) must still
        be fed to the model so its window stays primed. Empty under the bug."""
        import numpy as np
        bridge = self._idle_bridge(wispr_wake_gain=1.0, wispr_wake_rms_floor=200.0)
        bridge.wake_model = _ScoringWakeModel(0.0)
        # int16 ~33 RMS, far below floor 200 (the old code skipped predict()).
        bridge._process_wake(np.full(1280, 0.001, dtype=np.float32))
        assert len(bridge.wake_model.frames) == 1

    def test_subfloor_frame_does_not_trigger(self):
        import numpy as np
        bridge = self._idle_bridge(wispr_wake_gain=1.0, wispr_wake_rms_floor=200.0,
                                   wispr_wake_threshold=0.3)
        bridge.wake_model = _ScoringWakeModel(0.99)  # would trigger if not gated
        triggered = []
        bridge._start_dictation = lambda score: triggered.append(score)
        bridge._process_wake(np.full(1280, 0.001, dtype=np.float32))
        assert len(bridge.wake_model.frames) == 1   # fed (primed)
        assert triggered == []                       # but quiet -> no trigger

    def test_above_floor_high_score_triggers(self):
        import numpy as np
        bridge = self._idle_bridge(wispr_wake_gain=1.0, wispr_wake_rms_floor=200.0,
                                   wispr_wake_threshold=0.3)
        bridge.wake_model = _ScoringWakeModel(0.99)
        triggered = []
        bridge._start_dictation = lambda score: triggered.append(score)
        bridge._process_wake(np.full(1280, 0.3, dtype=np.float32))  # rms ~9830
        assert triggered and abs(triggered[0] - 0.99) < 1e-6

    def test_above_floor_low_score_does_not_trigger(self):
        import numpy as np
        bridge = self._idle_bridge(wispr_wake_gain=1.0, wispr_wake_rms_floor=200.0,
                                   wispr_wake_threshold=0.3)
        bridge.wake_model = _ScoringWakeModel(0.05)  # below threshold
        triggered = []
        bridge._start_dictation = lambda score: triggered.append(score)
        bridge._process_wake(np.full(1280, 0.3, dtype=np.float32))
        assert bridge.wake_model.frames          # fed
        assert triggered == []                   # score below threshold

    def test_hot_window_feeds_model_but_does_not_trigger(self):
        import numpy as np
        bridge = self._idle_bridge(wispr_wake_gain=1.0, wispr_wake_rms_floor=200.0,
                                   wispr_wake_threshold=0.3)
        bridge._state = State.HOT_WINDOW
        bridge.wake_model = _ScoringWakeModel(0.99)
        triggered = []
        bridge._start_dictation = lambda score: triggered.append(score)
        bridge._process_wake(np.full(1280, 0.3, dtype=np.float32))
        assert bridge.wake_model.frames          # fed (keep window warm)
        assert triggered == []                   # HOT_WINDOW never wakes

    def test_muted_does_not_feed_model(self):
        import numpy as np
        bridge = self._idle_bridge(wispr_wake_gain=1.0, wispr_wake_rms_floor=200.0)
        bridge.wake_model = _ScoringWakeModel(0.99)
        bridge._user_muted = True
        bridge._process_wake(np.full(1280, 0.3, dtype=np.float32))
        assert bridge.wake_model.frames == []    # muted -> not fed
        assert bridge._wake_buf == []
        bridge._user_muted = False
        bridge._speak_paused = True
        bridge._process_wake(np.full(1280, 0.3, dtype=np.float32))
        assert bridge.wake_model.frames == []    # speaking -> not fed

    def test_default_floor_allows_far_field_wake(self):
        """Far-field regression guard: with NO rms_floor configured the bridge
        DEFAULT must not gate a quiet far-field frame. ~131 int16 RMS (about
        a 2-3 m 'Hey Jarvis' on the PD200X) with a high model score must still
        trigger. A default of 200 silently dropped these distant wakes."""
        import numpy as np
        # wispr_wake_rms_floor intentionally omitted -> exercises the default.
        bridge = self._idle_bridge(wispr_wake_gain=1.0, wispr_wake_threshold=0.3)
        bridge.wake_model = _ScoringWakeModel(0.99)
        triggered = []
        bridge._start_dictation = lambda score: triggered.append(score)
        # 0.004 * 32767 ~ 131 -> int16 frame ~131 RMS (far-field, below old 200).
        bridge._process_wake(np.full(1280, 0.004, dtype=np.float32))
        assert bridge.wake_model.frames                       # fed (primed)
        assert triggered and abs(triggered[0] - 0.99) < 1e-6  # AND triggers


# ===========================================================================
# W10 — startup / unmute priming of the stateful wake model
# ===========================================================================

@pytest.mark.unit
class TestWakePriming:
    """Prime openWakeWord with silence at startup (and on unmute) so the FIRST
    'Hey Jarvis' hits a full classifier window instead of cold-starting."""

    class _PrimeRecorder:
        def __init__(self):
            self.frames: list = []
            self.reset_calls = 0

        def reset(self):
            self.reset_calls += 1

        def predict(self, frame):
            import numpy as np
            self.frames.append(np.asarray(frame).copy())
            return {"hey_jarvis": 0.0}

    def test_prime_feeds_silent_frames_and_resets(self):
        import numpy as np
        from jarvis.listening.wispr_bridge import WAKE_PRIME_FRAMES, WAKE_FRAME_SIZE
        bridge = _make_bridge()
        bridge.wake_model = self._PrimeRecorder()
        bridge._prime_wake_model()
        assert bridge.wake_model.reset_calls == 1
        assert len(bridge.wake_model.frames) == WAKE_PRIME_FRAMES
        for f in bridge.wake_model.frames:
            assert f.dtype == np.int16
            assert len(f) == WAKE_FRAME_SIZE
            assert int(np.abs(f).max()) == 0     # silence

    def test_prime_without_reset_method_still_feeds(self):
        from jarvis.listening.wispr_bridge import WAKE_PRIME_FRAMES
        bridge = _make_bridge()
        bridge.wake_model = _ScoringWakeModel(0.0)   # no reset() method
        bridge._prime_wake_model()
        assert len(bridge.wake_model.frames) == WAKE_PRIME_FRAMES

    def test_prime_is_best_effort_on_predict_error(self):
        bridge = _make_bridge()

        class _Boom:
            def predict(self, frame):
                raise RuntimeError("boom")

        bridge.wake_model = _Boom()
        bridge._prime_wake_model()   # must not raise

    def test_prime_noop_without_model(self):
        bridge = _make_bridge()
        bridge.wake_model = None
        bridge._prime_wake_model()   # must not raise

    def test_resume_reprimes(self):
        from jarvis.listening.wispr_bridge import WAKE_PRIME_FRAMES
        bridge = _make_bridge()
        bridge.wake_model = self._PrimeRecorder()
        bridge._user_muted = True
        bridge.resume()
        assert bridge._user_muted is False
        assert len(bridge.wake_model.frames) == WAKE_PRIME_FRAMES
