"""Composition root: builds the application-wide services and the main window.

Keeping wiring in one place (instead of inside widgets) makes the object graph
explicit and testable: the UI smoke test constructs this same class.

Settings flow: ``SettingsService`` loads ``settings.json``; this module applies
it at startup (theme, font, engine options) and re-applies on every change
(live apply — the settings dialog never touches the engine itself).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication

from app import __version__
from app.core.recents import RecentFiles
from app.core.settings import AppSettings
from app.player.controller import PlayerController
from app.player.queue import PlaybackQueue
from app.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme
from app.utils.logging import get_logger, setup_logging
from app.utils.paths import config_dir, log_dir

logger = get_logger("application")


class Application:
    """Owns the services (settings, player, queue, recents) and the window."""

    def __init__(
        self,
        qapp: QApplication,
        mpv_options: Mapping[str, Any] | None = None,
        queue_seed: int | None = None,
        settings_path: Path | None = None,
    ) -> None:
        self._qapp = qapp
        setup_logging(log_dir())

        self._settings = SettingsService(settings_path or config_dir() / "settings.json")
        self._applied_theme = self._settings.settings.interface.theme
        self._applied_scale = self._settings.settings.interface.font_scale
        apply_theme(qapp, self._applied_theme, self._applied_scale)

        self._controller = PlayerController(mpv_options=mpv_options)
        self._queue = PlaybackQueue(self._controller, seed=queue_seed)
        self._recents = RecentFiles(config_dir() / "recents.json")

        self._apply_engine_settings(self._settings.settings)

        self._window = MainWindow(self._controller, self._queue, self._recents, self._settings)
        self._settings.changed.connect(self._on_settings_changed)
        logger.info("Glint %s ready", __version__)

    # ------------------------------------------------------------- properties
    @property
    def window(self) -> MainWindow:
        return self._window

    @property
    def controller(self) -> PlayerController:
        return self._controller

    @property
    def queue(self) -> PlaybackQueue:
        return self._queue

    @property
    def recents(self) -> RecentFiles:
        return self._recents

    @property
    def settings(self) -> SettingsService:
        return self._settings

    def show(self) -> None:
        self._window.show()

    # ------------------------------------------------------------ settings glue
    def _apply_engine_settings(self, settings: AppSettings) -> None:
        """Push settings into the player engine (idempotent, cheap)."""
        controller = self._controller
        controller.autoplay_on_open = settings.playback.autoplay_on_open
        controller.set_volume(settings.playback.default_volume)
        controller.set_speed(settings.playback.default_speed)

        controller.set_subtitle_appearance(
            font=settings.subtitles.font,
            size=settings.subtitles.size,
            color=settings.subtitles.color,
        )
        controller.set_subtitle_delay(settings.subtitles.default_delay)
        controller.set_sub_auto_load_external(settings.subtitles.auto_load_external)

        controller.set_audio_device(settings.audio.output_device)
        controller.set_hardware_decoding(settings.video.hardware_decoding)
        controller.set_deinterlace(settings.video.deinterlace)

    def _on_settings_changed(self, new_settings: AppSettings) -> None:
        previous_theme = getattr(self, "_applied_theme", None)
        previous_scale = getattr(self, "_applied_scale", None)
        theme = new_settings.interface.theme
        scale = new_settings.interface.font_scale
        if theme != previous_theme or scale != previous_scale:
            apply_theme(self._qapp, theme, scale)
        self._applied_theme, self._applied_scale = theme, scale
        self._apply_engine_settings(new_settings)

    # --------------------------------------------------------------- lifecycle
    def shutdown(self) -> None:
        """Release engine resources (video surface must already be released)."""
        logger.info("shutting down")
        self._controller.shutdown()
