"""Real-device enumeration + live Windows default-output detection.

Three responsibilities, all fail-open (privacy- and crash-safe):

  * :func:`get_default_output_name` — read the LIVE Windows default playback
    endpoint's friendly name via pycaw (Core Audio). Used so Jarvis can follow
    whatever the user just switched Windows to, re-checked on every playback,
    without a restart.
  * :func:`list_real_devices` — enumerate ``sounddevice`` devices but keep only
    those that pycaw reports as ACTIVE for the matching flow (output vs input),
    de-duping host-API variants of the same physical device. This strips the
    junk Windows exposes through PortAudio (Microsoft Sound Mapper, Stereo Mix,
    Primary Sound Driver, disconnected endpoints).
  * :func:`match_name_to_sd_index` — resolve a (possibly pycaw-full) device name
    to the actual ``sounddevice`` index for the requested flow, tolerant of the
    name truncation WASAPI applies, preferring the WASAPI host API.

Why pycaw + sounddevice together?
  * pycaw reads Windows Core Audio directly. It is the only reliable source for
    (a) the *live* default endpoint and (b) which endpoints are genuinely
    present/active. It does NOT re-initialise PortAudio, so it is safe to call
    while the wispr bridge holds an open mic ``InputStream``.
  * sounddevice (PortAudio) owns the actual stream *index* used for playback and
    distinguishes input vs output via channel counts. But it also surfaces every
    virtual/host-API endpoint, which is exactly the junk we want to hide.

pycaw friendly names are often LONGER than the sounddevice name for the same
device (WASAPI truncates to ~31 chars), so all name matching is tolerant:
normalise (casefold + strip) then test containment in BOTH directions.

Privacy: pycaw reads local Core Audio only; no network, no telemetry.
"""

from __future__ import annotations

from typing import Optional

from ..debug import debug_log

# Imported at module scope so tests can monkeypatch ``audio_devices.sd`` with a
# fake. Guarded because sounddevice/PortAudio may be unavailable in some envs;
# every public function fails open if it is None.
try:  # pragma: no cover - trivial import guard
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover
    sd = None  # type: ignore


def _normalise(name: Optional[str]) -> str:
    """Casefold + collapse-strip a device name for tolerant comparison."""
    if not name:
        return ""
    return " ".join(str(name).split()).casefold()


def _hostapi_score(sd_module, hostapi_index) -> int:
    """Rank host APIs: WASAPI=2, DirectSound=1, MME/other=0.

    Higher is preferred when de-duping / matching, because WASAPI gives the
    best latency and bit-perfect routing on Windows.
    """
    try:
        name = str(sd_module.query_hostapis(hostapi_index)["name"]).lower()
    except Exception:
        return 0
    if "wasapi" in name:
        return 2
    if "directsound" in name:
        return 1
    return 0


def _is_output(dev: dict) -> bool:
    return int(dev.get("max_output_channels", 0) or 0) > 0


def _is_input(dev: dict) -> bool:
    return int(dev.get("max_input_channels", 0) or 0) > 0


def get_default_output_name() -> Optional[str]:
    """Return the LIVE Windows default playback endpoint's friendly name.

    Uses pycaw ``AudioUtilities.GetSpeakers().FriendlyName`` — Core Audio only,
    safe alongside an open PortAudio mic stream. Fail-open: returns ``None`` if
    pycaw/COM is unavailable or raises, so callers fall back to PortAudio's own
    default device.
    """
    try:
        from pycaw.utils import AudioUtilities
    except Exception as e:
        debug_log(f"get_default_output_name: pycaw unavailable ({e!r})", "audio")
        return None
    try:
        speakers = AudioUtilities.GetSpeakers()
        name = getattr(speakers, "FriendlyName", None)
        if name:
            debug_log(f"get_default_output_name: live default = {name!r}", "audio")
            return str(name)
        return None
    except Exception as e:
        debug_log(f"get_default_output_name: GetSpeakers raised ({e!r})", "audio")
        return None


