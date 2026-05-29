"""Live Windows Core Audio device-change watcher.

Registers a pycaw ``IMMNotificationClient`` so Jarvis learns about audio device
add / remove / state / default-device changes the moment they happen, then
invokes a single debounced callback. The daemon uses that callback to (a) push a
``devices_changed`` signal to the React UI over the existing ``/ws/state`` socket
and (b) ask the Wispr bridge to re-resolve its mic (reconnect when the chosen
device reappears).

Why a dedicated thread?
  comtypes initialises COM as an STA on the thread that imports it (the daemon
  main thread). STA notification callbacks need a running message pump, which the
  daemon main loop does not provide. So the watcher runs on its OWN thread,
  initialised as MTA (``COINIT_MULTITHREADED``); Windows then delivers the
  callbacks on RPC worker threads with no pump required. The watcher thread
  simply holds the apartment alive until :meth:`stop`.

It NEVER touches PortAudio (safe alongside the bridge's open mic stream) and is
fail-open end to end: if pycaw/COM is unavailable or registration raises, the
watcher quietly delivers no events. The UI's periodic device-list poll and the
per-play TTS device re-resolution still adapt, so nothing breaks.

Privacy: pycaw reads local Core Audio only. No network, no telemetry.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from ..debug import debug_log

# Imported at module scope so tests can monkeypatch
# ``device_watcher.MMNotificationClient``. Guarded because pycaw/comtypes may be
# unavailable in some environments; :meth:`DeviceWatcher.start` fails open when
# this is None.
try:  # pragma: no cover - trivial import guard
    from pycaw.callbacks import MMNotificationClient  # type: ignore
except Exception:  # pragma: no cover
    MMNotificationClient = None  # type: ignore


class DeviceWatcher:
    """Watch Core Audio for device changes and fire a debounced callback.

    Parameters
    ----------
    on_change:
        Zero-argument callable invoked (on a worker thread) after a device
        change settles. Exceptions raised by it are swallowed and logged.
    debounce_sec:
        Coalesce window. A single physical change fires several Core Audio
        callbacks in a burst; they collapse into one ``on_change`` call after
        this many seconds of quiet.
    """

    def __init__(self, on_change: Callable[[], None], *, debounce_sec: float = 0.4) -> None:
        self._on_change = on_change
        self._debounce_sec = max(0.0, float(debounce_sec))
        self._client = None
        self._enumerator = None
        self._registered = False
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop_evt = threading.Event()
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ COM
    def _init_com(self) -> bool:
        """Initialise COM as MTA on the current thread. Returns True if WE did.

        Best-effort + isolated so tests can neutralise it. Returns False (rather
        than raising) on any failure, in which case the caller does not later
        call :meth:`_uninit_com`.
        """
        try:
            import comtypes

            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            return True
        except Exception as e:  # pragma: no cover - environment dependent
            debug_log(f"device_watcher: CoInitializeEx failed ({e!r})", "audio")
            return False

    def _uninit_com(self) -> None:
        try:
            import comtypes

            comtypes.CoUninitialize()
        except Exception:  # pragma: no cover - environment dependent
            pass

    # --------------------------------------------------------------- public
    def start(self) -> bool:
        """Register the notification client. Returns True on success.

        Fail-open: returns False (never raises) if pycaw is unavailable or
        registration fails. Idempotent — a second call returns the current
        registration state without re-registering.
        """
        if self._thread is not None:
            return self._registered
        if MMNotificationClient is None:
            debug_log(
                "device_watcher: pycaw unavailable; live device events off", "audio"
            )
            return False

        self._ready.clear()
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run, name="AudioDeviceWatcher", daemon=True
        )
        self._thread.start()
        # Wait for the thread to attempt registration so the return value is
        # meaningful. The bound is generous; registration is near-instant.
        self._ready.wait(timeout=3.0)
        return self._registered

    def stop(self) -> None:
        """Unregister and tear down. Safe to call repeatedly / when never started."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._stop_evt.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    # --------------------------------------------------------------- worker
    def _run(self) -> None:
        com_inited = False
        try:
            com_inited = self._init_com()
            from pycaw.utils import AudioUtilities

            self._client = self._build_client()
            self._enumerator = AudioUtilities.GetDeviceEnumerator()
            self._enumerator.RegisterEndpointNotificationCallback(self._client)
            self._registered = True
            debug_log(
                "device_watcher: registered Core Audio notification client", "audio"
            )
        except Exception as e:
            debug_log(f"device_watcher: registration failed ({e!r})", "audio")
            self._registered = False
            self._client = None
            self._enumerator = None
        finally:
            self._ready.set()

        if not self._registered:
            if com_inited:
                self._uninit_com()
            return

        # Hold the (MTA) apartment alive so callbacks keep being delivered.
        self._stop_evt.wait()

        try:
            if self._enumerator is not None and self._client is not None:
                self._enumerator.UnregisterEndpointNotificationCallback(self._client)
                debug_log("device_watcher: unregistered notification client", "audio")
        except Exception as e:
            debug_log(f"device_watcher: unregister failed ({e!r})", "audio")
        finally:
            self._registered = False
            self._client = None
            self._enumerator = None
            if com_inited:
                self._uninit_com()

    def _build_client(self):
        """Build the pycaw notification client; every callback fans into _fire."""
        watcher = self

        class _Client(MMNotificationClient):  # type: ignore[misc, valid-type]
            def on_device_added(self, *args):
                watcher._fire("added")

            def on_device_removed(self, *args):
                watcher._fire("removed")

            def on_device_state_changed(self, *args):
                watcher._fire("state_changed")

            def on_default_device_changed(self, *args):
                watcher._fire("default_changed")

        return _Client()

    # -------------------------------------------------------------- debounce
    def _fire(self, reason: str) -> None:
        debug_log(f"device_watcher: change ({reason})", "audio")
        fire_now = False
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._debounce_sec <= 0:
                fire_now = True
            else:
                self._timer = threading.Timer(self._debounce_sec, self._emit)
                self._timer.daemon = True
                self._timer.start()
        if fire_now:
            self._emit()

    def _emit(self) -> None:
        try:
            self._on_change()
        except Exception as e:  # pragma: no cover - defensive
            debug_log(f"device_watcher: on_change raised ({e!r})", "audio")
