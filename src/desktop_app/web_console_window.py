"""Native PyQt6 window hosting the React Control Console (/panel).

This replaces the old LogViewerWindow + Edge --app combination. The window
has a native title bar with the standard min/maximize/close so there is NO
double-chrome confusion. The React TopBar's decorative window-buttons are
hidden via injected CSS once the page loads.

Cold-start handling: until the daemon's API responds on 127.0.0.1:38130, we
show a native placeholder widget instead of the WebEngine view, so the user
never sees Chromium's "site can't be reached" page. The WebEngine view is
swapped in once the socket accepts connections.
"""

from __future__ import annotations

import socket
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QGuiApplication, QIcon, QPainter, QColor, QPen, QFont
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget


CONSOLE_URL = "http://127.0.0.1:38130/panel"
API_HOST = "127.0.0.1"
API_PORT = 38130
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 820


# CSS injected into the page so the React TopBar's fake window buttons are
# hidden (the native Qt title bar handles min/max/close).
HIDE_REACT_CHROME_CSS = """
/* React's TopBar fake window controls — hide; we use the native Qt chrome. */
[data-hide-in-native='true'],
#native-hide-window-controls {
    display: none !important;
}
"""


class _ConsoleBootPlaceholder(QWidget):
    """Native widget shown while waiting for the daemon's API to come up.

    Matches the same cyan-on-deep-navy aesthetic the React UI uses, so the
    visual transition is seamless once the WebEngine view swaps in.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tick = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(80)

    def _on_tick(self) -> None:
        self._tick = (self._tick + 1) % 1000
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = self.width()
        h = self.height()

        # Full-bleed deep-navy background
        painter.fillRect(self.rect(), QColor(8, 16, 30, 255))

        # Wordmark
        painter.setPen(QColor(0, 212, 255, 140))
        font = QFont("Inter, Segoe UI", 14, QFont.Weight.Medium)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 130)
        painter.setFont(font)
        painter.drawText(0, h // 2 - 80, w, 28, Qt.AlignmentFlag.AlignCenter, "JARVIS")

        # Pulsing concentric rings (matches React WaveformRings)
        import math
        cx = w // 2
        cy = h // 2 + 10
        for ring_idx in range(4):
            phase = (self._tick / 14.0) + ring_idx * 0.9
            scale = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(phase))
            radius = int(32 + ring_idx * 26 * scale)
            alpha = int(120 - ring_idx * 22)
            painter.setPen(QPen(QColor(0, 212, 255, max(25, alpha)), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(cx - radius, cy - radius, 2 * radius, 2 * radius)

        # Loading label
        painter.setPen(QColor(125, 211, 252, 200))
        font2 = QFont("Inter, Segoe UI", 11)
        font2.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 140)
        painter.setFont(font2)
        loading_text = "BOOTING DAEMON" + "." * ((self._tick // 8) % 4)
        painter.drawText(0, h // 2 + 120, w, 24, Qt.AlignmentFlag.AlignCenter, loading_text)

        painter.end()


class JarvisConsoleWindow(QMainWindow):
    """Native window hosting the React /panel UI."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Jarvis · Control Console")
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._center_on_screen()

        # Stack: page 0 = boot placeholder, page 1 = WebEngine view
        self._stack = QStackedWidget(self)
        self._placeholder = _ConsoleBootPlaceholder(self._stack)
        self._stack.addWidget(self._placeholder)

        self._view = QWebEngineView(self._stack)
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._stack.addWidget(self._view)

        self.setCentralWidget(self._stack)
        self._stack.setCurrentIndex(0)  # start on placeholder

        # Begin polling for the daemon to come up before loading the URL.
        self._poll_attempts = 0
        QTimer.singleShot(200, self._poll_daemon)

        self._view.page().loadFinished.connect(self._on_load_finished)

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
            # Inject CSS to hide the React TopBar's fake window buttons —
            # native Qt chrome handles min/max/close so there's no doubling up.
            script = (
                "var s=document.createElement('style');"
                f"s.innerText={HIDE_REACT_CHROME_CSS!r};"
                "document.head.appendChild(s);"
            )
            self._view.page().runJavaScript(script)
        else:
            # Page failed mid-load — retry after 1 s.
            QTimer.singleShot(1000, lambda: self._view.load(QUrl(CONSOLE_URL)))

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
