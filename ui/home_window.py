"""Blitztext home window.

Opens on tray-icon left-click. Mac-menubar-popup-style:
- Frameless tool window, translucent pale-grey/blue background
- Rounded corners with a softly painted drop shadow
- Click-away or Esc closes it (like a native menubar popup)
- Positioned just above the tray icon's rect

IMPORTANT: no QGraphicsDropShadowEffect — on WA_TranslucentBackground
frameless tool windows on Windows it kills paintEvent invalidation.
The shadow is drawn manually inside paintEvent (concentric rounded
rects with decreasing alpha), same strategy as RecordingOverlay.
"""

import os
import sys

from PyQt6.QtWidgets import (
    QWidget, QApplication, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF, QPoint, QEvent, QSize
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QLinearGradient, QPainterPath,
    QKeyEvent, QIcon, QPixmap,
)


# ---------------------------------------------------------------------------
# Design tokens — muted, MacOS-leaning light palette
# ---------------------------------------------------------------------------

BG_TOP       = QColor(248, 249, 252, 240)   # very pale blue-grey top
BG_BOTTOM    = QColor(235, 238, 243, 240)   # slightly deeper bottom
BORDER       = QColor(210, 214, 220, 120)   # 1px hairline around the card
SHADOW_COLOR = (0, 0, 0)                    # alpha stepped in paintEvent

TEXT       = "#1E2026"
TEXT_STRONG = "#12141A"
MUTED      = "#7A7E86"
FAINT      = "#A6A9B0"
HAIRLINE   = "rgba(30, 32, 38, 14)"
HOTKEY_BG  = "#DBDEE3"
HOTKEY_FG  = "#3B3E44"
QUIT_HOV   = "rgba(230, 66, 66, 0.08)"
ACCENT_OK  = "#34C759"   # Apple green
ACCENT_BUSY = "#F1C14A"  # warm yellow
ACCENT_REC = "#FF5A5F"   # red


# ---------------------------------------------------------------------------
# Mode catalogue
# ---------------------------------------------------------------------------
# Taglines follow the product brief ("Sprache rein. Text raus." etc).
# The LLM system prompts for modes 2 and 3 live in core/llm.py — the
# labels here are descriptive, not derived from that code.

MODES = [
    {"id": 1, "title": "Blitztext",     "subtitle": "Sprache rein. Text raus.",      "icon": "mic"},
    {"id": 2, "title": "Blitztext+",    "subtitle": "Geschrieben sprechen.",         "icon": "mic_plus"},
    {"id": 3, "title": "Blitztext $%&!", "subtitle": "Frust rein. Entspannt raus.",   "icon": "mic_filter"},
]


# ---------------------------------------------------------------------------
# Hotkey formatting:  "ctrl+alt+1"  →  "Strg  Alt  1"
# ---------------------------------------------------------------------------
# Mirrors the Settings-window HotkeyBadge convention (double-space separator,
# German modifier labels). Keeps the two visible hotkey surfaces consistent.

_LABELS = {
    "ctrl": "Strg", "control": "Strg",
    "alt": "Alt", "option": "Alt",
    "shift": "Umsch",
    "meta": "Win", "win": "Win", "cmd": "Cmd",
}


def format_hotkey(spec: str) -> str:
    """Turn ``'ctrl+alt+1'`` into ``'Strg  Alt  1'`` (double-space separated)."""
    if not spec:
        return ""
    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    out = []
    for p in parts:
        if p in _LABELS:
            out.append(_LABELS[p])
        else:
            out.append(p.upper() if len(p) == 1 else p.capitalize())
    return "  ".join(out)


# ---------------------------------------------------------------------------
# Small widgets
# ---------------------------------------------------------------------------


