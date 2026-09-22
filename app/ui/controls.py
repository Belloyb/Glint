"""Bottom control bar: transport buttons, time labels, seek bar, volume,
speed and fullscreen controls.

The bar is intentionally "dumb": it emits signals for user actions and
receives state through setters. All wiring to the player happens in the main
window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from app.core.models import PlaybackState
from app.core.playback import SPEED_PRESETS
from app.ui.icons import load_icon
from app.ui.seekbar import SeekBar
from app.ui.volume_slider import VolumeSlider
from app.utils.format import format_time

_BUTTON_SIZE = 38, 32
_TIME_LABEL_MIN_WIDTH = 52
_VOLUME_SLIDER_WIDTH = 96
# Responsive layout: below these widths parts of the bar collapse.
_HIDE_VOLUME_SLIDER_BELOW = 700
_HIDE_TOTAL_TIME_BELOW = 560


class ControlBar(QWidget):
    """Signal-emitting control strip; state is pushed in via setters."""

    playToggled = Signal()
    stopClicked = Signal()
    prevClicked = Signal()
    nextClicked = Signal()
    muteToggled = Signal()
    volumeChanged = Signal(int)  # user moved the volume slider
    seekRequested = Signal(float)  # user released a scrub on the seek bar
    speedSelected = Signal(float)  # user picked a speed preset
    fullscreenToggled = Signal()
    entered = Signal()  # mouse moved onto the bar (fullscreen auto-hide)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlBar")

        self.btn_prev = self._make_button("skip-back", "Previous")
        self.btn_play = self._make_button("play", "Play / Pause")
        self.btn_next = self._make_button("skip-forward", "Next")
        self.btn_stop = self._make_button("stop", "Stop")
        self.btn_mute = self._make_button("volume", "Mute")
        self.btn_fullscreen = self._make_button("fullscreen", "Fullscreen")

        self.lbl_current = self._make_time_label()
        self.lbl_current.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_total = self._make_time_label()
        self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.seekbar = SeekBar()

        # Range, default, tooltip and the amplified-zone painting live in
        # VolumeSlider; the bar only sizes and wires it.
        self.volume_slider = VolumeSlider(self)
        self.volume_slider.setFixedWidth(_VOLUME_SLIDER_WIDTH)

        self.btn_speed = QPushButton("1×")
        self.btn_speed.setObjectName("SpeedButton")
        self.btn_speed.setToolTip("Playback speed")
        self.btn_speed.setAccessibleName("Playback speed")
        self.btn_speed.setCursor(Qt.CursorShape.PointingHandCursor)
        self._speed_menu = self._build_speed_menu()
        self.btn_speed.setMenu(self._speed_menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)
        layout.addWidget(self.btn_prev)
        layout.addWidget(self.btn_play)
        layout.addWidget(self.btn_next)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.lbl_current)
        layout.addWidget(self.seekbar)
        layout.addWidget(self.lbl_total)
        layout.addWidget(self.btn_mute)
        layout.addWidget(self.volume_slider)
        layout.addWidget(self.btn_speed)
        layout.addWidget(self.btn_fullscreen)

        self.btn_play.clicked.connect(self.playToggled)
        self.btn_stop.clicked.connect(self.stopClicked)
        self.btn_prev.clicked.connect(self.prevClicked)
        self.btn_next.clicked.connect(self.nextClicked)
        self.btn_mute.clicked.connect(self.muteToggled)
        self.btn_fullscreen.clicked.connect(self.fullscreenToggled)
        self.volume_slider.valueChanged.connect(self.volumeChanged)
        self.seekbar.seekRequested.connect(self.seekRequested)

    # ---------------------------------------------------------------- builders
    @staticmethod
    def _make_time_label() -> QLabel:
        label = QLabel("--:--")
        label.setObjectName("TimeLabel")
        label.setMinimumWidth(_TIME_LABEL_MIN_WIDTH)
        return label

    @staticmethod
    def _make_button(icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("IconButton")
        button.setIcon(load_icon(icon_name))
        button.setFixedSize(*_BUTTON_SIZE)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_speed_menu(self) -> QMenu:
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for preset in SPEED_PRESETS:
            action = QAction(f"{preset:g}×", menu)
            action.setCheckable(True)
            action.setData(preset)
            if preset == 1.0:
                action.setChecked(True)
            group.addAction(action)
            menu.addAction(action)
        menu.triggered.connect(self._on_speed_menu_triggered)
        return menu

    # -------------------------------------------------------------- interaction
    def _on_speed_menu_triggered(self, action: QAction) -> None:
        value = action.data()
        if value is not None:
            self.speedSelected.emit(float(value))

    def enterEvent(self, event) -> None:  # Qt override
        self.entered.emit()
        super().enterEvent(event)

    def resizeEvent(self, event) -> None:  # Qt override
        super().resizeEvent(event)
        width = self.width()
        self.volume_slider.setVisible(width >= _HIDE_VOLUME_SLIDER_BELOW)
        self.lbl_total.setVisible(width >= _HIDE_TOTAL_TIME_BELOW)

    # ----------------------------------------------------------------- setters
    def set_playback_state(self, state: PlaybackState) -> None:
        """Update the play/pause icon for a playback state."""
        playing = state in (PlaybackState.PLAYING, PlaybackState.LOADING)
        self.btn_play.setIcon(load_icon("pause" if playing else "play"))
        self.btn_play.setAccessibleName("Pause" if playing else "Play")

    def set_position(self, position: float | None) -> None:
        self.lbl_current.setText(format_time(position))
        self.seekbar.set_position(position)

    def set_duration(self, duration: float | None) -> None:
        self.lbl_total.setText(format_time(duration))
        self.seekbar.set_duration(duration)

    def set_volume(self, volume: int) -> None:
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(volume)
        self.volume_slider.blockSignals(False)

    def set_muted(self, muted: bool) -> None:
        self.btn_mute.setIcon(load_icon("volume-muted" if muted else "volume"))

    def set_speed(self, speed: float) -> None:
        """Reflect a speed value on the button and in its menu."""
        self.btn_speed.setText(f"{speed:g}×")
        for action in self._speed_menu.actions():
            value = action.data()
            action.setChecked(value is not None and abs(float(value) - speed) < 1e-9)

    def set_fullscreen_active(self, active: bool) -> None:
        self.btn_fullscreen.setIcon(load_icon("fullscreen-exit" if active else "fullscreen"))
        self.btn_fullscreen.setToolTip("Exit fullscreen" if active else "Fullscreen")
