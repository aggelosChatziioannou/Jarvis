"""Native PyQt6 window hosting the React Control Console (/panel).

On Windows the window is frameless so the React UI can draw its own dark
integrated title bar.  macOS and Linux keep the native title bar and only
hide React's decorative window-buttons to avoid double-chrome.

Cold-start handling: until the daemon's API responds on 127.0.0.1:38130, we
show a native placeholder widget instead of the WebEngine view, so the user
never sees Chromium's "site can't be reached" page. The WebEngine view is
swapped in once the socket accepts connections.
"""

from __future__ import annotations

import ctypes
import math
import socket
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, QTimer, QObject
from PyQt6.QtGui import QGuiApplication, QIcon, QPainter, QColor, QPen, QFont, QRadialGradient
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget


CONSOLE_URL = "http://127.0.0.1:38130/panel"
API_HOST = "127.0.0.1"
API_PORT = 38130
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 820


class _ConsolePage(QWebEnginePage):
    """Custom page that intercepts console:// navigation requests from JS bridge."""

    def __init__(self, console: "JarvisConsoleWindow", parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._console = console

    def acceptNavigationRequest(self, url: QUrl, type_, isMainFrame):  # noqa: N802
        if url.scheme().lower() == "console":
            self._console._handle_console_url(url)
            return False
        return super().acceptNavigationRequest(url, type_, isMainFrame)


class _ConsoleBootPlaceholder(QWidget):
    """Native widget shown while waiting for the daemon's API to come up.

    Premium minimal aesthetic: clean wordmark, thin progress bar, status text.
    No sci-fi effects, no particles, no rings.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tick = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(50)

    def _on_tick(self) -> None:
        self._tick = (self._tick + 1) % 1000
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = self.width()
        h = self.height()
        cx = w // 2
        cy = h // 2

        # ── Background ──
        gradient = QRadialGradient(cx, cy, max(w, h) * 0.7)
        gradient.setColorAt(0.0, QColor(13, 17, 23))
        gradient.setColorAt(1.0, QColor(8, 12, 20))
        painter.fillRect(self.rect(), gradient)

        # ── Wordmark ──
        painter.setPen(QColor(255, 255, 255, 230))
        font = QFont("Inter, Segoe UI", 28, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        painter.setFont(font)
        painter.drawText(0, cy - 50, w, 40, Qt.AlignmentFlag.AlignCenter, "JARVIS")

        # ── Progress bar track ──
        bar_w = 360
        bar_h = 2
        bar_x = cx - bar_w // 2
        bar_y = cy + 8
        painter.fillRect(bar_x, bar_y, bar_w, bar_h, QColor(26, 35, 50))

        # ── Progress bar fill (subtle pulse to show activity) ──
        pulse = 0.35 + 0.15 * math.sin(self._tick * 0.08)
        fill_w = int(bar_w * pulse)
        fill_x = bar_x + (bar_w - fill_w) // 2
        painter.fillRect(fill_x, bar_y, fill_w, bar_h, QColor(79, 209, 197, 200))

        # ── Status text ──
        painter.setPen(QColor(100, 116, 139, 220))
        font_status = QFont("Inter, Segoe UI", 12)
        font_status.setWeight(QFont.Weight.Normal)
        painter.setFont(font_status)
        painter.drawText(0, bar_y + 18, w, 22, Qt.AlignmentFlag.AlignCenter, "Loading...")

        painter.end()


class JarvisConsoleWindow(QMainWindow):
    """Native window hosting the React /panel UI."""

    def __init__(self, parent=None) -> None:
        # Pass the window flags to QMainWindow at construction so the HWND is
        # created with the right styles from the start. Mid-life setWindowFlags
        # destroys and re-creates the native window, which on Windows triggers
        # an access-violation in QtCore.pyd once a QWebEngineView (Chromium
        # compositor child HWND) is attached. Qt 6.5+ also has built-in
        # frameless handling on Windows (resize borders, Aero Snap, DPI), so
        # we no longer need a custom nativeEvent override.
        flags = Qt.WindowType.Window
        if sys.platform == "win32":
            flags |= Qt.WindowType.FramelessWindowHint
        super().__init__(parent, flags)

        self._frameless_ok = sys.platform == "win32"
        self.setWindowTitle("Jarvis · Control Console")

        self._stack = QStackedWidget(self)
        self._placeholder = _ConsoleBootPlaceholder(self._stack)
        self._stack.addWidget(self._placeholder)

        self._view = QWebEngineView(self._stack)
        self._page = _ConsolePage(self, self._view)
        self._view.setPage(self._page)
        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._stack.addWidget(self._view)

        self.setCentralWidget(self._stack)
        self._stack.setCurrentIndex(0)  # start on placeholder

        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._center_on_screen()

        # Begin polling for the daemon to come up before loading the URL.
        self._poll_attempts = 0
        QTimer.singleShot(200, self._poll_daemon)

        self._page.loadFinished.connect(self._on_load_finished)

    def _center_on_screen(self) -> None:
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            geom = screen.availableGeometry()
            x = geom.left() + (geom.width() - DEFAULT_WIDTH) // 2
            y = geom.top() + (geom.height() - DEFAULT_HEIGHT) // 2
            self.move(x, y)
        except Exception:
            pass

    def _poll_daemon(self) -> None:
        """Wait until 127.0.0.1:38130 accepts connections, then load the URL."""
        self._poll_attempts += 1
        try:
            with socket.create_connection((API_HOST, API_PORT), timeout=0.2):
                self._view.load(QUrl(CONSOLE_URL))
                return
        except OSError:
            if self._poll_attempts < 600:  # ~120s max wait
                QTimer.singleShot(200, self._poll_daemon)

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            # Swap from placeholder to the real WebEngine view.
            self._stack.setCurrentIndex(1)
            # Inject the JS bridge so React can drive min/max/close/drag.
            self._inject_console_bridge()
            # Hide React's fake window-buttons whenever Qt is supplying the
            # chrome — i.e. on macOS/Linux always, and on Windows whenever the
            # frameless flag flip didn't take (fallback path). Without this,
            # the fallback path shows double chrome.
            if sys.platform != "win32" or not self._frameless_ok:
                script = (
                    "var s=document.createElement('style');"
                    "s.innerText='[data-hide-in-native=\"true\"]{display:none!important;}';"
                    "document.head.appendChild(s);"
                )
                self._page.runJavaScript(script)
        else:
            # Page failed mid-load — retry after 1 s.
            QTimer.singleShot(1000, lambda: self._view.load(QUrl(CONSOLE_URL)))

    def _inject_console_bridge(self) -> None:
        """Expose window.consoleMinimize / Maximize / Close / StartSystemMove."""
        script = r"""
        (function() {
            if (window.__consoleBridgeInjected) return;
            window.__consoleBridgeInjected = true;

            window.consoleMinimize = function() {
                window.location.href = 'console://minimize';
            };
            window.consoleMaximize = function() {
                window.location.href = 'console://maximize';
            };
            window.consoleClose = function() {
                window.location.href = 'console://close';
            };
            window.consoleStartSystemMove = function() {
                window.location.href = 'console://startsystemmove';
            };
        })();
        """
        self._page.runJavaScript(script)

    def _handle_console_url(self, url: QUrl) -> None:
        action = url.host().lower()
        if action == "minimize":
            self.showMinimized()
        elif action == "maximize":
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
        elif action == "close":
            self.hide()
        elif action == "startsystemmove":
            self._start_system_move()

    def _start_system_move(self) -> None:
        """Ask the window manager to take over dragging this window.

        Tries Qt's portable `startSystemMove()` first; on Windows that
        sometimes silently no-ops when the call originates from a
        QWebEngineView mouse event, so we fall back to sending the native
        `WM_NCLBUTTONDOWN`/`HTCAPTION` message.
        """
        handle = self.windowHandle()
        if handle is not None:
            try:
                if handle.startSystemMove():
                    return
            except Exception:
                pass

        if sys.platform == "win32":
            try:
                WM_NCLBUTTONDOWN = 0xA1
                HTCAPTION = 2
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(
                    int(self.winId()), WM_NCLBUTTONDOWN, HTCAPTION, 0
                )
            except Exception:
                pass

    def closeEvent(self, event) -> None:  # noqa: N802
        # Hide instead of destroying so re-opening from the tray is instant
        # (and the WebEngine state — scroll position, log buffer — is kept).
        event.ignore()
        self.hide()


def main() -> None:
    """Stand-alone smoke test."""
    app = QApplication(sys.argv)
    w = JarvisConsoleWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
