import math
import random
import time

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QTimer, QRectF, QRect
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QFont, QLinearGradient, QPen,
    QPainterPath, QRegion,
)


class RecordingOverlay(QWidget):
    """Minimal pill-shaped overlay: smoothly animated audio bars + timer.

    The widget rectangle is EXACTLY the pill size (no outer shadow padding),
    and a QRegion mask carved from a rounded-rect QPainterPath constrains
    the OS-level window shape so only the pill outline reaches the screen.
    Previous versions padded the widget for a soft painted shadow, but on
    some Windows 11 setups the padding area stayed opaque white/grey
    despite WA_TranslucentBackground — producing a visible frame around
    the pill. Shape-masking the window side-steps the translucent-backing
    issue entirely.
    """

    # --- Layout ---
    # Pill = widget. No padding, no painted shadow.
    PILL_W = 84
    PILL_H = 20
    WIDTH = PILL_W
    HEIGHT = PILL_H

    BAR_COUNT = 4
    BAR_WIDTH = 1.4
    BAR_GAP = 3
    BAR_MIN_H = 2
    BAR_MAX_H = 10
    PADDING_X = 10

    # --- Animation ---
    FRAME_MS = 16            # ~60 fps
    TARGET_REFRESH_MS = 130  # how often new target heights are picked
    EASE_FACTOR = 0.22       # higher = snappier, lower = smoother

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self._apply_shape_mask()

        self._start_time = 0.0
        self._current = [0.35] * self.BAR_COUNT
        self._target = [0.35] * self.BAR_COUNT
        self._phases = [random.random() * math.pi * 2 for _ in range(self.BAR_COUNT)]

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(self.FRAME_MS)
        self._frame_timer.timeout.connect(self._tick)

        self._target_timer = QTimer(self)
        self._target_timer.setInterval(self.TARGET_REFRESH_MS)
        self._target_timer.timeout.connect(self._pick_new_targets)

    # --- Lifecycle ---

    def _apply_shape_mask(self) -> None:
        """Clip the window to the pill outline at the OS compositor level.

        QRegion doesn't antialias, but for a pill with very short straight
        sections and full-half-circle ends the rasterised polygon is
        visually indistinguishable from the painted antialiased fill.
        """
        radius = self.PILL_H / 2
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.WIDTH), float(self.HEIGHT), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def show_overlay(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + screen.height() - self.height() - 54
        self.move(x, y)

        self._start_time = time.time()
        self._current = [0.35] * self.BAR_COUNT
        self._target = [0.35] * self.BAR_COUNT
        self._phases = [random.random() * math.pi * 2 for _ in range(self.BAR_COUNT)]

        self.show()
        self.raise_()
        self._frame_timer.start()
        self._target_timer.start()

    def hide_overlay(self) -> None:
        self._frame_timer.stop()
        self._target_timer.stop()
        self.hide()

    # --- Animation logic ---

    def _pick_new_targets(self) -> None:
        for i in range(self.BAR_COUNT):
            # Natural-feeling distribution: occasional tall peaks, mostly mid-height
            base = 0.3 + random.random() * 0.55
            spike = random.random() > 0.75
            self._target[i] = min(1.0, base + (0.25 if spike else 0.0))

    def _tick(self) -> None:
        for i in range(self.BAR_COUNT):
            self._phases[i] += 0.12
            breath = 0.04 * math.sin(self._phases[i])
            target = max(0.18, min(1.0, self._target[i] + breath))
            self._current[i] += (target - self._current[i]) * self.EASE_FACTOR
        self.update()

    # --- Painting ---

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pill_rect = QRectF(0, 0, self.PILL_W, self.PILL_H)
        radius = self.PILL_H / 2

        # Subtle top-to-bottom gradient — deep near-black, lightly translucent
        grad = QLinearGradient(0, 0, 0, self.PILL_H)
        grad.setColorAt(0.0, QColor(28, 28, 30, 230))
        grad.setColorAt(1.0, QColor(14, 14, 16, 230))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill_rect, radius, radius)

        # Hairline highlight at the very top (glass edge)
        pen = QPen(QColor(255, 255, 255, 22), 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill_rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

        # --- Animated bars ---
        bar_color = QColor(240, 240, 244)
        p.setBrush(QBrush(bar_color))
        p.setPen(Qt.PenStyle.NoPen)

        cy = self.PILL_H / 2
        x = self.PADDING_X

        for h_frac in self._current:
            bar_h = self.BAR_MIN_H + h_frac * (self.BAR_MAX_H - self.BAR_MIN_H)
            y = cy - bar_h / 2
            p.drawRoundedRect(
                QRectF(x, y, self.BAR_WIDTH, bar_h),
                self.BAR_WIDTH / 2, self.BAR_WIDTH / 2,
            )
            x += self.BAR_WIDTH + self.BAR_GAP

        # --- Time text ---
        elapsed = time.time() - self._start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_text = f"{minutes}:{seconds:02d}"

        p.setPen(QColor(220, 220, 224))
        font = QFont("Segoe UI", 9, QFont.Weight.Medium)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        p.setFont(font)
        text_left = x + 6
        text_right = self.PILL_W - self.PADDING_X
        text_rect = QRectF(text_left, 0, text_right - text_left, self.PILL_H)
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            time_text,
        )

        p.end()
