from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from PyQt6.QtCore import pyqtSignal, QObject, QRectF, QRect, Qt


class TraySignals(QObject):
    open_settings = pyqtSignal()
    quit_app = pyqtSignal()
    # Left-click on the tray icon → open the home popup.
    # QRect payload is the icon's screen rect, used to anchor the window above it.
    open_home = pyqtSignal(QRect)


class SystemTray:
    """Minimal line-art microphone icon. State indicated by line weight and subtle fill."""

    # Monochrome greys — single accent for recording
    C_IDLE = QColor(110, 110, 110)
    C_ACTIVE = QColor(10, 10, 10)
    C_RECORDING = QColor(10, 10, 10)  # solid black when recording

    def __init__(self, app: QApplication):
        self.signals = TraySignals()
        self._app = app
        self._tray = QSystemTrayIcon()
        self._state = "idle"

        self._set_icon("idle")
        self._build_menu()
        # Route every icon activation: left-click → home popup, right-click
        # keeps falling through to the built-in QMenu context-menu behaviour.
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger = single left click; DoubleClick for users with the Windows
        # "double-click to open" setting. Context (right-click) is handled by Qt.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.signals.open_home.emit(self._tray.geometry())

    def _create_mic_icon(self, state: str) -> QIcon:
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))

        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if state == "recording":
            stroke_color = self.C_RECORDING
            fill_color = self.C_RECORDING
            stroke_w = 4.0
        elif state == "processing":
            stroke_color = self.C_ACTIVE
            fill_color = None
            stroke_w = 4.0
        else:
            stroke_color = self.C_IDLE
            fill_color = None
            stroke_w = 3.2

        cx = size / 2

        # --- Microphone capsule (filled when recording, outlined otherwise) ---
        cap_w, cap_h = 22, 32
        cap_x = cx - cap_w / 2
        cap_y = 8
        cap_rect = QRectF(cap_x, cap_y, cap_w, cap_h)

        if fill_color:
            p.setBrush(QBrush(fill_color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(cap_rect, cap_w / 2, cap_w / 2)
        else:
            pen = QPen(stroke_color, stroke_w, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(cap_rect, cap_w / 2, cap_w / 2)

        # --- U-shaped arc below the capsule ---
        pen = QPen(stroke_color, stroke_w, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc_rect = QRectF(cx - 16, cap_y + cap_h - 10, 32, 22)
        p.drawArc(arc_rect, -180 * 16, 180 * 16)

        # --- Vertical stem ---
        stem_top = cap_y + cap_h + 12
        stem_bottom = size - 8
        p.drawLine(int(cx), int(stem_top), int(cx), int(stem_bottom))

        p.end()
        return QIcon(pixmap)

    def _set_icon(self, state: str) -> None:
        icon = self._create_mic_icon(state)
        self._tray.setIcon(icon)
        labels = {
            "idle": "Blitztext",
            "recording": "Blitztext – Aufnahme",
            "processing": "Blitztext – Verarbeitung",
        }
        self._tray.setToolTip(labels.get(state, "Blitztext"))

    def _build_menu(self) -> None:
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background-color: #FFFFFF; border: 1px solid #ECECEC; "
            "  border-radius: 8px; padding: 6px; font-family: 'Segoe UI'; font-size: 13px; }"
            "QMenu::item { padding: 8px 24px 8px 16px; border-radius: 4px; color: #0A0A0A; }"
            "QMenu::item:selected { background-color: #F5F5F5; }"
            "QMenu::separator { height: 1px; background: #ECECEC; margin: 6px 4px; }"
        )

        settings_action = menu.addAction("Einstellungen")
        settings_action.triggered.connect(self.signals.open_settings.emit)

        menu.addSeparator()

        quit_action = menu.addAction("Beenden")
        quit_action.triggered.connect(self.signals.quit_app.emit)

        self._tray.setContextMenu(menu)

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self._set_icon(state)

    def show_message(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
