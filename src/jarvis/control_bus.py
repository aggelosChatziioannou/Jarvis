"""Local TCP control bus for cross-process Jarvis commands.

Why this exists: the desktop_app (PyQt6 face/HUD) and the daemon
(VoiceListener + TTS + LLM) run in SEPARATE Python processes when Jarvis
is launched in dev/source mode (the desktop process spawns the daemon
via subprocess.Popen). That means a module-level `_active_listener`
variable cannot be shared between them — the desktop's import of
`jarvis.daemon` is a fresh module with `_active_listener = None`,
regardless of what the daemon process has set.

Solution: a tiny TCP listener on 127.0.0.1:38127 that the daemon owns.
The desktop sends single-line text commands; the daemon dispatches them
to a registered callback (typically VoiceListener.reset_everything()).

Commands supported:
    STOP      → full interrupt (TTS + in-flight LLM + dialogue memory)
    MUTE      → toggle mic input suppression
    PING      → reply "PONG\\n" for health-check

Design notes:
  - Loopback only — no security risk beyond local processes.
  - Daemon thread, never blocks the main event loop.
  - One short-lived socket per command — survives daemon restarts.
  - Logs every command receipt so the user can see STOP fired in the feed.
"""

from __future__ import annotations

import socket
import threading
from typing import Callable, Optional

from .debug import debug_log


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 38127


class ControlBusServer:
    """Daemon-side server. One instance per daemon process."""

    def __init__(self, on_command: Callable[[str], Optional[str]]) -> None:
        """
        Args:
            on_command: Callback invoked for each received command.
                Receives the command string (e.g., "STOP"), may return a
                response string sent back to the client (or None).
        """
        self._on_command = on_command
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def start(self) -> bool:
        """Bind + start listening. Returns True on success."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((CONTROL_HOST, CONTROL_PORT))
            self._sock.listen(8)
            self._sock.settimeout(0.5)  # so the accept loop can poll _stop
        except OSError as e:
            debug_log(f"control_bus: bind failed on {CONTROL_HOST}:{CONTROL_PORT}: {e}", "bus")
            return False

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="ControlBusServer"
        )
        self._thread.start()
        print(f"🔌 Control bus listening on {CONTROL_HOST}:{CONTROL_PORT}", flush=True)
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                client, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            threading.Thread(
                target=self._handle_client, args=(client,), daemon=True
            ).start()

    def _handle_client(self, client: socket.socket) -> None:
        try:
            client.settimeout(2.0)
            data = client.recv(256)
            if not data:
                return
            command = data.decode("utf-8", errors="replace").strip()
            if not command:
                return
            debug_log(f"control_bus: received '{command}'", "bus")
            try:
                response = self._on_command(command)
            except Exception as e:
                debug_log(f"control_bus: handler error: {e}", "bus")
                response = f"ERROR {e}"
            if response is None:
                response = "OK"
            try:
                client.sendall((response + "\n").encode("utf-8"))
            except OSError:
                pass
        finally:
            try:
                client.close()
            except OSError:
                pass


def send_command(command: str, timeout: float = 1.5) -> Optional[str]:
    """Client-side helper. Send a single command, return the response.

    Returns None on failure (daemon not running, refused, timeout, etc.).
    Safe to call from any thread / process; opens a fresh socket per call.
    """
    try:
        with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=timeout) as sock:
            sock.sendall((command.strip() + "\n").encode("utf-8"))
            sock.settimeout(timeout)
            chunks: list[bytes] = []
            try:
                while True:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    chunks.append(chunk)
            except socket.timeout:
                pass
            return b"".join(chunks).decode("utf-8", errors="replace").strip()
    except OSError:
        return None


def ping() -> bool:
    """Quick health-check. True if the daemon's bus is reachable."""
    return send_command("PING") == "PONG"
