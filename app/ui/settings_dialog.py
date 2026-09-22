"""Settings dialog: category pages, live apply, reset to defaults.

Every change applies immediately through :class:`app.settings_service.
SettingsService` (which persists and notifies the composition root — the
dialog never touches the engine itself). A ``_loading`` guard keeps the
initial population from re-triggering applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.playback import SPEED_PRESETS
from app.core.settings import (
    AppSettings,
    AudioSettings,
    InterfaceSettings,
    PlaybackSettings,
    SubtitleSettings,
    VideoSettings,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as QtWidget

    from app.player.controller import PlayerController
    from app.settings_service import SettingsService

_THEME_LABELS = {"dark": "Dark", "light": "Light"}
_SCALE_LABELS = {"small": "Small", "normal": "Normal", "large": "Large"}


class SettingsDialog(QDialog):
    """Live-applying settings dialog with category pages."""

    def __init__(
        self,
        service: SettingsService,
        controller: PlayerController,
        parent: QtWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._controller = controller
        self._loading = True
        self._current_color = "#FFFFFF"

        self.setWindowTitle("Settings")
        self.setMinimumSize(640, 480)
        self.setSizeGripEnabled(True)

        self._categories = QListWidget()
        self._categories.setFixedWidth(150)
        self._categories.setCurrentRow(0)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._wrap(self._build_playback_page()))
        self._pages.addWidget(self._wrap(self._build_interface_page()))
        self._pages.addWidget(self._wrap(self._build_subtitles_page()))
        self._pages.addWidget(self._wrap(self._build_audio_page()))
        self._pages.addWidget(self._wrap(self._build_video_page()))
        for label in ("Playback", "Interface", "Subtitles", "Audio", "Video"):
            self._categories.addItem(label)
        self._categories.currentRowChanged.connect(self._pages.setCurrentIndex)

        reset_button = QPushButton("Reset to Defaults")
        reset_button.clicked.connect(self._reset)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addWidget(reset_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        body = QHBoxLayout()
        body.addWidget(self._categories)
        body.addWidget(self._pages, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)

        self._populate()
        self._loading = False

    # --------------------------------------------------------------- builders
    @staticmethod
    def _wrap(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_playback_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(8, 8, 8, 8)

        volume_row = QWidget()
        volume_layout = QHBoxLayout(volume_row)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_label = QLabel("100%")
        self._volume_slider.valueChanged.connect(
            lambda value: self._volume_label.setText(f"{value}%")
        )
        volume_layout.addWidget(self._volume_slider, 1)
        volume_layout.addWidget(self._volume_label)
        self._volume_slider.valueChanged.connect(self._apply)
        form.addRow("Default volume", volume_row)

        self._speed_combo = QComboBox()
        for preset in SPEED_PRESETS:
            self._speed_combo.addItem(f"{preset:g}×", preset)
        self._speed_combo.currentIndexChanged.connect(self._apply)
        form.addRow("Default speed", self._speed_combo)

        self._autoplay_check = QCheckBox("Start playback automatically when a file is opened")
        self._autoplay_check.toggled.connect(self._apply)
        form.addRow("", self._autoplay_check)
        return page

    def _build_interface_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(8, 8, 8, 8)

        self._theme_combo = QComboBox()
        for name, label in _THEME_LABELS.items():
            self._theme_combo.addItem(label, name)
        self._theme_combo.currentIndexChanged.connect(self._apply)
        form.addRow("Theme", self._theme_combo)

        self._font_scale_combo = QComboBox()
        for name, label in _SCALE_LABELS.items():
            self._font_scale_combo.addItem(label, name)
        self._font_scale_combo.currentIndexChanged.connect(self._apply)
        form.addRow("Interface size", self._font_scale_combo)

        self._playlist_check = QCheckBox("Show playlist when the application starts")
        self._playlist_check.toggled.connect(self._apply)
        form.addRow("", self._playlist_check)
        return page

    def _build_subtitles_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(8, 8, 8, 8)

        self._font_combo = QFontComboBox()
        self._font_combo.currentFontChanged.connect(self._apply)
        form.addRow("Font", self._font_combo)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(5, 200)
        self._size_spin.valueChanged.connect(self._apply)
        form.addRow("Size", self._size_spin)

        self._color_button = QPushButton()
        self._color_button.setToolTip("Subtitle color")
        self._color_button.clicked.connect(self._pick_color)
        form.addRow("Color", self._color_button)

        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(-3600.0, 3600.0)
        self._delay_spin.setSingleStep(0.1)
        self._delay_spin.setDecimals(1)
        self._delay_spin.setSuffix(" s")
        self._delay_spin.valueChanged.connect(self._apply)
        form.addRow("Default delay", self._delay_spin)

        self._autoload_check = QCheckBox("Automatically load subtitle files found next to the video")
        self._autoload_check.toggled.connect(self._apply)
        form.addRow("", self._autoload_check)
        return page

    def _build_audio_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(8, 8, 8, 8)

        self._device_combo = QComboBox()
        self._device_combo.currentIndexChanged.connect(self._apply)
        form.addRow("Output device", self._device_combo)
        return page

    def _build_video_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(8, 8, 8, 8)

        self._hwdec_check = QCheckBox("Use hardware decoding when available")
        self._hwdec_check.toggled.connect(self._apply)
        form.addRow("", self._hwdec_check)

        self._deinterlace_check = QCheckBox("Deinterlace video (applies to interlaced content)")
        self._deinterlace_check.toggled.connect(self._apply)
        form.addRow("", self._deinterlace_check)
        return page

    # ------------------------------------------------------------- population
    def _populate(self) -> None:
        settings = self._service.settings
        playback = settings.playback
        interface = settings.interface
        subtitles = settings.subtitles
        audio = settings.audio
        video = settings.video

        self._volume_slider.setValue(playback.default_volume)
        index = self._speed_combo.findData(playback.default_speed)
        self._speed_combo.setCurrentIndex(index if index >= 0 else SPEED_PRESETS.index(1.0))
        self._autoplay_check.setChecked(playback.autoplay_on_open)

        self._theme_combo.setCurrentIndex(
            max(0, list(_THEME_LABELS).index(interface.theme))
        )
        self._font_scale_combo.setCurrentIndex(
            max(0, list(_SCALE_LABELS).index(interface.font_scale))
        )
        self._playlist_check.setChecked(interface.show_playlist_at_start)

        self._font_combo.setCurrentFont(QFont(subtitles.font))
        self._size_spin.setValue(round(subtitles.size))
        self._delay_spin.setValue(subtitles.default_delay)
        self._autoload_check.setChecked(subtitles.auto_load_external)
        self._update_color_button(subtitles.color)

        self._populate_devices(audio.output_device)

        self._hwdec_check.setChecked(video.hardware_decoding)
        self._deinterlace_check.setChecked(video.deinterlace)

    def _populate_devices(self, current: str) -> None:
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        for device_id, description in self._controller.audio_devices():
            self._device_combo.addItem(description, device_id)
        index = self._device_combo.findData(current)
        if index < 0:
            self._device_combo.insertItem(0, f"{current} (unavailable)", current)
            index = 0
        self._device_combo.setCurrentIndex(index)
        self._device_combo.blockSignals(False)

    def _update_color_button(self, color: str) -> None:
        rgb = color.lstrip("#")[:6]
        self._current_color = color.upper()
        self._color_button.setText(f"  {self._current_color}  ")
        self._color_button.setStyleSheet(
            f"background: #{rgb}; color: {'#000000' if _is_light(rgb) else '#ffffff'};"
            "border: 1px solid #888; border-radius: 4px; padding: 6px;"
        )

    # ------------------------------------------------------------- applying
    def _pick_color(self) -> None:
        current = QColor(self._service.settings.subtitles.color)
        color = QColorDialog.getColor(current, self, "Subtitle color")
        if color.isValid():
            self._update_color_button(color.name())
            self._apply()

    def _apply(self, *_args) -> None:
        if self._loading:
            return
        speed = self._speed_combo.currentData()
        self._service.apply(
            AppSettings(
                playback=PlaybackSettings(
                    default_volume=self._volume_slider.value(),
                    default_speed=float(speed) if speed else 1.0,
                    autoplay_on_open=self._autoplay_check.isChecked(),
                ),
                interface=InterfaceSettings(
                    theme=self._theme_combo.currentData(),
                    show_playlist_at_start=self._playlist_check.isChecked(),
                    font_scale=self._font_scale_combo.currentData(),
                ),
                subtitles=SubtitleSettings(
                    font=self._font_combo.currentFont().family(),
                    size=float(self._size_spin.value()),
                    color=self._current_color,
                    default_delay=self._delay_spin.value(),
                    auto_load_external=self._autoload_check.isChecked(),
                ),
                audio=AudioSettings(
                    output_device=self._device_combo.currentData() or "auto",
                ),
                video=VideoSettings(
                    hardware_decoding=self._hwdec_check.isChecked(),
                    deinterlace=self._deinterlace_check.isChecked(),
                ),
            )
        )

    def _reset(self) -> None:
        self._loading = True
        self._service.reset_to_defaults()
        self._populate()
        self._loading = False


def _is_light(rgb_hex: str) -> bool:
    try:
        red, green, blue = int(rgb_hex[0:2], 16), int(rgb_hex[2:4], 16), int(rgb_hex[4:6], 16)
    except ValueError:
        return False
    return (red * 299 + green * 587 + blue * 114) / 1000 > 150