class HotkeyPill(QLabel):
    """Small rounded grey pill that displays a shortcut like "Strg Alt 1"."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)
        self.setMinimumWidth(86)  # fits "Strg  Alt  1"
        f = QFont("Segoe UI", 9, QFont.Weight.Medium)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.2)
        self.setFont(f)
        self.setStyleSheet(
            f"QLabel {{ background-color: {HOTKEY_BG}; color: {HOTKEY_FG}; "
            f"  border-radius: 6px; padding: 0 10px; }}"
        )


class ModeIcon(QLabel):
    """20×20 monochrome line-art icon for a mode row."""

    SIZE = 22

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._kind = kind

    def paintEvent(self, event):  # noqa: D401
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(40, 42, 48), 1.3, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        cx = self.SIZE / 2
        # Microphone capsule
        cap_rect = QRectF(cx - 4.0, 3.0, 8.0, 11.0)
        p.drawRoundedRect(cap_rect, 4, 4)
        # U-arc below
        arc_rect = QRectF(cx - 6.0, 10.5, 12.0, 7.0)
        p.drawArc(arc_rect, -180 * 16, 180 * 16)
        # Stem
        p.drawLine(int(cx), 17, int(cx), 20)

        # Decorator per kind
        if self._kind == "mic_plus":
            # small "+" top-right
            p.drawLine(17, 4, 17, 10)
            p.drawLine(14, 7, 20, 7)
        elif self._kind == "mic_filter":
            # three small horizontal lines (filter/EQ glyph) top-right
            p.drawLine(16, 4, 21, 4)
            p.drawLine(15, 7, 21, 7)
            p.drawLine(17, 10, 21, 10)
        p.end()


class ModeRow(QWidget):
    """One row in the mode list. Not interactive in v1 — informational only."""

    def __init__(self, mode: dict, hotkey_spec: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 8, 18, 8)
        lay.setSpacing(12)

        self._icon = ModeIcon(mode["icon"])
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        title = QLabel(mode["title"])
        tf = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.2)
        title.setFont(tf)
        title.setStyleSheet(f"color: {TEXT_STRONG};")

        subtitle = QLabel(mode["subtitle"])
        sf = QFont("Segoe UI", 9)
        subtitle.setFont(sf)
        subtitle.setStyleSheet(f"color: {MUTED};")

        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        lay.addLayout(text_col, 1)

        self._pill = HotkeyPill(format_hotkey(hotkey_spec))
        lay.addWidget(self._pill, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_hotkey(self, hotkey_spec: str) -> None:
        self._pill.setText(format_hotkey(hotkey_spec))


class StatusDot(QWidget):
    """Small coloured circle (state indicator)."""

    SIZE = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE + 2, self.SIZE + 2)
        self._color = QColor(ACCENT_OK)

    def set_color(self, qcolor: QColor) -> None:
        self._color = qcolor
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._color))
        p.drawEllipse(1, 1, self.SIZE, self.SIZE)
        p.end()


# ---------------------------------------------------------------------------
# HomeWindow
# ---------------------------------------------------------------------------


class HomeWindow(QWidget):
    """Tray-popup home window. Signals drive the host application."""

    open_settings = pyqtSignal()
    quit_app      = pyqtSignal()

    # Outer widget = card + shadow margin (shadow painted inside paintEvent)
    CARD_W      = 340
    CARD_H      = 300
    SHADOW_PAD  = 22
    WIDTH       = CARD_W + 2 * SHADOW_PAD
    HEIGHT      = CARD_H + 2 * SHADOW_PAD

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint  # we draw our own
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        self._build_ui()
        self._status = "idle"
        self.set_state(self._status)

    # -- Public API --------------------------------------------------------

    def set_config(self, config: dict) -> None:
        """Update hotkey pills when settings change."""
        self._config = dict(config)
        self._row1.set_hotkey(self._config.get("hotkey_mode1", "ctrl+alt+1"))
        self._row2.set_hotkey(self._config.get("hotkey_mode2", "ctrl+alt+2"))
        self._row3.set_hotkey(self._config.get("hotkey_mode3", "ctrl+alt+3"))

    def set_state(self, state: str) -> None:
        """State-driven status pill: idle / loading / recording / processing."""
        self._status = state
        if state == "recording":
            self._status_dot.set_color(QColor(ACCENT_REC))
            self._status_label.setText("Aufnahme läuft")
        elif state == "processing":
            self._status_dot.set_color(QColor(ACCENT_BUSY))
            self._status_label.setText("Verarbeitung")
        elif state == "loading":
            self._status_dot.set_color(QColor(ACCENT_BUSY))
            self._status_label.setText("Lädt Modell")
        else:
            self._status_dot.set_color(QColor(ACCENT_OK))
            self._status_label.setText("Bereit")

    def show_near(self, anchor: QRect) -> None:
        """Position the window just above ``anchor`` (e.g. the tray icon rect),
        right-aligned to it, clipped to the primary screen's available area."""
        self.set_config(self._config)
        screen_rect = QApplication.primaryScreen().availableGeometry()
        if anchor is None or anchor.isEmpty():
            # Fallback: bottom-right of the screen, 12 px from edges
            x = screen_rect.right() - self.width() - 12
            y = screen_rect.bottom() - self.height() - 12
        else:
            # Center horizontally over the anchor; but keep inside screen
            x = anchor.center().x() - self.width() // 2
            y = anchor.top() - self.height() + self.SHADOW_PAD
            # If anchor is at the top of the screen (unusual), show below instead
            if y < screen_rect.top():
                y = anchor.bottom() + 4 - self.SHADOW_PAD
        x = max(screen_rect.left() + 4, min(x, screen_rect.right() - self.width() - 4))
        y = max(screen_rect.top() + 4,  min(y, screen_rect.bottom() - self.height() - 4))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    # -- Event handling ----------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def event(self, event):
        # Close on click-away (focus lost to another window)
        if event.type() == QEvent.Type.WindowDeactivate:
            self.hide()
        return super().event(event)

    # -- Painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        # Explicitly blit fully-transparent ARGB into every pixel of the widget
        # BEFORE painting anything. Without this, Windows 11 dark-mode shows
        # its default dark window background through the parts of the widget
        # that lie outside the card (the shadow padding area), producing a
        # black rectangular frame around the grey card. WA_TranslucentBackground
        # alone is unreliable with frameless tool windows on Win11 dark mode.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        card_x = self.SHADOW_PAD
        card_y = self.SHADOW_PAD
        card_rect = QRectF(card_x, card_y, self.CARD_W, self.CARD_H)
        radius = 14.0

        # --- Manually painted soft drop shadow (10 concentric rounded rects) ---
        p.setPen(Qt.PenStyle.NoPen)
        shadow_steps = 10
        max_blur = 18.0
        offset_y = 6
        for i in range(shadow_steps, 0, -1):
            t = i / shadow_steps               # 1 → 0
            grow = max_blur * t
            alpha = int(4 + 18 * (1 - t))      # outer ~4, inner ~22
            p.setBrush(QBrush(QColor(*SHADOW_COLOR, alpha)))
            rr = QRectF(
                card_x - grow,
                card_y - grow + offset_y,
                self.CARD_W + 2 * grow,
                self.CARD_H + 2 * grow,
            )
            p.drawRoundedRect(rr, radius + grow, radius + grow)

        # --- Card background: subtle vertical gradient ---
        grad = QLinearGradient(card_x, card_y, card_x, card_y + self.CARD_H)
        grad.setColorAt(0.0, BG_TOP)
        grad.setColorAt(1.0, BG_BOTTOM)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(card_rect, radius, radius)

        # Hairline border
        pen = QPen(BORDER, 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card_rect.adjusted(0.5, 0.5, -0.5, -0.5),
                          radius - 0.5, radius - 0.5)

        p.end()

    # -- UI composition ----------------------------------------------------

    def _build_ui(self) -> None:
        # Outer layout lives entirely inside the card rect (offset by SHADOW_PAD)
        root = QVBoxLayout(self)
        root.setContentsMargins(
            self.SHADOW_PAD, self.SHADOW_PAD,
            self.SHADOW_PAD, self.SHADOW_PAD,
        )
        root.setSpacing(0)

        card = QFrame(self)
        card.setStyleSheet("QFrame { background: transparent; }")
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 16, 0, 12)
        lay.setSpacing(0)

        # --- Header row: "Blitztext" + ⚙ right-aligned ---
        header = QHBoxLayout()
        header.setContentsMargins(18, 0, 14, 0)
        header.setSpacing(6)

        title = QLabel("Blitztext")
        tf = QFont("Segoe UI", 13, QFont.Weight.DemiBold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.3)
        title.setFont(tf)
        title.setStyleSheet(f"color: {TEXT_STRONG};")
        header.addWidget(title)

        header.addStretch(1)

        gear = QPushButton("⚙")
        gear.setFixedSize(24, 24)
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            f"  color: {MUTED}; font-size: 14px; }}"
            "QPushButton:hover { color: #30333A; }"
        )
        gear.clicked.connect(self._on_gear_clicked)
        header.addWidget(gear)

        lay.addLayout(header)
        lay.addSpacing(8)

        # --- Status row ---
        status_row = QHBoxLayout()
        status_row.setContentsMargins(18, 0, 18, 0)
        status_row.setSpacing(8)
        status_row.addStretch(1)
        self._status_dot = StatusDot()
        self._status_label = QLabel("Bereit")
        sf = QFont("Segoe UI", 9, QFont.Weight.Medium)
        self._status_label.setFont(sf)
        self._status_label.setStyleSheet(f"color: {MUTED};")
        status_row.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self._status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch(1)
        lay.addLayout(status_row)
        lay.addSpacing(10)

        # --- Divider ---
        lay.addWidget(self._hairline())

        # --- Mode rows ---
        self._row1 = ModeRow(MODES[0], self._config.get("hotkey_mode1", "ctrl+alt+1"))
        self._row2 = ModeRow(MODES[1], self._config.get("hotkey_mode2", "ctrl+alt+2"))
        self._row3 = ModeRow(MODES[2], self._config.get("hotkey_mode3", "ctrl+alt+3"))
        lay.addWidget(self._row1)
        lay.addWidget(self._hairline())
        lay.addWidget(self._row2)
        lay.addWidget(self._hairline())
        lay.addWidget(self._row3)

        lay.addStretch(1)

        # --- Footer: Beenden button right-aligned ---
        footer = QHBoxLayout()
        footer.setContentsMargins(18, 6, 14, 0)
        footer.addStretch(1)
        quit_btn = QPushButton("Beenden")
        quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_btn.setFixedHeight(26)
        qf = QFont("Segoe UI", 9, QFont.Weight.Medium)
        quit_btn.setFont(qf)
        quit_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; "
            f"  color: {MUTED}; padding: 0 10px; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {QUIT_HOV}; color: #B03030; }}"
        )
        quit_btn.clicked.connect(self._on_quit_clicked)
        footer.addWidget(quit_btn)
        lay.addLayout(footer)

    # -- helpers -----------------------------------------------------------

    def _hairline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.NoFrame)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {HAIRLINE};")
        return line

    def _on_gear_clicked(self) -> None:
        self.hide()
        self.open_settings.emit()

    def _on_quit_clicked(self) -> None:
        self.hide()
        self.quit_app.emit()
