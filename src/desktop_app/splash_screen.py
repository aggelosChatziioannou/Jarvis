"""
Jarvis Splash Screen

Premium minimal startup splash shown while the desktop app initializes.
Clean, professional aesthetic — no sci-fi effects, no particles, no orbs.
"""

from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QProgressBar
from PyQt6.QtGui import QPainter, QColor, QFont, QRadialGradient
from PyQt6.QtCore import Qt, pyqtSignal


class SplashScreen(QWidget):
    """Frameless splash screen shown during application startup."""

    finished = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 260)
        self._center_on_screen()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Wordmark
        self._title = QLabel("JARVIS")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont("Inter, Segoe UI, sans-serif")
        title_font.setPointSize(26)
        title_font.setWeight(QFont.Weight.Bold)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        self._title.setFont(title_font)
        self._title.setStyleSheet("color: #ffffff; background: transparent;")
        layout.addWidget(self._title)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(280, 2)
        self._progress.setStyleSheet("""
            QProgressBar {
                background-color: #1a2332;
                border: none;
                border-radius: 1px;
            }
            QProgressBar::chunk {
                background-color: #4fd1c5;
                border-radius: 1px;
            }
        """)
        self._progress.setRange(0, 0)  # indeterminate — pulsing animation
        self._progress.setMaximumHeight(2)
        layout.addSpacing(24)
        layout.addWidget(self._progress, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status label
        self._status_label = QLabel("Initializing...")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_font = QFont("Inter, Segoe UI, sans-serif")
        status_font.setPointSize(11)
        status_font.setWeight(QFont.Weight.Normal)
        self._status_label.setFont(status_font)
        self._status_label.setStyleSheet("color: #64748b; background: transparent;")
        layout.addSpacing(16)
        layout.addWidget(self._status_label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dark background with subtle center glow
        gradient = QRadialGradient(self.width() / 2, self.height() / 2, self.height())
        gradient.setColorAt(0, QColor(13, 17, 23))
        gradient.setColorAt(1, QColor(8, 12, 20))
        painter.fillRect(self.rect(), gradient)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = (geom.width() - self.width()) // 2 + geom.x()
            y = (geom.height() - self.height()) // 2 + geom.y()
            self.move(x, y)

    def set_status(self, status: str):
        """Update the status message."""
        self._status_label.setText(status)
        QApplication.processEvents()

    def close_splash(self):
        """Close the splash screen gracefully."""
        self.finished.emit()
        self.close()
