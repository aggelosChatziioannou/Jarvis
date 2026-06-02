"""The runtime must disclose when STT sends audio to a third-party cloud.

README claims "100% local", but with stt_backend=wispr the user's raw mic audio
is sent to Wispr Flow's cloud. stt_cloud_disclosure surfaces that honestly at
the point of use; the local whisper backend gets no notice.
"""

from types import SimpleNamespace

from jarvis.config import stt_cloud_disclosure


def test_wispr_backend_discloses_cloud():
    msg = stt_cloud_disclosure(SimpleNamespace(stt_backend="wispr"))
    assert msg is not None
    low = msg.lower()
    assert "cloud" in low
    assert "sent" in low
    assert "wispr" in low


def test_whisper_backend_has_no_disclosure():
    assert stt_cloud_disclosure(SimpleNamespace(stt_backend="whisper")) is None


def test_default_backend_is_local_no_disclosure():
    assert stt_cloud_disclosure(SimpleNamespace()) is None
