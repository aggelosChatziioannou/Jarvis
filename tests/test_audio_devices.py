"""Behaviour tests for jarvis.output.audio_devices.

These verify observable outcomes of the real-device cleaner, name matcher and
live-default reader — NOT how they are wired internally:

  * ``list_real_devices`` keeps only endpoints that pycaw reports as ACTIVE for
    the matching flow (output vs input), drops junk virtual devices (Sound
    Mapper, Stereo Mix, a NotPresent endpoint) and host-API duplicates.
  * ``match_name_to_sd_index`` matches a full (untruncated) pycaw friendly name
    to a WASAPI-truncated sounddevice name, preferring the WASAPI host API.
  * ``get_default_output_name`` fails open to ``None`` when pycaw cannot be
    imported.

Fakes mirror the shapes verified on the live machine:
  * ``sd.query_devices()`` → list of dicts with ``name``,
    ``max_input_channels``, ``max_output_channels``, ``hostapi``.
  * ``sd.query_hostapis(i)`` → dict with ``name``.
  * pycaw ``GetAllDevices()`` → objects with ``.FriendlyName`` and ``.state``.
"""

from __future__ import annotations

import sys
import types

import pytest


# --- Fakes --------------------------------------------------------------------

# Host API indices used by the fake device table.
_HA_WASAPI = 0
_HA_MME = 1
_HA_DS = 2  # Windows DirectSound


class _FakeSD:
    """Stand-in for the sounddevice module exposing only what we use."""

    def __init__(self, devices):
        self._devices = devices

    def query_devices(self, device=None):
        if device is None:
            return list(self._devices)
        return self._devices[device]

    def query_hostapis(self, index=None):
        apis = [
            {"name": "Windows WASAPI"},
            {"name": "MME"},
            {"name": "Windows DirectSound"},
        ]
        if index is None:
            return apis
        return apis[index]


class _FakePycawDevice:
    def __init__(self, friendly_name, state):
        self.FriendlyName = friendly_name
        self.state = state


def _install_fake_pycaw(monkeypatch, active_names, default_name):
    """Install a fake pycaw package whose Active set == ``active_names``."""

    class _FakeState:
        Active = "STATE_ACTIVE"
        NotPresent = "STATE_NOTPRESENT"
        Disabled = "STATE_DISABLED"

    # Every name in active_names is Active; one extra NotPresent device is added
    # so the filter has something junk to drop on the pycaw side too.
    all_devices = [_FakePycawDevice(n, _FakeState.Active) for n in active_names]
    all_devices.append(_FakePycawDevice("Ghost Device (NotPresent)", _FakeState.NotPresent))

    class _FakeAudioUtilities:
        @staticmethod
        def GetAllDevices():
            return list(all_devices)

        @staticmethod
        def GetSpeakers():
            return _FakePycawDevice(default_name, _FakeState.Active)

    utils_mod = types.ModuleType("pycaw.utils")
    utils_mod.AudioUtilities = _FakeAudioUtilities
    constants_mod = types.ModuleType("pycaw.constants")
    constants_mod.AudioDeviceState = _FakeState
    pkg = types.ModuleType("pycaw")
    pkg.utils = utils_mod
    pkg.constants = constants_mod

    monkeypatch.setitem(sys.modules, "pycaw", pkg)
    monkeypatch.setitem(sys.modules, "pycaw.utils", utils_mod)
    monkeypatch.setitem(sys.modules, "pycaw.constants", constants_mod)