def _active_friendly_names() -> Optional[list[str]]:
    """Return the friendly names of all ACTIVE Core Audio endpoints, or None.

    ``None`` (not ``[]``) signals "pycaw unavailable" so callers can fail open
    to the raw sounddevice lists rather than mistaking it for "no real
    devices".
    """
    try:
        from pycaw.utils import AudioUtilities
        from pycaw.constants import AudioDeviceState
    except Exception as e:
        debug_log(f"_active_friendly_names: pycaw unavailable ({e!r})", "audio")
        return None
    try:
        active = []
        for dev in AudioUtilities.GetAllDevices():
            try:
                if getattr(dev, "state", None) == AudioDeviceState.Active:
                    fname = getattr(dev, "FriendlyName", None)
                    if fname:
                        active.append(str(fname))
            except Exception:
                continue
        return active
    except Exception as e:
        debug_log(f"_active_friendly_names: GetAllDevices raised ({e!r})", "audio")
        return None


def _default_endpoint_id(getter) -> Optional[str]:
    """Return the endpoint id of a pycaw default-endpoint getter, or None.

    ``getter`` is ``AudioUtilities.GetSpeakers`` or ``GetMicrophone``. The
    object they return may be a wrapped ``AudioDevice`` (``.id``) or, for
    ``GetMicrophone``, a raw IMMDevice (``.GetId()``). Try both. Fail-open to
    ``None`` so a missing default never breaks the listing.
    """
    try:
        dev = getter()
    except Exception:
        return None
    if dev is None:
        return None
    dev_id = getattr(dev, "id", None)
    if dev_id:
        return str(dev_id)
    try:
        raw = dev.GetId()
        return str(raw) if raw else None
    except Exception:
        return None


def _enumerate_endpoints(data_flow_value: int):
    """Yield ``(id, name)`` for ACTIVE Core Audio endpoints of one flow.

    ``data_flow_value`` is ``EDataFlow.eRender.value`` (0, outputs) or
    ``EDataFlow.eCapture.value`` (1, inputs). Uses
    ``AudioUtilities.GetAllDevices(data_flow=..., device_state=ACTIVE)`` so the
    render/capture split + the Active filter are done by Core Audio itself
    (the same enumerator that backs the live device list).

    Raises on pycaw failure — the public caller decides the fail-open shape.
    """
    from pycaw.utils import AudioUtilities
    from pycaw.constants import AudioDeviceState, DEVICE_STATE

    active_mask = DEVICE_STATE.ACTIVE.value
    out: list[tuple[str, str]] = []
    for dev in AudioUtilities.GetAllDevices(
        data_flow=data_flow_value, device_state=active_mask
    ):
        try:
            # Belt-and-braces: the enumerator already filtered to ACTIVE, but
            # re-check so a fake/edge case that ignores the mask still drops
            # inactive endpoints.
            if getattr(dev, "state", None) != AudioDeviceState.Active:
                continue
            dev_id = getattr(dev, "id", None)
            fname = getattr(dev, "FriendlyName", None)
            if dev_id and fname:
                out.append((str(dev_id), str(fname)))
        except Exception:
            continue
    return out


def list_devices() -> dict:
    """Enumerate live input/output devices with STABLE endpoint ids.

    Returns::

        {
          "inputs":  [{"id", "name", "is_default", "available"}, ...],  # capture
          "outputs": [{"id", "name", "is_default", "available"}, ...],  # render
        }

    Source of truth = pycaw Windows Core Audio (render = outputs, capture =
    inputs), Active endpoints only, each carrying the stable endpoint **id**
    (survives restarts/reconnects, unlike friendly names which collide for
    identical devices). ``is_default`` matches ``GetSpeakers().id`` /
    ``GetMicrophone()`` id; ``available`` is True for Active endpoints. Live:
    reflects hot-plug without re-initialising PortAudio.

    Fail-open: if pycaw is unavailable or raises, returns a sounddevice-derived
    list with BLANK ids (the UI still shows the user's devices; resolution then
    leans on the saved name). Privacy: pycaw reads local Core Audio only.
    """
    try:
        from pycaw.constants import EDataFlow  # noqa: F401 (import guard)
    except Exception as e:
        debug_log(f"list_devices: pycaw unavailable ({e!r}); sd fallback", "audio")
        return _list_devices_sounddevice_fallback()

    try:
        from pycaw.constants import EDataFlow

        render = _enumerate_endpoints(EDataFlow.eRender.value)
        capture = _enumerate_endpoints(EDataFlow.eCapture.value)
    except Exception as e:
        debug_log(f"list_devices: enumeration raised ({e!r}); sd fallback", "audio")
        return _list_devices_sounddevice_fallback()

    default_out_id = _default_endpoint_id(_get_speakers)
    default_in_id = _default_endpoint_id(_get_microphone)

    def _shape(pairs, default_id):
        return [
            {
                "id": dev_id,
                "name": name,
                "is_default": bool(default_id) and dev_id == default_id,
                "available": True,  # only Active endpoints reach here
            }
            for dev_id, name in pairs
        ]

    result = {
        "inputs": _shape(capture, default_in_id),
        "outputs": _shape(render, default_out_id),
    }
    debug_log(
        f"list_devices: {len(result['outputs'])} outputs, "
        f"{len(result['inputs'])} inputs (Core Audio)",
        "audio",
    )
    return result


