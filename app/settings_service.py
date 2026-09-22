"""Qt-facing settings service (thin wrapper over the core store).

Holds the current :class:`app.core.settings.AppSettings`, persists them, and
emits :attr:`changed` so the composition root can re-apply engine/UI options.
All mutation flows through :meth:`apply` — one place, one signal.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.core.settings import AppSettings, SettingsStore
from app.utils.logging import get_logger

logger = get_logger("settings_service")


class SettingsService(QObject):
    """Owns the settings tree; persistence + change notification."""

    changed = Signal(object)  # AppSettings (the new value)

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = SettingsStore(path)
        self._settings = self._store.load()
        logger.info("settings loaded from %s (theme=%s)", path, self._settings.interface.theme)

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def path(self) -> Path:
        return self._store.path

    def apply(self, new_settings: AppSettings) -> None:
        """Adopt ``new_settings``, persist them and notify listeners.

        Persistence failures are logged but never raised — the in-memory
        settings still apply for this session.
        """
        if new_settings == self._settings:
            return
        self._settings = new_settings
        try:
            self._store.save(new_settings)
        except OSError:
            logger.warning("could not persist settings to %s", self._store.path, exc_info=True)
        self.changed.emit(new_settings)

    def reset_to_defaults(self) -> None:
        self.apply(AppSettings())
