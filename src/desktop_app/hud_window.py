"""Unified Jarvis HUD window — single Iron Man-style cinematic surface.

Replaces the old pair of separate windows (FaceWindow + LogViewerWindow)
with one frameless, always-on-top widget that hosts:

  • The animated face (existing `LowPolyFaceWidget`) wrapped in a panel
    that paints two rotating tech-rings (one CW, one CCW) on top.
  • A live feed (read-only QTextEdit) bound to `LogSignals.new_log`.
  • A system telemetry card (mic / model / MCPs / voice).
  • A control bar with a STOP button that triggers a full reset via the
    cross-process control bus on 127.0.0.1:38127.
  • A top title bar (drag region + clock + min/close buttons).

Sub-windows (Settings, Memory Viewer, Dictation History) remain separate
dialogs — they are opened through the menu button or the tray icon. This
file only concerns the primary HUD surface.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPalette,
    QPen,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .face_widget import LowPolyFaceWidget, JarvisState, get_jarvis_state
from .themes import COLORS, JARVIS_THEME_STYLESHEET


# ─── Face panel with rotating HUD rings ────────────────────────────────


class FacePanel(QWidget):
    """Hosts the existing low-poly face and overlays two rotating tech-rings.

    Rings are painted in this widget's `paintEvent` AFTER the child face
    has rendered itself (we rely on Qt's natural paint order: children
    paint themselves, then this widget's paintEvent runs on top because
    we draw in `paintEvent` rather than embedding the face as a layout
    sibling). To make that simple we use a manual layout: the face fills
    the panel; the panel adds painted overlays.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.face = LowPolyFaceWidget(self)
        self._angle_outer = 0.0
        self._angle_inner = 0.0
        # The face widget handles its own ~30 fps animation; we piggyback
        # on a slightly slower 25 fps timer for the ring rotation so we
        # don't double the paint budget.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        # Face takes the full panel; rings paint into the same area.
        self.face.setGeometry(self.rect())
        super().resizeEvent(event)

    def _tick(self) -> None:
        # Slow rotations — fast enough to feel alive, slow enough not to
        # distract from the face.
        self._angle_outer = (self._angle_outer + 0.6) % 360.0
        self._angle_inner = (self._angle_inner - 0.9) % 360.0
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        # The face child paints itself; we draw the rings on top. We
        # avoid clipping by using an unclipped painter on `self`.
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        r = self.rect()
        cx, cy = r.center().x(), r.center().y()
        side = min(r.width(), r.height())
        outer_radius = side * 0.46
        inner_radius = side * 0.40

        amber = QColor(COLORS["accent_secondary"])
        cyan = QColor(COLORS["hud_cyan_light"])

        # Activation-driven opacity
        try:
            activation = float(getattr(self.face, "_activation_level", 1.0))
        except Exception:
            activation = 1.0
        activation = max(0.0, min(1.0, activation))

        # Outer arc (amber, 270°, rotating CW)
        outer_color = QColor(amber)
        outer_color.setAlphaF(0.55 * activation)
        pen = QPen(outer_color)
        pen.setWidthF(2.2)
        p.setPen(pen)
        outer_rect = QRectF(cx - outer_radius, cy - outer_radius,
                            outer_radius * 2, outer_radius * 2)
        p.drawArc(
            outer_rect,
            int((self._angle_outer) * 16),
            int(270 * 16),
        )
        # Outer tick marks at the start/end of the arc
        for offset in (0, 270):
            theta = math.radians(self._angle_outer + offset)
            x1 = cx + math.cos(theta) * outer_radius
            y1 = cy - math.sin(theta) * outer_radius
            x2 = cx + math.cos(theta) * (outer_radius + 8)
            y2 = cy - math.sin(theta) * (outer_radius + 8)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Inner arc (cyan, 180°, rotating CCW) — data ring
        inner_color = QColor(cyan)
        inner_color.setAlphaF(0.55 * activation)
        pen2 = QPen(inner_color)
        pen2.setWidthF(1.6)
        p.setPen(pen2)
        inner_rect = QRectF(cx - inner_radius, cy - inner_radius,
                            inner_radius * 2, inner_radius * 2)
        p.drawArc(
            inner_rect,
            int((self._angle_inner + 90) * 16),
            int(180 * 16),
        )
        # Three dots equally spaced along the inner ring path
        for i in range(3):
            theta = math.radians(self._angle_inner + 90 + i * 60)
            x = cx + math.cos(theta) * inner_radius
            y = cy - math.sin(theta) * inner_radius
            p.setBrush(inner_color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), 2.5, 2.5)

        p.end()

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(360, 360)


