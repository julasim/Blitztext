import math
import random
import time

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QFont, QLinearGradient, QPen


class RecordingOverlay(QWidget):
    """Minimal pill-shaped overlay: smoothly animated audio bars + timer.

    The bar values ease toward a rolling target, giving a soft, premium feel.
    """

    # --- Layout ---
    # Pill dimensions (the visible black capsule)
    PILL_W = 116
    PILL_H = 30
    # Outer widget adds margin so we can paint a soft shadow around the pill
    # without relying on QGraphicsDropShadowEffect, which breaks repaint
    # invalidation on WA_TranslucentBackground top-level windows (Qt/Windows).
    SHADOW_PAD_X = 18
    SHADOW_PAD_TOP = 10
    SHADOW_PAD_BOTTOM = 22  # extra to accommodate the 4px downward offset
    WIDTH = PILL_W + 2 * SHADOW_PAD_X
    HEIGHT = PILL_H + SHADOW_PAD_TOP + SHADOW_PAD_BOTTOM

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

        # Pill rect, offset inside the padded widget
        pill_x = self.SHADOW_PAD_X
        pill_y = self.SHADOW_PAD_TOP
        pill_rect = QRectF(pill_x, pill_y, self.PILL_W, self.PILL_H)
        radius = self.PILL_H / 2  # full pill

        # --- Soft drop shadow (manual — 8 concentric rounded rects with
        # decreasing alpha to emulate a ~36px blur, offset 4px down) ---
        p.setPen(Qt.PenStyle.NoPen)
        shadow_steps = 8
        shadow_offset_y = 4
        max_blur = 10.0  # how far the shadow extends outward from the pill
        for i in range(shadow_steps, 0, -1):
            t = i / shadow_steps  # 1 (outermost) → 0
            grow = max_blur * t
            alpha = int(10 + 22 * (1 - t))  # outer ring ~10, inner ring ~32
            p.setBrush(QBrush(QColor(0, 0, 0, alpha)))
            shadow_rect = QRectF(
                pill_x - grow,
                pill_y - grow + shadow_offset_y,
                self.PILL_W + 2 * grow,
                self.PILL_H + 2 * grow,
            )
            r = radius + grow
            p.drawRoundedRect(shadow_rect, r, r)

        # Subtle top-to-bottom gradient — deep near-black
        grad = QLinearGradient(pill_x, pill_y, pill_x, pill_y + self.PILL_H)
        grad.setColorAt(0.0, QColor(28, 28, 30, 240))
        grad.setColorAt(1.0, QColor(14, 14, 16, 240))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill_rect, radius, radius)

        # Hairline highlight at the very top (glass edge)
        pen = QPen(QColor(255, 255, 255, 18), 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill_rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

        # --- Animated bars ---
        bar_color = QColor(240, 240, 244)
        p.setBrush(QBrush(bar_color))
        p.setPen(Qt.PenStyle.NoPen)

        cy = pill_y + self.PILL_H / 2
        x = pill_x + self.PADDING_X

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
        text_right = pill_x + self.PILL_W - self.PADDING_X
        text_rect = QRectF(text_left, pill_y, text_right - text_left, self.PILL_H)
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            time_text,
        )

        p.end()
