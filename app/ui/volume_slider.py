"""Volume slider with a VLC-style amplified zone (0–200%).

``QSlider`` subclass: interaction (click, drag, wheel, arrow keys) stays
native and unchanged; only painting and the tooltip are custom, following
the SeekBar precedent (theme-token colours, custom ``paintEvent``).

Painting:

* groove — theme border colour;
* fill up to 100% (unity) — accent colour;
* the amplified zone above unity — warning colour, visually distinct so
  the user can see they are beyond "no amplification";
* handle — always visible, text colour.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSlider, QWidget

from app.core.playback import VOLUME_MAX, VOLUME_UNITY
from app.ui.theme import DARK

_GROOVE_HEIGHT = 4.0
_GROOVE_RADIUS = 2.0
_HANDLE_RADIUS = 5.0


class VolumeSlider(QSlider):
    """0–200% volume slider; the region above 100% is drawn as a warning."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, VOLUME_MAX)
        self.setValue(VOLUME_UNITY)
        # Clicking the groove pages by 10 units = 5% at this range.
        self.setPageStep(10)
        self.setAccessibleName("Volume")
        self._sync_labels()

    def setValue(self, value: int) -> None:
        # Override: keep the tooltip current even when callers block our
        # signals (ControlBar.set_volume does exactly that).
        super().setValue(value)
        self._sync_labels()

    def _sync_labels(self) -> None:
        value = self.value()
        suffix = " (amplified — may distort)" if value > VOLUME_UNITY else ""
        self.setToolTip(f"Volume: {value}%{suffix}")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        width = float(self.width())
        center_y = float(self.height()) / 2.0

        groove = QRectF(0.0, center_y - _GROOVE_HEIGHT / 2, width, _GROOVE_HEIGHT)
        painter.setBrush(QColor(DARK.border))
        painter.drawRoundedRect(groove, _GROOVE_RADIUS, _GROOVE_RADIUS)

        span = self.maximum() - self.minimum()
        fraction = (self.value() - self.minimum()) / span if span > 0 else 0.0
        unity_fraction = (
            VOLUME_UNITY / VOLUME_MAX if self.maximum() >= VOLUME_MAX else 1.0
        )

        if fraction > 0.0:
            fill = QRectF(groove)
            fill.setWidth(max(_GROOVE_HEIGHT, width * min(fraction, unity_fraction)))
            painter.setBrush(QColor(DARK.accent))
            painter.drawRoundedRect(fill, _GROOVE_RADIUS, _GROOVE_RADIUS)
        if fraction > unity_fraction:
            loud = QRectF(groove)
            loud.setLeft(width * unity_fraction)
            loud.setWidth(max(_GROOVE_HEIGHT, width * (fraction - unity_fraction)))
            painter.setBrush(QColor(DARK.warning))
            painter.drawRoundedRect(loud, _GROOVE_RADIUS, _GROOVE_RADIUS)

        painter.setBrush(QColor(DARK.text))
        painter.drawEllipse(
            QPointF(width * fraction, center_y), _HANDLE_RADIUS, _HANDLE_RADIUS
        )
        painter.end()
