"""The wispr_min_dictation_sec default must match the documented value.

JARVIS_CHANGES R4 records this default being lowered 2.0 -> 1.0 'for faster
short commands', but the code shipped 2.0 at every site (the change was never
applied). Reconcile to the documented 1.0 so a wake-triggered short command
('next song') doesn't hold push-to-talk for a needless extra second.
"""


def test_default_config_min_dictation_is_one_second():
    from jarvis.config import get_default_config
    assert get_default_config()["wispr_min_dictation_sec"] == 1.0


def test_bridge_constant_min_dictation_is_one_second():
    from jarvis.listening.wispr_bridge import DEFAULT_MIN_DICTATION_SEC
    assert DEFAULT_MIN_DICTATION_SEC == 1.0
