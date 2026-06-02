"""After dispatching a Wispr transcript, the user's clipboard should be restored.

The Wispr bridge captures transcripts by reading the system clipboard. It never
restored the wake-time clipboard, so the full spoken utterance lingered on the
clipboard (and in Windows Win+V history) after every interaction. Restoring the
baseline closes that quiet retention channel. Gated by wispr_restore_clipboard
(default True) for users who want the transcript kept.
"""

import jarvis.listening.wispr_bridge as wb

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_wispr_bridge import _make_bridge  # reuse the bridge builder


class _FakeClip:
    def __init__(self):
        self.copied = []

    def copy(self, value):
        self.copied.append(value)

    def paste(self):
        return ""


def _prep(bridge, fake, monkeypatch, baseline="PRIOR USER CLIPBOARD"):
    monkeypatch.setattr(wb, "pyperclip", fake)
    bridge.watch_clipboard = True
    bridge.suppress_autotype = False  # skip the backspace/pynput path in tests
    bridge._clipboard_baseline = baseline
    bridge.on_transcription = lambda t: None


def test_clipboard_restored_to_baseline_by_default(monkeypatch):
    fake = _FakeClip()
    bridge = _make_bridge()
    _prep(bridge, fake, monkeypatch)
    bridge._dispatch_transcription("hello jarvis what is the weather")
    assert "PRIOR USER CLIPBOARD" in fake.copied  # spoken text not left on clipboard


def test_clipboard_not_restored_when_disabled(monkeypatch):
    fake = _FakeClip()
    bridge = _make_bridge(wispr_restore_clipboard=False)
    _prep(bridge, fake, monkeypatch)
    bridge._dispatch_transcription("hello jarvis")
    assert fake.copied == []