# ─── Live feed panel ───────────────────────────────────────────────────


class FeedPanel(QFrame):
    """Read-only colour-coded log feed."""

    MAX_LINES = 500

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("hud_feed_panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(0)

        header = QLabel("▎ LIVE FEED")
        header.setObjectName("hud_panel_header")
        layout.addWidget(header)

        self.log = QTextEdit(self)
        self.log.setObjectName("hud_feed_log")
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.log, 1)

    def append_log(self, line: str) -> None:
        """Append a line, auto-scroll, colour-code by content."""
        if not line:
            return
        text = line.rstrip("\n")
        if not text.strip():
            return

        # Pick a colour based on content markers
        lower = text.lower()
        if "⚡" in text or "fast-path" in lower:
            color = COLORS["hud_cyan_light"]
        elif "error" in lower or "❌" in text or "failed" in lower:
            color = COLORS["error_light"]
        elif "⏹" in text or "stop" == lower.strip().lstrip("⏹ ").rstrip():
            color = COLORS["error_light"]
        elif "🎬" in text or "easter egg" in lower:
            color = COLORS["accent_secondary"]
        elif "🤖" in text or "jarvis\n" in lower or text.strip().startswith("🤖"):
            color = COLORS["accent_secondary"]
        elif "🧠" in text or "intent" in lower:
            color = COLORS["text_secondary"]
        else:
            color = COLORS["text_primary"]

        # Strip carriage returns & enforce single line per call
        for sub in text.splitlines():
            if not sub.strip():
                continue
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            cursor = self.log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            ts = datetime.now().strftime("%H:%M:%S")
            cursor.insertText(ts + "  ", QTextCharFormat())
            cursor.insertText(sub + "\n", fmt)

        # Cap line count
        doc = self.log.document()
        if doc.blockCount() > self.MAX_LINES:
            cursor = self.log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.KeepAnchor,
                doc.blockCount() - self.MAX_LINES,
            )
            cursor.removeSelectedText()

        # Auto-scroll
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())


# ─── System telemetry panel ────────────────────────────────────────────


