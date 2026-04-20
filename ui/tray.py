from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QGuiApplication, QPolygonF
from PyQt6.QtCore import pyqtSignal, QObject, QRectF, QRect, QPointF, Qt

from core.log import log


class TraySignals(QObject):
    open_settings = pyqtSignal()
    quit_app = pyqtSignal()
    # Left-click on the tray icon → open the home popup.
    # QRect payload is the icon's screen rect, used to anchor the window above it.
    open_home = pyqtSignal(QRect)


# ---------------------------------------------------------------------------
# Taskbar-theme detection
# ---------------------------------------------------------------------------

def _taskbar_is_dark() -> bool:
    """Return True if the Windows taskbar uses the dark theme.

    Preferred source: the ``SystemUsesLightTheme`` registry value, which is
    the one Windows itself consults for the taskbar (``AppsUseLightTheme``
    controls app windows and can differ). We fall back to Qt's color-scheme
    hint, and finally default to dark (Windows 11's out-of-box setting).
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return value == 0
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        return True


class SystemTray:
    """Minimal line-art microphone icon. State indicated by line weight and subtle fill.

    Colours adapt to the Windows taskbar theme (light or dark) so the icon
    never disappears into the taskbar. The icon is redrawn automatically when
    the user toggles system theme at runtime.
    """

    # --- Palette per theme ---------------------------------------------------
    # The palette is picked at icon-draw time based on _taskbar_is_dark().
    # Values tuned for good contrast without looking harsh on either taskbar.
    _PALETTE = {
        "dark": {       # dark taskbar → light-ish icon
            "idle":       QColor(220, 220, 220),
            "active":     QColor(255, 255, 255),
            "recording":  QColor(255, 255, 255),
        },
        "light": {      # light taskbar → dark icon
            "idle":       QColor(90, 90, 90),
            "active":     QColor(10, 10, 10),
            "recording":  QColor(10, 10, 10),
        },
    }

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
        # Live-update the icon if the user toggles Windows theme (light ↔ dark)
        # while the app is running.
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_theme_changed)
        except Exception as e:
            log(f"colorSchemeChanged connect failed: {type(e).__name__}: {e}")
        self._tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger = single left click; DoubleClick for users with the Windows
        # "double-click to open" setting. Context (right-click) is handled by Qt.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.signals.open_home.emit(self._tray.geometry())

    def _on_theme_changed(self, *_args) -> None:
        """Windows theme toggled — repaint the current-state icon."""
        log(f"taskbar theme changed (dark={_taskbar_is_dark()}); redrawing tray icon")
        self._set_icon(self._state)

    def _create_mic_icon(self, state: str) -> QIcon:
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))

        palette = self._PALETTE["dark" if _taskbar_is_dark() else "light"]

        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # "speaking" gets a visually distinct speaker glyph — v1.0.19's tray
        # reused the filled mic for both "recording" and "speaking", which
        # made the two states indistinguishable at a glance.
        if state == "speaking":
            self._draw_speaker_glyph(p, size, palette["recording"])
            p.end()
            return QIcon(pixmap)

        if state == "recording":
            stroke_color = palette["recording"]
            fill_color = palette["recording"]
            stroke_w = 4.0
        elif state == "processing":
            stroke_color = palette["active"]
            fill_color = None
            stroke_w = 4.0
        else:
            stroke_color = palette["idle"]
            fill_color = None
            stroke_w = 3.4  # slightly beefier outline so it reads at 16 px

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

    @staticmethod
    def _draw_speaker_glyph(p: QPainter, size: int, color: QColor) -> None:
        """Filled speaker cone + three sound waves. Same visual weight as the
        mic icon so state switches don't feel jumpy in the tray."""
        cx = size / 2
        cy = size / 2

        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)

        # Speaker body (small rectangle)
        body = QRectF(cx - 18, cy - 7, 9, 14)
        p.drawRect(body)

        # Cone (trapezoid)
        horn = QPolygonF([
            QPointF(cx - 9, cy - 7),
            QPointF(cx - 1, cy - 16),
            QPointF(cx - 1, cy + 16),
            QPointF(cx - 9, cy + 7),
        ])
        p.drawPolygon(horn)

        # Three sound waves on the right
        pen = QPen(color, 3.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r in (7, 13, 19):
            arc = QRectF(cx + 2 - r, cy - r, r * 2, r * 2)
            p.drawArc(arc, -45 * 16, 90 * 16)

    def _set_icon(self, state: str) -> None:
        icon = self._create_mic_icon(state)
        self._tray.setIcon(icon)
        labels = {
            "idle": "Blitztext",
            "recording": "Blitztext – Aufnahme",
            "processing": "Blitztext – Verarbeitung",
            "speaking": "Blitztext – Liest vor",
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
