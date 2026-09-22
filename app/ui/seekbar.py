"""Custom-painted seek bar with hover preview and scrubbing.

Deliberately hand-painted (not a QSlider): a media scrubber needs a thin
groove, a fill that tracks the engine position, a handle that only appears on
interaction, and a floating time preview — all cheap to draw exactly once per
repaint with no per-frame allocation.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.theme import DARK
from app.utils.format import format_time

_GROOVE_HEIGHT = 4.0
_GROOVE_RADIUS = 2.0
_HANDLE_RADIUS = 5.5
_HINT_GAP = 14.0
_HINT_PADDING_H = 6.0
_HINT_PADDING_V = 3.0


class SeekBar(QWidget):
    """Progress bar for the current media.

    Emits :attr:`seekRequested` (absolute seconds) when the user releases a
    scrub. While dragging, only the preview moves — the engine is left alone
    until release.
    """

    seekRequested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._position = 0.0
        self._hovering = False
        self._dragging = False
        self._drag_fraction = 0.0
        self._hover_fraction = 0.0

        self.setMouseTracking(True)
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Seek bar")
        self.setToolTip("Seek")

    # ------------------------------------------------------------- public API
    def set_duration(self, duration: float | None) -> None:
        if duration is not None and duration > 0:
            self._duration = float(duration)
        else:
            self._duration = 0.0
        self.setEnabled(self._duration > 0)
        self.update()

    def set_position(self, position: float | None) -> None:
        if self._dragging:
            return  # never fight the user's scrub
        self._position = max(0.0, float(position or 0.0))
        self.update()

    # ------------------------------------------------------------ interaction
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            self._dragging = True
            self._drag_fraction = self._fraction_at(event.position().x())
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._drag_fraction = self._fraction_at(event.position().x())
        elif self._duration > 0:
            self._hovering = True
            self._hover_fraction = self._fraction_at(event.position().x())
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._drag_fraction = self._fraction_at(event.position().x())
            self.update()
            self.seekRequested.emit(self._drag_fraction * self._duration)

    def leaveEvent(self, event) -> None:
        self._hovering = False
        self.update()

    def _fraction_at(self, x: float) -> float:
        usable = max(1.0, float(self.width()))
        return min(1.0, max(0.0, x / usable))

    # ---------------------------------------------------------------- painting
    def _display_fraction(self) -> float:
        if self._dragging:
            return self._drag_fraction
        if self._duration <= 0:
            return 0.0
        return min(1.0, self._position / self._duration)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = float(self.width())
        center_y = float(self.height()) / 2.0

        painter.setPen(Qt.PenStyle.NoPen)

        groove = QRectF(0.0, center_y - _GROOVE_HEIGHT / 2, width, _GROOVE_HEIGHT)
        painter.setBrush(QColor(DARK.border))
        painter.drawRoundedRect(groove, _GROOVE_RADIUS, _GROOVE_RADIUS)

        fraction = self._display_fraction()
        if self._duration > 0 and fraction > 0.0:
            fill = QRectF(groove)
            fill.setWidth(max(_GROOVE_HEIGHT, width * fraction))
            painter.setBrush(QColor(DARK.accent))
            painter.drawRoundedRect(fill, _GROOVE_RADIUS, _GROOVE_RADIUS)

        if (self._dragging or self._hovering) and self._duration > 0:
            if self._dragging:
                handle_x = width * self._drag_fraction
                painter.setBrush(QColor(DARK.text))
                painter.drawEllipse(QPointF(handle_x, center_y), _HANDLE_RADIUS, _HANDLE_RADIUS)
            else:
                handle_x = width * self._hover_fraction
            self._draw_time_hint(painter, handle_x)

        painter.end()

    def _draw_time_hint(self, painter: QPainter, x: float) -> None:
        fraction = self._drag_fraction if self._dragging else self._hover_fraction
        text = format_time(fraction * self._duration)

        font = QFont(self.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text) + 2 * _HINT_PADDING_H
        text_height = metrics.height() + 2 * _HINT_PADDING_V

        center_x = min(max(x, text_width / 2), float(self.width()) - text_width / 2)
        top = max(0.0, float(self.height()) / 2 - _HINT_GAP - text_height)
        rect = QRectF(center_x - text_width / 2, top, text_width, text_height)

        painter.setBrush(QColor(DARK.surface_alt))
        painter.drawRoundedRect(rect, 4.0, 4.0)
        painter.setPen(QColor(DARK.text))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(Qt.PenStyle.NoPen)