class SystemPanel(QFrame):
    """Static-ish telemetry card with mic / model / MCPs / voice rows."""

    def __init__(self, cfg=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("hud_system_panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(0)

        header = QLabel("▎ SYSTEM")
        header.setObjectName("hud_panel_header")
        layout.addWidget(header)

        self._rows: dict[str, QLabel] = {}
        for key, label in (
            ("mic", "● MIC      …"),
            ("model", "● MODEL    …"),
            ("mcps", "● MCPS     …"),
            ("voice", "● VOICE    …"),
        ):
            row = QLabel(label)
            row.setObjectName("hud_telemetry_row")
            layout.addWidget(row)
            self._rows[key] = row
        layout.addStretch(1)

        if cfg is not None:
            self.refresh_from_config(cfg)

    def refresh_from_config(self, cfg) -> None:
        """Populate telemetry rows from the running config."""
        mic_name = getattr(cfg, "voice_device", None) or "default device"
        sr = getattr(cfg, "sample_rate", 16000)
        compute = getattr(cfg, "whisper_compute_type", "int8")
        self._rows["mic"].setText(f"● MIC      {mic_name} · {sr // 1000} kHz · {compute}")

        chat = getattr(cfg, "ollama_chat_model", "—")
        whisper = getattr(cfg, "whisper_model", "—")
        self._rows["model"].setText(f"● MODEL    {chat}  ·  whisper {whisper}")

        mcps = getattr(cfg, "mcps", {}) or {}
        self._rows["mcps"].setText(f"● MCPS     {len(mcps)} connected")

        tts_engine = getattr(cfg, "tts_engine", "—")
        clone = getattr(cfg, "tts_chatterbox_audio_prompt", None)
        voice_desc = tts_engine
        if tts_engine == "chatterbox" and clone:
            voice_desc += " (voice cloned)"
        self._rows["voice"].setText(f"● VOICE    {voice_desc}")


# ─── Control bar ───────────────────────────────────────────────────────


class ControlBar(QFrame):
    """Bottom strip: STOP, MUTE, MENU buttons + weather/city label."""

    stop_clicked = pyqtSignal()
    mute_clicked = pyqtSignal()
    menu_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("hud_control_bar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self.btn_stop = QPushButton("⏹  STOP")
        self.btn_stop.setObjectName("hud_stop")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.btn_stop)

        self.btn_mute = QPushButton("⏸  MUTE MIC")
        self.btn_mute.setObjectName("hud_secondary_btn")
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mute.clicked.connect(self.mute_clicked.emit)
        layout.addWidget(self.btn_mute)

        self.btn_menu = QPushButton("⚙  MENU")
        self.btn_menu.setObjectName("hud_secondary_btn")
        self.btn_menu.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_menu.clicked.connect(self.menu_clicked.emit)
        layout.addWidget(self.btn_menu)

        layout.addStretch(1)

        self.weather_label = QLabel("—°C  ·  IOANNINA")
        self.weather_label.setObjectName("hud_weather")
        layout.addWidget(self.weather_label)

    def set_muted(self, muted: bool) -> None:
        self.btn_mute.setText("🔇  MIC MUTED" if muted else "⏸  MUTE MIC")

    def set_weather(self, text: str) -> None:
        self.weather_label.setText(text)


# ─── Title bar ─────────────────────────────────────────────────────────


class TitleBar(QFrame):
    """Custom title bar with brand text + clock + min/close buttons.

    Provides a drag handle for the frameless window — the parent window
    listens to drag events that this bar emits.
    """

    drag_started = pyqtSignal(QPoint)
    drag_moved = pyqtSignal(QPoint)
    minimize_clicked = pyqtSignal()
    close_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("hud_title_bar")
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 6, 0)
        layout.setSpacing(8)

        self.brand = QLabel("⟨ J A R V I S ⟩")
        self.brand.setObjectName("hud_title_brand")
        layout.addWidget(self.brand)

        layout.addStretch(1)

        self.clock = QLabel("--:-- --")
        self.clock.setObjectName("hud_title_clock")
        layout.addWidget(self.clock)

        layout.addSpacing(8)

        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("hud_title_btn")
        self.btn_min.setFixedSize(28, 24)
        self.btn_min.clicked.connect(self.minimize_clicked.emit)
        layout.addWidget(self.btn_min)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("hud_title_btn_close")
        self.btn_close.setFixedSize(28, 24)
        self.btn_close.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.btn_close)

        self._drag_origin: Optional[QPoint] = None
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    def _update_clock(self) -> None:
        self.clock.setText(datetime.now().strftime("%I:%M %p").lstrip("0"))

    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = e.globalPosition().toPoint()
            self.drag_started.emit(self._drag_origin)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # type: ignore[override]
        if self._drag_origin is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.drag_moved.emit(e.globalPosition().toPoint())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # type: ignore[override]
        self._drag_origin = None
        super().mouseReleaseEvent(e)


# ─── Main HUD window ───────────────────────────────────────────────────


