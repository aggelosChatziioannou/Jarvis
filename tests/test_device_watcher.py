"""DeviceWatcher: live Windows Core Audio device-change notifications.

The watcher registers a pycaw ``IMMNotificationClient`` on its own MTA COM
thread and invokes a single debounced callback on any add / remove / state /
default-device change. Behaviours under test:

  * start() registers the notification client; stop() unregisters it.
  * a burst of raw Core Audio callbacks coalesces into ONE on_change call.
  * fail-open: if pycaw is unavailable or registration raises, start() returns
    False and never raises (the UI poll + per-play TTS re-resolve still adapt).

The real COM client base and the device enumerator are faked so the wiring is
exercised without touching real Windows COM (verified manually by the user).
"""

import sys
import time
import types

import pytest

import jarvis.output.device_watcher as dw


@pytest.fixture
def fake_pycaw(monkeypatch):
    """Fake the COM client base + the device enumerator.

    ``MMNotificationClient`` is swapped for ``object`` so the watcher's client
    subclass instantiates without comtypes/COM; ``pycaw.utils`` is swapped for a
    stub exposing a mock ``AudioUtilities.GetDeviceEnumerator``. COM init is
    neutralised so tests never call real ``CoInitializeEx``.
    """
    monkeypatch.setattr(dw, "MMNotificationClient", object)
    monkeypatch.setattr(dw.DeviceWatcher, "_init_com", lambda self: False)
    monkeypatch.setattr(dw.DeviceWatcher, "_uninit_com", lambda self: None)

    enumerator = types.SimpleNamespace(
        registered=[],
        unregistered=[],
    )

    def _register(client):
        enumerator.registered.append(client)

    def _unregister(client):
        enumerator.unregistered.append(client)

    enumerator.RegisterEndpointNotificationCallback = _register
    enumerator.UnregisterEndpointNotificationCallback = _unregister

    fake_utils = types.ModuleType("pycaw.utils")
    fake_utils.AudioUtilities = types.SimpleNamespace(
        GetDeviceEnumerator=lambda: enumerator
    )
    monkeypatch.setitem(sys.modules, "pycaw.utils", fake_utils)
    return enumerator


def test_start_registers_and_stop_unregisters(fake_pycaw):
    w = dw.DeviceWatcher(on_change=lambda: None, debounce_sec=0.01)
    assert w.start() is True
    assert len(fake_pycaw.registered) == 1
    client = fake_pycaw.registered[0]

    w.stop()
    assert fake_pycaw.unregistered == [client]


def test_callback_burst_coalesces_to_one_on_change(fake_pycaw):
    fired = []
    w = dw.DeviceWatcher(on_change=lambda: fired.append(1), debounce_sec=0.05)
    assert w.start() is True
    client = fake_pycaw.registered[0]

    # Simulate a single physical change that fires several Core Audio callbacks.
    client.on_device_added("id-1")
    client.on_device_state_changed("id-1", "Active", 1)
    client.on_default_device_changed("eRender", 0, "eConsole", 0, "id-1")
    client.on_device_removed("id-2")

    time.sleep(0.25)
    assert fired == [1]  # debounced into exactly one refresh
    w.stop()


def test_separate_changes_fire_separately(fake_pycaw):
    fired = []
    w = dw.DeviceWatcher(on_change=lambda: fired.append(1), debounce_sec=0.05)
    assert w.start() is True
    client = fake_pycaw.registered[0]

    client.on_device_added("id-1")
    time.sleep(0.2)
    client.on_device_removed("id-1")
    time.sleep(0.2)

    assert fired == [1, 1]
    w.stop()


def test_fail_open_when_pycaw_client_unavailable(monkeypatch):
    monkeypatch.setattr(dw, "MMNotificationClient", None)
    w = dw.DeviceWatcher(on_change=lambda: None)
    assert w.start() is False  # no raise
    w.stop()  # no raise


def test_fail_open_when_registration_raises(monkeypatch):
    monkeypatch.setattr(dw, "MMNotificationClient", object)
    monkeypatch.setattr(dw.DeviceWatcher, "_init_com", lambda self: False)
    monkeypatch.setattr(dw.DeviceWatcher, "_uninit_com", lambda self: None)

    def _boom():
        raise OSError("COM enumerator unavailable")

    fake_utils = types.ModuleType("pycaw.utils")
    fake_utils.AudioUtilities = types.SimpleNamespace(GetDeviceEnumerator=_boom)
    monkeypatch.setitem(sys.modules, "pycaw.utils", fake_utils)

    w = dw.DeviceWatcher(on_change=lambda: None, debounce_sec=0.01)
    assert w.start() is False
    w.stop()  # no raise


def test_on_change_exception_does_not_propagate(fake_pycaw):
    def _bad():
        raise RuntimeError("downstream boom")

    w = dw.DeviceWatcher(on_change=_bad, debounce_sec=0.01)
    assert w.start() is True
    client = fake_pycaw.registered[0]
    client.on_device_added("id-1")  # must not raise out of the watcher
    time.sleep(0.1)
    w.stop()
