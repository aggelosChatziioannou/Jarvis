"""Behaviour tests for :mod:`jarvis.listening.wispr_state`.

The probe reports whether Wispr Flow is currently recording by reading
Windows' per-application microphone-usage record (CapabilityAccessManager
consent store: ``LastUsedTimeStop == 0`` while an app is capturing). These
tests inject a fake reader / crafted registry rows — no real registry is
touched in CI. The real ``winreg`` backend is exercised only by the opt-in
``integration`` smoke test.
"""

import pytest

from jarvis.listening.wispr_state import (
    WisprStateProbe,
    recording_from_consent_rows,
)


# Crafted consent rows: (subkey_name, last_used_start, last_used_stop).
# stop == 0 means the app is CURRENTLY capturing the microphone.
_ACTIVE = "C:#Users#x#AppData#Local#WisprFlow#app-1.5.559#Wispr Flow.exe"
_OLD = "C:#Users#x#AppData#Local#WisprFlow#app-1.4.549#Wispr Flow.exe"
_OTHER = "C:#Program Files#Zoom#zoom.exe"


@pytest.mark.unit
class TestRecordingFromConsentRows:
    """The pure max-start selection logic over consent rows."""

    def test_active_version_recording(self):
        rows = [
            (_OLD, 100, 150),       # stale, idle
            (_ACTIVE, 200, 0),      # active, recording
            (_OTHER, 999, 0),       # not Wispr, ignored even though stop==0
        ]
        assert recording_from_consent_rows(rows) is True

    def test_active_idle_ignores_stale_in_use(self):
        # The active (max-start) Wispr entry is idle; an older stale entry has
        # a spurious stop==0. Must NOT read as recording.
        rows = [
            (_OLD, 100, 0),         # stale, spurious in-use
            (_ACTIVE, 200, 12345),  # active, idle
        ]
        assert recording_from_consent_rows(rows) is False

    def test_all_idle(self):
        rows = [(_OLD, 100, 150), (_ACTIVE, 200, 250)]
        assert recording_from_consent_rows(rows) is False

    def test_no_wispr_row(self):
        rows = [(_OTHER, 999, 0)]
        assert recording_from_consent_rows(rows) is None

    def test_empty(self):
        assert recording_from_consent_rows([]) is None


@pytest.mark.unit
class TestWisprStateProbe:
    """The probe wraps an injected reader and never raises."""

    def test_reader_true(self):
        probe = WisprStateProbe(reader=lambda: True)
        assert probe.is_recording() is True
        assert probe.available() is True

    def test_reader_false(self):
        probe = WisprStateProbe(reader=lambda: False)
        assert probe.is_recording() is False
        assert probe.available() is True

    def test_reader_none(self):
        probe = WisprStateProbe(reader=lambda: None)
        assert probe.is_recording() is None
        assert probe.available() is False

    def test_reader_raises_is_caught(self):
        def boom():
            raise OSError("registry gone")

        probe = WisprStateProbe(reader=boom)
        assert probe.is_recording() is None
        assert probe.available() is False


@pytest.mark.integration
def test_real_reader_smoke():
    """Opt-in: the real winreg-backed reader runs and returns a tri-state.

    Skipped under ``-m unit``. Requires a Windows host (and ideally Wispr Flow
    installed) to be meaningful, but must at least not raise.
    """
    probe = WisprStateProbe()  # default reader = real winreg mic-consent reader
    result = probe.is_recording()
    assert result in (True, False, None)