def _get_speakers():
    from pycaw.utils import AudioUtilities

    return AudioUtilities.GetSpeakers()


def _get_microphone():
    from pycaw.utils import AudioUtilities

    return AudioUtilities.GetMicrophone()


def _list_devices_sounddevice_fallback() -> dict:
    """Fail-open device list derived from sounddevice, with BLANK endpoint ids.

    Used when pycaw is unavailable. Ids are empty strings (no Core Audio), so
    selection resolution falls back to the saved friendly name. De-duping is
    left to the consumer; this just guarantees the user still sees devices.
    """
    if sd is None:
        return {"inputs": [], "outputs": []}
    try:
        devices = list(sd.query_devices())
    except Exception as e:
        debug_log(f"list_devices fallback: query_devices raised ({e!r})", "audio")
        return {"inputs": [], "outputs": []}

    def _items(predicate) -> list[dict]:
        return [
            {
                "id": "",
                "name": str(d.get("name", "")),
                "is_default": False,
                "available": True,
            }
            for d in devices
            if predicate(d)
        ]

    return {"inputs": _items(_is_input), "outputs": _items(_is_output)}


def _matches_any_active(sd_name: str, active_norm: list[str]) -> bool:
    """True if ``sd_name`` corresponds to any pycaw Active friendly name.

    Tolerant of WASAPI truncation: tests containment in BOTH directions so a
    truncated sounddevice name ("PD200X (2- FIFINE Microph") matches the full
    pycaw name ("PD200X (2- FIFINE Microphone)") and vice versa.
    """
    needle = _normalise(sd_name)
    if not needle:
        return False
    for active in active_norm:
        if not active:
            continue
        if needle in active or active in needle:
            return True
    return False