# A representative device table: 3 real outputs + 2 real inputs, each present
# under WASAPI, plus junk (Sound Mapper, Stereo Mix) and an MME duplicate.
def _device_table():
    return [
        # Junk: MME "Microsoft Sound Mapper" virtual endpoints.
        {"name": "Microsoft Sound Mapper - Output", "max_input_channels": 0, "max_output_channels": 2, "hostapi": _HA_MME},
        {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "max_output_channels": 0, "hostapi": _HA_MME},
        # Real outputs (WASAPI). Note the WASAPI names are TRUNCATED versions of
        # the pycaw friendly names (which carry the full "(Realtek(R) Audio)").
        {"name": "Headset (Realtek(R) Audio)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": _HA_WASAPI},
        {"name": "PD200X (2- FIFINE Microph", "max_input_channels": 0, "max_output_channels": 2, "hostapi": _HA_WASAPI},
        {"name": "CORSAIR VOID Wireless", "max_input_channels": 0, "max_output_channels": 2, "hostapi": _HA_WASAPI},
        # Real inputs (WASAPI).
        {"name": "PD200X (2- FIFINE Microph", "max_input_channels": 1, "max_output_channels": 0, "hostapi": _HA_WASAPI},
        {"name": "CORSAIR VOID Wireless", "max_input_channels": 1, "max_output_channels": 0, "hostapi": _HA_WASAPI},
        # Junk: Stereo Mix loopback capture (WASAPI but NOT in pycaw Active set).
        {"name": "Stereo Mix (Realtek(R) Audio)", "max_input_channels": 2, "max_output_channels": 0, "hostapi": _HA_WASAPI},
        # Host-API duplicate of a real output on MME — should be de-duped away
        # in favour of the WASAPI variant of the same name.
        {"name": "Headset (Realtek(R) Audio)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": _HA_MME},
    ]


# pycaw friendly names (FULL, untruncated) for the real endpoints only.
_ACTIVE_OUTPUT_NAMES = [
    "Headset (Realtek(R) Audio)",
    "PD200X (2- FIFINE Microphone)",       # full name longer than WASAPI's truncation
    "CORSAIR VOID Wireless Gaming Headset",
]
_ACTIVE_INPUT_NAMES = [
    "Microphone (PD200X (2- FIFINE Microphone))",
    "Headset Microphone (CORSAIR VOID Wireless Gaming Headset)",
]


# --- Tests --------------------------------------------------------------------


def test_list_real_devices_drops_junk_and_keeps_real(monkeypatch):
    """Junk (Sound Mapper, Stereo Mix, NotPresent) is dropped; 3 outputs / 2
    inputs survive; host-API duplicates collapse to a single entry per name."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    _install_fake_pycaw(
        monkeypatch,
        active_names=_ACTIVE_OUTPUT_NAMES + _ACTIVE_INPUT_NAMES,
        default_name="Headset (Realtek(R) Audio)",
    )

    result = audio_devices.list_real_devices()

    out_names = {d["name"] for d in result["outputs"]}
    in_names = {d["name"] for d in result["inputs"]}

    # Exactly the 3 real outputs (sounddevice names) survive.
    assert out_names == {
        "Headset (Realtek(R) Audio)",
        "PD200X (2- FIFINE Microph",
        "CORSAIR VOID Wireless",
    }
    # Exactly the 2 real inputs survive.
    assert in_names == {
        "PD200X (2- FIFINE Microph",
        "CORSAIR VOID Wireless",
    }

    # Junk is gone from BOTH lists.
    for junk in ("Microsoft Sound Mapper - Output", "Microsoft Sound Mapper - Input",
                 "Stereo Mix (Realtek(R) Audio)", "Ghost Device (NotPresent)"):
        assert junk not in out_names
        assert junk not in in_names

    # De-dupe: "Headset" appears once even though it was present on WASAPI + MME.
    assert sum(1 for d in result["outputs"] if d["name"] == "Headset (Realtek(R) Audio)") == 1


def test_list_real_devices_dedupes_truncated_and_full_name(monkeypatch):
    """A WASAPI-truncated entry and the full-name (other host-API) entry for the
    SAME physical device collapse to ONE output, preferring the WASAPI variant.

    Reproduces the live-machine case where sounddevice lists both
    "Headset Earphone (CORSAIR VOID " (WASAPI, truncated) and
    "Headset Earphone (CORSAIR VOID WIRELESS v2 Gaming Headset)" (DirectSound,
    full) for one headset — the user must see it once.
    """
    from jarvis.output import audio_devices

    devices = [
        # WASAPI truncated variant (index 0) — preferred.
        {"name": "Headset Earphone (CORSAIR VOID ", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": _HA_WASAPI},
        # DirectSound full-name variant of the SAME device (index 1).
        {"name": "Headset Earphone (CORSAIR VOID WIRELESS v2 Gaming Headset)",
         "max_input_channels": 0, "max_output_channels": 2, "hostapi": _HA_MME},
    ]
    fake_sd = _FakeSD(devices)
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    _install_fake_pycaw(
        monkeypatch,
        active_names=["Headset Earphone (CORSAIR VOID WIRELESS v2 Gaming Headset)"],
        default_name="Headset Earphone (CORSAIR VOID WIRELESS v2 Gaming Headset)",
    )

    result = audio_devices.list_real_devices()

    # Collapsed to exactly one output.
    assert len(result["outputs"]) == 1
    # The kept entry is the WASAPI variant (index 0).
    assert result["outputs"][0]["index"] == 0


def test_list_real_devices_returns_indices(monkeypatch):
    """Each returned device carries its real sounddevice index."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    _install_fake_pycaw(
        monkeypatch,
        active_names=_ACTIVE_OUTPUT_NAMES + _ACTIVE_INPUT_NAMES,
        default_name="Headset (Realtek(R) Audio)",
    )

    result = audio_devices.list_real_devices()

    # The de-duped Headset output must keep the WASAPI index (2), not the MME
    # duplicate's index (8) — the WASAPI variant is preferred.
    headset = next(d for d in result["outputs"] if d["name"] == "Headset (Realtek(R) Audio)")
    assert headset["index"] == 2


