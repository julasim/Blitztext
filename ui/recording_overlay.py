import math
import random
import time

from PyQt6.QtWidgets import QWidget, QApplication, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QFont, QLinearGradient


class RecordingOverlay(QWidget):
    """Minimal pill-shaped overlay: smoothly animated audio bars + timer.

    The bar values ease toward a rolling target, giving a soft, premium feel.
    """

    # --- Layout ---
    WIDTH = 116
    HEIGHT = 30
    BAR_COUNT = 5
    BAR_WIDTH = 2.0
    BAR_GAP = 4
    BAR_MIN_H = 4
    BAR_MAX_H = 16
    PADDING_X = 14

    # --- Animation ---
    FRAME_MS = 16            # ~60 fps
    TARGET_REFRESH_MS = 130  # how often new target heights are picked
    EASE_FACTOR = 0.22       # higher = snappier, lower = smoother

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        # Soft drop shadow for a floating, premium feel
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 100))
        self.setGraphicsEffect(shadow)

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
        # Ease each bar toward its target; add a tiny sine-wave breath per bar
        t = time.time()
        for i in range(self.BAR_COUNT):
            self._phases[i] += 0.12
            breath = 0.04 * math.sin(self._phases[i])
            target = max(0.18, min(1.0, self._target[i] + breath))
            self._current[i] += (target - self._current[i]) * self.EASE_FACTOR
        self.update()

    # --- Painting ---

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2  # full pill

        # Subtle top-to-bottom gradient — deep near-black
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(28, 28, 30, 240))
        grad.setColorAt(1.0, QColor(14, 14, 16, 240))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)

        # Hairline highlight at the very top (glass edge)
        from PyQt6.QtGui import QPen
        pen = QPen(QColor(255, 255, 255, 18), 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

        # --- Animated bars ---
        bar_color = QColor(240, 240, 244)
        p.setBrush(QBrush(bar_color))
        p.setPen(Qt.PenStyle.NoPen)

        cy = self.height() / 2
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
        font = QFont("Segoe UI", 10, QFont.Weight.Medium)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        p.setFont(font)
        text_left = x + 8
        text_rect = QRectF(text_left, 0, self.width() - text_left - self.PADDING_X, self.height())
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            time_text,
        )

        p.end()