def list_real_devices() -> dict:
    """Enumerate real, currently-available audio devices.

    Returns a dict shaped for the settings UI::

        {
          "inputs":  [{"index": int, "name": str}, ...],
          "outputs": [{"index": int, "name": str}, ...],
          "current_in":  Optional[int],
          "current_out": Optional[int],
        }

    Only devices whose name matches a pycaw ACTIVE endpoint of the matching flow
    survive, so Sound Mapper / Stereo Mix / Primary Driver / disconnected
    endpoints are dropped. Host-API variants of the same physical device are
    de-duped by name, preferring the WASAPI variant (kept index + name come from
    that variant). Names + indices are the SOUNDDEVICE ones (what the playback
    path actually needs).

    Fail-open: if sounddevice is unavailable the lists are empty; if pycaw is
    unavailable the RAW sounddevice lists are returned unfiltered (so the user
    still sees their devices rather than an empty dropdown).
    """
    if sd is None:
        return {"inputs": [], "outputs": [], "current_in": None, "current_out": None}

    try:
        devices = list(sd.query_devices())
    except Exception as e:
        debug_log(f"list_real_devices: query_devices raised ({e!r})", "audio")
        return {"inputs": [], "outputs": [], "current_in": None, "current_out": None}

    # Default in/out indices (PortAudio). Best-effort.
    current_in: Optional[int] = None
    current_out: Optional[int] = None
    try:
        default = sd.default.device
        if isinstance(default, (list, tuple)) and len(default) >= 2:
            current_in = int(default[0]) if default[0] is not None and int(default[0]) >= 0 else None
            current_out = int(default[1]) if default[1] is not None and int(default[1]) >= 0 else None
    except Exception:
        pass

    active = _active_friendly_names()

    def _raw(predicate) -> list[dict]:
        return [
            {"index": i, "name": str(d.get("name", ""))}
            for i, d in enumerate(devices)
            if predicate(d)
        ]

    if active is None:
        # pycaw unavailable — fail open to the raw lists (still de-dupe nothing;
        # the UI de-dupes by name on its side too).
        return {
            "inputs": _raw(_is_input),
            "outputs": _raw(_is_output),
            "current_in": current_in,
            "current_out": current_out,
        }

    active_norm = [_normalise(n) for n in active]

    def _filtered(predicate) -> list[dict]:
        # Keep only sd devices of this flow that match an Active endpoint, then
        # de-dupe physical devices. De-dupe is truncation-tolerant: two entries
        # are the same physical device if one normalised name CONTAINS the other
        # (WASAPI truncates names, so the same headset can appear as both
        # "...(CORSAIR VOID " on WASAPI and "...(CORSAIR VOID WIRELESS v2...)"
        # on DirectSound). The winner per group is the higher host-API score,
        # then the longer (more descriptive) name, then the lower index — all
        # deterministic.
        kept: list[tuple[int, int, int, str]] = []  # (score, index, name_len, name)
        for i, d in enumerate(devices):
            if not predicate(d):
                continue
            name = str(d.get("name", ""))
            if not _matches_any_active(name, active_norm):
                continue
            score = _hostapi_score(sd, d.get("hostapi"))
            norm = _normalise(name)
            cand = (score, i, len(norm), name)

            # Find an existing kept entry that is the same physical device
            # (substring-equal, either direction).
            dup_pos = None
            for pos, (_s, _i, _nl, kname) in enumerate(kept):
                kn = _normalise(kname)
                if norm and kn and (norm in kn or kn in norm):
                    dup_pos = pos
                    break

            if dup_pos is None:
                kept.append(cand)
                continue
            # Same device — keep the better variant. Better = higher host-API
            # score; tie-break on longer name (more descriptive), then keep the
            # already-stored one (lower index, since iteration is ascending).
            cur = kept[dup_pos]
            if (cand[0], cand[2]) > (cur[0], cur[2]):
                kept[dup_pos] = cand

        # Preserve a stable, index-ascending order for the UI.
        chosen = sorted(kept, key=lambda t: t[1])
        return [{"index": idx, "name": nm} for _score, idx, _nl, nm in chosen]

    return {
        "inputs": _filtered(_is_input),
        "outputs": _filtered(_is_output),
        "current_in": current_in,
        "current_out": current_out,
    }


def match_name_to_sd_index(name: Optional[str], *, kind: str = "output") -> Optional[int]:
    """Resolve a device ``name`` to a sounddevice index for the given flow.

    ``kind`` is ``"output"`` (default) or ``"input"`` — only devices of that
    flow are considered. Matching normalises (casefold + strip) and is tolerant
    of WASAPI truncation: a candidate matches if the needle is contained in the
    sounddevice name OR the sounddevice name is contained in the needle. When
    several candidates match, the WASAPI host-API variant wins (then the
    lowest index, deterministically).

    Fail-open: returns ``None`` if ``name`` is empty, sounddevice is
    unavailable, nothing matches, or anything raises — the caller then uses
    PortAudio's own default device.
    """
    if not name or sd is None:
        return None
    predicate = _is_input if kind == "input" else _is_output
    needle = _normalise(name)
    if not needle:
        return None
    try:
        devices = list(sd.query_devices())
    except Exception as e:
        debug_log(f"match_name_to_sd_index: query_devices raised ({e!r})", "audio")
        return None

    candidates: list[tuple[int, int]] = []  # (score, index)
    for i, d in enumerate(devices):
        if not predicate(d):
            continue
        sd_norm = _normalise(d.get("name", ""))
        if not sd_norm:
            continue
        if needle in sd_norm or sd_norm in needle:
            candidates.append((_hostapi_score(sd, d.get("hostapi")), i))

    if not candidates:
        debug_log(f"match_name_to_sd_index: no {kind} match for {name!r}", "audio")
        return None
    # Highest host-API score first, then lowest index for determinism.
    candidates.sort(key=lambda t: (-t[0], t[1]))
    return candidates[0][1]