class JarvisHUDWindow(QWidget):
    """Unified Iron Man HUD: title + (face | feed+system) + control bar."""

    def __init__(
        self,
        cfg=None,
        on_menu_clicked=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("hud_root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Apply the project-wide stylesheet locally so our HUD-specific
        # rules (#hud_root, QPushButton#hud_stop, etc.) take effect even
        # when this window is created before any other styled surface.
        self.setStyleSheet(JARVIS_THEME_STYLESHEET)
        self.setWindowTitle("Jarvis HUD")
        self.setMinimumSize(820, 460)
        self.resize(900, 500)

        # Frameless, always-on-top
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self._on_menu_clicked = on_menu_clicked
        self._drag_offset: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Title bar
        self.title = TitleBar(self)
        self.title.drag_started.connect(self._on_drag_start)
        self.title.drag_moved.connect(self._on_drag_move)
        self.title.minimize_clicked.connect(self.showMinimized)
        self.title.close_clicked.connect(self.hide)  # tray manages lifecycle
        outer.addWidget(self.title)

        # Body row: face panel | right column (feed + system)
        body = QHBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(10)

        # Face column
        face_col = QVBoxLayout()
        face_col.setContentsMargins(0, 0, 0, 0)
        face_col.setSpacing(8)
        self.face_panel = FacePanel(self)
        self.face_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        face_col.addWidget(self.face_panel, 1)

        self.state_pill = QLabel("STATE: IDLE")
        self.state_pill.setObjectName("hud_state_pill")
        self.state_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        face_col.addWidget(self.state_pill, 0, Qt.AlignmentFlag.AlignHCenter)

        body.addLayout(face_col, 5)

        # Right column
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(10)
        self.feed_panel = FeedPanel(self)
        right_col.addWidget(self.feed_panel, 3)
        self.system_panel = SystemPanel(cfg=cfg, parent=self)
        right_col.addWidget(self.system_panel, 1)
        body.addLayout(right_col, 4)

        outer.addLayout(body, 1)

        # Control bar
        self.control_bar = ControlBar(self)
        self.control_bar.stop_clicked.connect(self._on_stop_clicked)
        self.control_bar.mute_clicked.connect(self._on_mute_clicked)
        self.control_bar.menu_clicked.connect(self._on_menu_clicked_internal)
        outer.addWidget(self.control_bar)

        # State pill updates from JarvisStateManager
        self._state_manager = get_jarvis_state()
        try:
            self._state_manager.state_changed.connect(self._on_state_changed)
        except Exception:
            pass
        self._on_state_changed(self._state_manager.state)

        # Weather refresh every 15 min (best-effort, non-blocking)
        self._weather_timer = QTimer(self)
        self._weather_timer.timeout.connect(self._refresh_weather)
        self._weather_timer.start(15 * 60 * 1000)
        QTimer.singleShot(2000, self._refresh_weather)

        # Position bottom-right by default
        self._position_default()

        # Track mute state locally so the button label can flip
        self._muted = False

    # ── public API used by app.py ────────────────────────────────────

    def append_log(self, line: str) -> None:
        self.feed_panel.append_log(line)

    # ── internal ─────────────────────────────────────────────────────

    def _position_default(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        x = geom.right() - self.width() - 24
        y = geom.bottom() - self.height() - 60
        self.move(x, y)

    def _on_drag_start(self, global_pos: QPoint) -> None:
        self._drag_offset = global_pos - self.frameGeometry().topLeft()

    def _on_drag_move(self, global_pos: QPoint) -> None:
        if self._drag_offset is not None:
            self.move(global_pos - self._drag_offset)

    def _on_state_changed(self, state) -> None:
        try:
            name = state.value if hasattr(state, "value") else str(state)
        except Exception:
            name = "IDLE"
        self.state_pill.setText(f"STATE: {str(name).upper()}")

    def _on_stop_clicked(self) -> None:
        # Send STOP to the daemon via control bus. Uses the same module
        # whether desktop_app + daemon share a process (bundled) or are
        # separate processes (subprocess mode).
        try:
            from jarvis.control_bus import send_command
            response = send_command("STOP", timeout=2.0)
            self.append_log(f"⏹ STOP sent → {response or 'no reply'}")
        except Exception as e:
            self.append_log(f"⏹ STOP failed: {e}")

    def _on_mute_clicked(self) -> None:
        try:
            from jarvis.control_bus import send_command
            response = send_command("MUTE", timeout=2.0)
            if response and "MUTED=" in response:
                self._muted = response.endswith("True")
                self.control_bar.set_muted(self._muted)
            self.append_log(f"🔇 MUTE → {response or 'no reply'}")
        except Exception as e:
            self.append_log(f"🔇 MUTE failed: {e}")

    def _on_menu_clicked_internal(self) -> None:
        if callable(self._on_menu_clicked):
            try:
                self._on_menu_clicked()
            except Exception as e:
                self.append_log(f"menu callback error: {e}")
        else:
            self.append_log("⚙ Menu: open the tray icon for now")

    def _refresh_weather(self) -> None:
        """Fetch weather via the OpenWeather key in mcps/.env (non-blocking)."""
        import threading

        def worker() -> None:
            try:
                import os as _os
                from pathlib import Path as _Path
                import requests as _requests
                env_path = _Path("C:/Users/aggel/Jarvis/mcps/.env")
                key = _os.environ.get("OPENWEATHER_API_KEY") or ""
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if line.startswith("OPENWEATHER_API_KEY"):
                            key = line.split("=", 1)[1].strip()
                            break
                if not key:
                    return
                r = _requests.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": "Ioannina,GR", "appid": key, "units": "metric", "lang": "en"},
                    timeout=4,
                )
                if r.ok:
                    d = r.json()
                    temp = round(float(d["main"]["temp"]))
                    self.control_bar.set_weather(f"{temp}°C  ·  ΙΩΑΝΝΙΝΑ")
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