def test_match_name_to_sd_index_matches_truncated_name(monkeypatch):
    """A full pycaw friendly name matches a WASAPI-truncated sounddevice name."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)

    # The full name "PD200X (2- FIFINE Microphone)" must resolve to the
    # truncated sounddevice OUTPUT entry "PD200X (2- FIFINE Microph" at index 3.
    idx = audio_devices.match_name_to_sd_index(
        "PD200X (2- FIFINE Microphone)", kind="output"
    )
    assert idx == 3


def test_match_name_prefers_resampling_hostapi_over_wasapi(monkeypatch):
    """For OPENING a stream we must NOT prefer WASAPI: it is rate-rigid (rejects
    the 16 kHz wake mic, PaErrorCode -9997) and has proven silent for output from
    inside the daemon. Here Headset exists on WASAPI (idx 2) and MME (idx 8); the
    resampling/robust MME variant must win for playback resolution."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)

    idx = audio_devices.match_name_to_sd_index(
        "Headset (Realtek(R) Audio)", kind="output"
    )
    # MME duplicate is index 8; the WASAPI variant (idx 2) must NOT win now.
    assert idx == 8


def test_match_name_prefers_directsound_over_wasapi(monkeypatch):
    """DirectSound (resampling + COM-robust) is the top-ranked open-path host
    API, beating both WASAPI and MME."""
    from jarvis.output import audio_devices

    devices = [
        {"name": "Headset (Realtek(R) Audio)", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": _HA_WASAPI},   # idx 0
        {"name": "Headset (Realtek(R) Audio)", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": _HA_MME},      # idx 1
        {"name": "Headset (Realtek(R) Audio)", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": _HA_DS},       # idx 2 — preferred
    ]
    fake_sd = _FakeSD(devices)
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)

    idx = audio_devices.match_name_to_sd_index(
        "Headset (Realtek(R) Audio)", kind="output"
    )
    assert idx == 2  # the DirectSound variant wins


def test_match_name_respects_kind(monkeypatch):
    """A name is matched only against devices of the requested flow."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)

    # "CORSAIR VOID Wireless" exists as BOTH an output (idx 4) and an input
    # (idx 6). Asking for the input flow must return the input index.
    out_idx = audio_devices.match_name_to_sd_index("CORSAIR VOID Wireless", kind="output")
    in_idx = audio_devices.match_name_to_sd_index("CORSAIR VOID Wireless", kind="input")
    assert out_idx == 4
    assert in_idx == 6


def test_match_name_returns_none_for_unknown(monkeypatch):
    """An unmatched name fails open to None (caller uses PortAudio default)."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)

    assert audio_devices.match_name_to_sd_index("No Such Device", kind="output") is None
    assert audio_devices.match_name_to_sd_index(None, kind="output") is None


def test_get_default_output_name_returns_live_default(monkeypatch):
    """get_default_output_name returns pycaw's live GetSpeakers().FriendlyName."""
    from jarvis.output import audio_devices

    _install_fake_pycaw(
        monkeypatch,
        active_names=_ACTIVE_OUTPUT_NAMES,
        default_name="PD200X (2- FIFINE Microphone)",
    )

    assert audio_devices.get_default_output_name() == "PD200X (2- FIFINE Microphone)"


def test_get_default_output_name_fails_open_when_pycaw_missing(monkeypatch):
    """When pycaw import fails, get_default_output_name returns None."""
    from jarvis.output import audio_devices

    # Force the import inside the function to raise ImportError.
    monkeypatch.setitem(sys.modules, "pycaw", None)
    monkeypatch.setitem(sys.modules, "pycaw.utils", None)

    assert audio_devices.get_default_output_name() is None


def test_list_real_devices_fails_open_to_raw_when_pycaw_missing(monkeypatch):
    """When pycaw is unavailable, list_real_devices falls back to raw sd lists
    (no filtering) rather than returning empty."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    monkeypatch.setitem(sys.modules, "pycaw", None)
    monkeypatch.setitem(sys.modules, "pycaw.utils", None)
    monkeypatch.setitem(sys.modules, "pycaw.constants", None)

    result = audio_devices.list_real_devices()

    # Fail-open: raw output count (every device with output channels, incl.
    # Sound Mapper + the MME duplicate) is preserved, so the user still sees
    # something rather than an empty dropdown.
    raw_outputs = [d for d in _device_table() if d["max_output_channels"] > 0]
    assert len(result["outputs"]) == len(raw_outputs)


# --- list_devices() + resolve_endpoint_to_sd_index() (endpoint-id redesign) ---
#
# These exercise the new Core Audio service: a render/capture split that
# carries the STABLE endpoint id + is_default + availability, and resolution of
# a persisted endpoint id (or name fallback) to a current sounddevice index.
#
# The fake here mirrors the REAL pycaw API more closely than the legacy fake
# above: ``AudioUtilities.GetAllDevices(data_flow=..., device_state=...)`` takes
# the EDataFlow filter (eRender=0 / eCapture=1) and a device-state mask, each
# returned device exposes ``.id``/``.FriendlyName``/``.state``, and the default
# endpoints come from ``GetSpeakers().id`` / ``GetMicrophone().GetId()``.


class _FakeEndpoint:
    """A pycaw AudioDevice stand-in carrying a stable endpoint id."""

    def __init__(self, endpoint_id, friendly_name, state, data_flow):
        self.id = endpoint_id
        self.FriendlyName = friendly_name
        self.state = state
        self._data_flow = data_flow  # 0 = render, 1 = capture

    def GetId(self):  # the raw IMMDevice GetMicrophone() returns exposes this
        return self.id


def _install_fake_pycaw_endpoints(monkeypatch, *, render, capture,
                                  default_out_id, default_in_id):
    """Install a fake pycaw whose enumerator splits render vs capture by flow.

    ``render``/``capture`` are lists of ``(id, name, state_str)`` tuples. State
    strings are matched against the fake ``AudioDeviceState`` / ``DEVICE_STATE``
    enums so the production code's ``state == Active`` test works unchanged.
    """

    class _FakeState:
        Active = "STATE_ACTIVE"
        NotPresent = "STATE_NOTPRESENT"
        Disabled = "STATE_DISABLED"
        Unplugged = "STATE_UNPLUGGED"

    class _FakeDeviceState:
        # .value mirrors the real DEVICE_STATE IntFlag (ACTIVE == 1).
        class _V:
            def __init__(self, v):
                self.value = v
        ACTIVE = _V(0x1)
        MASK_ALL = _V(0xF)

    class _FakeEDataFlow:
        class _V:
            def __init__(self, v):
                self.value = v
        eRender = _V(0)
        eCapture = _V(1)
        eAll = _V(2)

    render_devs = [_FakeEndpoint(i, n, s, 0) for (i, n, s) in render]
    capture_devs = [_FakeEndpoint(i, n, s, 1) for (i, n, s) in capture]
    all_devs = render_devs + capture_devs

    default_out = next((d for d in render_devs if d.id == default_out_id), None)
    default_in = next((d for d in capture_devs if d.id == default_in_id), None)

    class _FakeAudioUtilities:
        @staticmethod
        def GetAllDevices(data_flow=_FakeEDataFlow.eAll.value,
                          device_state=_FakeDeviceState.MASK_ALL.value):
            if data_flow == _FakeEDataFlow.eRender.value:
                pool = render_devs
            elif data_flow == _FakeEDataFlow.eCapture.value:
                pool = capture_devs
            else:
                pool = all_devs
            # Honour an ACTIVE-only mask the way the real enumerator does.
            if device_state == _FakeDeviceState.ACTIVE.value:
                return [d for d in pool if d.state == _FakeState.Active]
            return list(pool)

        @staticmethod
        def GetSpeakers():
            return default_out

        @staticmethod
        def GetMicrophone():
            # Real GetMicrophone returns a raw IMMDevice (GetId()), NOT a
            # wrapped AudioDevice — exercise the .GetId() fallback path.
            return default_in

    utils_mod = types.ModuleType("pycaw.utils")
    utils_mod.AudioUtilities = _FakeAudioUtilities
    constants_mod = types.ModuleType("pycaw.constants")
    constants_mod.AudioDeviceState = _FakeState
    constants_mod.DEVICE_STATE = _FakeDeviceState
    constants_mod.EDataFlow = _FakeEDataFlow
    pkg = types.ModuleType("pycaw")
    pkg.utils = utils_mod
    pkg.constants = constants_mod

    monkeypatch.setitem(sys.modules, "pycaw", pkg)
    monkeypatch.setitem(sys.modules, "pycaw.utils", utils_mod)
    monkeypatch.setitem(sys.modules, "pycaw.constants", constants_mod)


def test_list_devices_splits_render_capture_with_ids(monkeypatch):
    """list_devices() returns {inputs, outputs}; render→outputs, capture→inputs,
    each item carries {id, name, is_default, available}; only Active survive."""
    from jarvis.output import audio_devices

    _install_fake_pycaw_endpoints(
        monkeypatch,
        render=[
            ("{0.0.0.00000000}.{spk}", "Headset (Realtek(R) Audio)", "STATE_ACTIVE"),
            ("{0.0.0.00000000}.{void}", "CORSAIR VOID Wireless", "STATE_ACTIVE"),
            ("{0.0.0.00000000}.{ghost}", "Ghost Speaker", "STATE_NOTPRESENT"),
        ],
        capture=[
            ("{0.0.1.00000000}.{mic}", "Microphone (PD200X)", "STATE_ACTIVE"),
            ("{0.0.1.00000000}.{stereomix}", "Stereo Mix", "STATE_DISABLED"),
        ],
        default_out_id="{0.0.0.00000000}.{spk}",
        default_in_id="{0.0.1.00000000}.{mic}",
    )

    out = audio_devices.list_devices()

    assert set(out.keys()) == {"inputs", "outputs"}
    # Every item carries the full contract.
    for item in out["outputs"] + out["inputs"]:
        assert {"id", "name", "is_default", "available"} <= set(item)

    out_ids = {d["id"] for d in out["outputs"]}
    in_ids = {d["id"] for d in out["inputs"]}

    # Render endpoints land in outputs (Active only), capture in inputs.
    assert "{0.0.0.00000000}.{spk}" in out_ids
    assert "{0.0.0.00000000}.{void}" in out_ids
    assert "{0.0.1.00000000}.{mic}" in in_ids
    # Inactive endpoints are dropped from BOTH lists.
    assert "{0.0.0.00000000}.{ghost}" not in out_ids
    assert "{0.0.1.00000000}.{stereomix}" not in in_ids
    # Render ids never leak into inputs and vice versa.
    assert out_ids.isdisjoint(in_ids)


def test_list_devices_marks_default(monkeypatch):
    """is_default is True for the endpoint whose id equals GetSpeakers().id /
    GetMicrophone().GetId(), and False for the rest."""
    from jarvis.output import audio_devices

    _install_fake_pycaw_endpoints(
        monkeypatch,
        render=[
            ("{spk}", "Headset (Realtek(R) Audio)", "STATE_ACTIVE"),
            ("{void}", "CORSAIR VOID Wireless", "STATE_ACTIVE"),
        ],
        capture=[("{mic}", "Microphone (PD200X)", "STATE_ACTIVE")],
        default_out_id="{void}",
        default_in_id="{mic}",
    )

    out = audio_devices.list_devices()

    defaults_out = {d["id"] for d in out["outputs"] if d["is_default"]}
    assert defaults_out == {"{void}"}
    # The non-default output is explicitly not default.
    headset = next(d for d in out["outputs"] if d["id"] == "{spk}")
    assert headset["is_default"] is False
    # The single mic is the default input.
    assert out["inputs"][0]["is_default"] is True
    # Active endpoints are marked available.
    assert all(d["available"] for d in out["outputs"] + out["inputs"])


def test_list_devices_fails_open_to_sounddevice_when_pycaw_missing(monkeypatch):
    """When pycaw import raises, list_devices() falls open to a sounddevice
    derived list with EMPTY ids (so the UI still shows real devices)."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    monkeypatch.setitem(sys.modules, "pycaw", None)
    monkeypatch.setitem(sys.modules, "pycaw.utils", None)
    monkeypatch.setitem(sys.modules, "pycaw.constants", None)

    out = audio_devices.list_devices()

    assert set(out.keys()) == {"inputs", "outputs"}
    # At least the real outputs surface (sounddevice fallback), each shaped with
    # the full contract and a BLANK id (pycaw gave us no endpoint ids).
    assert out["outputs"], "expected a sounddevice-derived output fallback"
    for item in out["outputs"] + out["inputs"]:
        assert {"id", "name", "is_default", "available"} <= set(item)
        assert item["id"] == ""
    # Fallback output count matches the raw sd devices that have output channels.
    raw_outputs = [d for d in _device_table() if d["max_output_channels"] > 0]
    assert len(out["outputs"]) == len(raw_outputs)


def test_resolve_endpoint_to_sd_index_by_id(monkeypatch):
    """A persisted endpoint id resolves via its CURRENT friendly name (from
    list_devices) to the matching sounddevice index, truncation-tolerant."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    # pycaw maps the endpoint id -> the FULL friendly name "...Microphone)".
    _install_fake_pycaw_endpoints(
        monkeypatch,
        render=[("{pd200x}", "PD200X (2- FIFINE Microphone)", "STATE_ACTIVE")],
        capture=[("{pd200x-in}", "PD200X (2- FIFINE Microphone)", "STATE_ACTIVE")],
        default_out_id="{pd200x}",
        default_in_id="{pd200x-in}",
    )

    # Output flow: the full pycaw name resolves to the truncated sd OUTPUT entry
    # "PD200X (2- FIFINE Microph" at index 3.
    idx = audio_devices.resolve_endpoint_to_sd_index(
        "{pd200x}", "ignored saved name", kind="output"
    )
    assert idx == 3


def test_resolve_endpoint_falls_back_to_name_when_id_unknown(monkeypatch):
    """When the endpoint id is not in the current device list, resolution falls
    back to the saved friendly name."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    # The persisted id is absent from the live list (device unplugged then a
    # different one present), so id lookup misses and we use the saved name.
    _install_fake_pycaw_endpoints(
        monkeypatch,
        render=[("{some-other}", "Some Other Speaker", "STATE_ACTIVE")],
        capture=[],
        default_out_id="{some-other}",
        default_in_id="",
    )

    idx = audio_devices.resolve_endpoint_to_sd_index(
        "{not-present-id}", "Headset (Realtek(R) Audio)", kind="output"
    )
    # Name fallback finds the Headset output; the open path now prefers the
    # resampling MME variant (idx 8) over the rate-rigid WASAPI one (idx 2).
    assert idx == 8


def test_resolve_endpoint_returns_none_when_absent(monkeypatch):
    """A device that matches neither id nor name resolves to None (caller treats
    it as disconnected)."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    _install_fake_pycaw_endpoints(
        monkeypatch,
        render=[("{some-other}", "Some Other Speaker", "STATE_ACTIVE")],
        capture=[],
        default_out_id="{some-other}",
        default_in_id="",
    )

    assert audio_devices.resolve_endpoint_to_sd_index(
        "{gone}", "No Such Device", kind="output"
    ) is None
    # Empty id + empty name -> None too.
    assert audio_devices.resolve_endpoint_to_sd_index("", "", kind="output") is None


def test_resolve_endpoint_name_fallback_without_pycaw(monkeypatch):
    """Even with pycaw unavailable, a saved name still resolves via sounddevice
    (the id->name lookup just yields nothing, name fallback carries it)."""
    from jarvis.output import audio_devices

    fake_sd = _FakeSD(_device_table())
    monkeypatch.setattr(audio_devices, "sd", fake_sd, raising=False)
    monkeypatch.setitem(sys.modules, "pycaw", None)
    monkeypatch.setitem(sys.modules, "pycaw.utils", None)
    monkeypatch.setitem(sys.modules, "pycaw.constants", None)

    idx = audio_devices.resolve_endpoint_to_sd_index(
        "{any-id}", "CORSAIR VOID Wireless", kind="input"
    )
    # Input flow: CORSAIR VOID input is index 6.
    assert idx == 6
