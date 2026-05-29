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
    """
    cfg = SimpleNamespace(**cfg_attrs)
    bridge = WisprBridge(
        cfg,
        on_transcription=lambda text: None,
    )
    return bridge


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
        bridge = _make_bridge(wispr_clipboard_wait_sec=0.05)
        bridge.watch_clipboard = True
        bridge.on_dictation_end = lambda captured: ends.append(captured)
        bridge.on_transcription = lambda text: transcripts.append(text)

        bridge._post_dictation_worker(baseline)

        assert ends == [False]
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
        bridge.on_dictation_end = lambda captured: ends.append(captured)
        bridge.on_transcription = lambda text: transcripts.append(text)

        bridge._post_dictation_worker(baseline)

        assert ends == [True]
        assert transcripts == [new_text]

    def test_no_clipboard_branch_reports_false(self):
        # watch_clipboard False -> the worker just sleeps then reports False.
        ends: list = []
        bridge = _make_bridge(wispr_clipboard_wait_sec=0.01)
        bridge.watch_clipboard = False
        bridge.on_dictation_end = lambda captured: ends.append(captured)

        bridge._post_dictation_worker("")

        assert ends == [False]


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
