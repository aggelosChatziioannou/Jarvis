"""Frameless, always-on-top web HUD hosting the React Home page.

Replaces the legacy PyQt6 face/HUD windows. The actual UI is rendered by
the React app (built into ui/dist and served by api_server on 38130).
This module is just a native container that:
  - is frameless + always-on-top
  - has a translucent background so only the card is visible
  - is draggable via the React UI (title-changed bridge)
  - supports minimize / close from the React UI
  - is small (~360×440)
  - loads http://127.0.0.1:38130/

Cold-start handling: until the daemon's API responds on /api/health, we
show a tiny native loading widget (not the WebEngine) so the user never
sees a 'site can't be reached' page. The WebEngine view is created lazily
once the health check passes, then swapped in.
"""

from __future__ import annotations

import socket
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, QTimer, QObject
from PyQt6.QtGui import QGuiApplication, QPainter, QColor, QPen, QFont
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
    QLabel,
)


CARD_WIDTH = 380
CARD_HEIGHT = 460
HUD_URL = "http://127.0.0.1:38130/"
API_HOST = "127.0.0.1"
API_PORT = 38130


class _HUDPage(QWebEnginePage):
    """Custom page that ignores custom scheme navigation requests from JS bridge."""

    def __init__(self, hud: "WebFloatingHUD", parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._hud = hud

    def acceptNavigationRequest(self, url: QUrl, type_, isMainFrame):  # noqa: N802
        if url.scheme().lower() == "hud":
            self._hud._handle_hud_url(url)
            return False
        return super().acceptNavigationRequest(url, type_, isMainFrame)


class _LoadingPlaceholder(QWidget):
    """Tiny native widget shown until the daemon's API is reachable.

    Draws the same rounded cyan-on-deep-navy aesthetic as the React card,
    so the cold-start visual is consistent with what shows up afterwards.
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

        # Card surface
        card_rect = self.rect().adjusted(8, 8, -8, -8)
        painter.setPen(QPen(QColor(0, 212, 255, 30), 1))
        painter.setBrush(QColor(8, 16, 30, 235))
        painter.drawRoundedRect(card_rect, 20, 20)

        # Wordmark
        painter.setPen(QColor(0, 212, 255, 100))
        font = QFont("Inter, Segoe UI", 9, QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(
            32, 48, "JARVIS"
        )

        # Pulsing concentric rings (matches the React WaveformRings vibe)
        cx = w // 2
        cy = h // 2 - 20
        for ring_idx in range(3):
            phase = (self._tick / 14.0) + ring_idx * 1.0
            import math
            scale = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(phase))
            radius = int(20 + ring_idx * 18 * scale)
            alpha = int(80 - ring_idx * 20)
            painter.setPen(QPen(QColor(0, 212, 255, max(20, alpha)), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(cx - radius, cy - radius, 2 * radius, 2 * radius)

        # Loading label
        painter.setPen(QColor(125, 211, 252, 180))
        font2 = QFont("Inter, Segoe UI", 8)
        font2.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 130)
        painter.setFont(font2)
        loading_text = "BOOTING DAEMON" + "." * ((self._tick // 8) % 4)
        painter.drawText(0, h - 80, w, 20, Qt.AlignmentFlag.AlignCenter, loading_text)

        painter.end()


class WebFloatingHUD(QWidget):
    """Tiny native shell around a QWebEngineView showing the React Home card."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Jarvis")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(CARD_WIDTH, CARD_HEIGHT)

        # Stack: page 0 = loading placeholder, page 1 = QWebEngineView
        self._stack = QStackedWidget(self)
        self._placeholder = _LoadingPlaceholder(self._stack)
        self._stack.addWidget(self._placeholder)

        self._view = QWebEngineView(self._stack)
        self._page = _HUDPage(self, self._view)
        self._view.setPage(self._page)
        self._page.setBackgroundColor(Qt.GlobalColor.transparent)
        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._stack.addWidget(self._view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack)

        # Start on the placeholder.
        self._stack.setCurrentIndex(0)

        # Begin polling for the daemon's API to come up.
        self._poll_attempts = 0
        QTimer.singleShot(200, self._poll_daemon)

        # Wire JS bridge injection for when the page loads.
        self._page.loadFinished.connect(self._on_page_loaded)

        # Place in top-right corner by default.
        self._move_to_default_corner()

    # ----------------- daemon readiness gate -----------------

    def _poll_daemon(self) -> None:
        """Wait until 127.0.0.1:38130 accepts connections, then load the React UI."""
        self._poll_attempts += 1
        try:
            with socket.create_connection((API_HOST, API_PORT), timeout=0.2):
                # Daemon is up — load the page and prepare to swap views.
                self._view.load(QUrl(HUD_URL))
                return
        except OSError:
            # Not ready yet. Keep showing the placeholder.
            if self._poll_attempts < 600:  # ~120s max
                QTimer.singleShot(200, self._poll_daemon)

    def _on_page_loaded(self, ok: bool) -> None:
        if ok:
            # Swap from placeholder to the real WebEngine view.
            self._stack.setCurrentIndex(1)
            self._inject_js_bridge()
        else:
            # Stay on placeholder; retry the load in 1 s.
            QTimer.singleShot(1000, lambda: self._view.load(QUrl(HUD_URL)))

    # ----------------- positioning -----------------

    def _move_to_default_corner(self) -> None:
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            geom = screen.availableGeometry()
            x = geom.right() - CARD_WIDTH - 32
            y = geom.top() + 32
            self.move(x, y)
        except Exception:
            pass

    # ----------------- JS bridge -----------------

    def _inject_js_bridge(self) -> None:
        """Expose window.hudMinimize / window.hudClose / window.hudMove to JS,
        wire a document-wide drag handler, and hide the React close button.

        The React UI only marks the small "JARVIS" text label as a drag handle,
        which is too tight a target for users. We attach a capture-phase
        mousedown listener on the document so dragging works from any
        non-interactive area of the card. Buttons, inputs, links etc. are
        excluded so they keep their normal click behaviour.

        We also inject CSS that hides the React top-bar close (X) button —
        the user can hide the HUD via minimize or the tray menu's Exit; the
        bare X was too easy to click by accident with no obvious way back.
        """
        script = r"""
        (function() {
            if (window.__hudBridgeInjected) return;
            window.__hudBridgeInjected = true;

            window.hudMinimize = function() {
                window.location.href = 'hud://minimize';
            };
            window.hudClose = function() {
                window.location.href = 'hud://close';
            };
            // Delta-based move kept for legacy callers; new code should
            // prefer hudStartSystemMove which delegates to the OS and is
            // immune to per-monitor DPI scaling.
            window.hudMove = function(dx, dy) {
                window.location.href = 'hud://move?dx=' + dx + '&dy=' + dy;
            };
            window.hudStartSystemMove = function() {
                window.location.href = 'hud://startsystemmove';
            };

            // --- Drag from the top of the card via OS-native window move
            // Restricted to clientY < DRAG_ZONE so the orb, status text,
            // and control buttons are NOT swallowed by the drag region.
            // Buttons (minimize) inside the drag zone still take priority.
            var DRAG_ZONE = 70;
            var INTERACTIVE = 'button, input, textarea, select, a, [role="button"], [role="link"], [contenteditable="true"]';

            document.addEventListener('mousedown', function(e) {
                if (e.button !== 0) return;             // left click only
                if (e.clientY > DRAG_ZONE) return;      // only top strip
                if (e.target && e.target.closest && e.target.closest(INTERACTIVE)) return;
                // Stop React's own drag handler (on the JARVIS label) so we
                // do not fight it for control of the cursor.
                e.preventDefault();
                e.stopPropagation();
                window.hudStartSystemMove();
            }, true);

            // --- Hide the React close (X) button -------------------------
            // The user explicitly asked for this so the HUD cannot be
            // dismissed by accident. Minimize button stays.
            // Top strip also gets a `move` cursor so the drag region is
            // discoverable without a tooltip.
            var hideCss = document.createElement('style');
            hideCss.textContent =
                'button[title="Close"]{display:none !important;}';
            document.head.appendChild(hideCss);
        })();
        """
        self._page.runJavaScript(script)

    def _handle_hud_url(self, url: QUrl) -> None:
        action = url.host().lower()
        if action == "minimize":
            self.showMinimized()
        elif action == "close":
            self.hide()
        elif action == "startsystemmove":
            # Hand dragging off to the OS so it handles multi-monitor,
            # per-monitor DPI, and edge-snap correctly. Without this the
            # delta-based JS approach lost most of the movement on
            # displays scaled >100% (cursor moves 10 px, window moves 6).
            self._start_system_move()
        elif action == "move":
            # Legacy delta-based move kept for backwards compat with any
            # JS that still calls hudMove. Avoid using this on HiDPI.
            query = url.query()
            dx = 0
            dy = 0
            for part in query.split("&"):
                if part.startswith("dx="):
                    try:
                        dx = int(part[3:])
                    except ValueError:
                        pass
                elif part.startswith("dy="):
                    try:
                        dy = int(part[3:])
                    except ValueError:
                        pass
            if dx or dy:
                self.move(self.x() + dx, self.y() + dy)

    def _start_system_move(self) -> None:
        """Ask the window manager to take over dragging this window.

        Tries Qt's portable `startSystemMove()` first; on Windows that
        sometimes silently no-ops when the call originates from a
        QWebEngineView mouse event, so we fall back to sending the native
        `WM_NCLBUTTONDOWN`/`HTCAPTION` message which is what Windows itself
        uses for caption drags.
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
                import ctypes
                WM_NCLBUTTONDOWN = 0xA1
                HTCAPTION = 2
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(
                    int(self.winId()), WM_NCLBUTTONDOWN, HTCAPTION, 0
                )
            except Exception:
                pass


def main() -> None:
    """Stand-alone smoke test."""
    app = QApplication(sys.argv)
    hud = WebFloatingHUD()
    hud.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
