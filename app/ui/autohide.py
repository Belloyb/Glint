"""Auto-hide behaviour for fullscreen chrome (controls, cursor).

The controller is deliberately dumb: it owns a countdown and emits
``shown``/``hidden`` transitions; the main window decides *what* chrome means.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

_MIN_INTERVAL_MS = 100
_DEFAULT_INTERVAL_MS = 2500


class AutoHideController(QObject):
    """Reveals chrome on activity and hides it again after an idle interval."""

    shown = Signal()
    hidden = Signal()

    def __init__(self, interval_ms: int = _DEFAULT_INTERVAL_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self.set_interval(interval_ms)
        self._active = False
        self._is_hidden = False

    # ------------------------------------------------------------------ API
    @property
    def active(self) -> bool:
        return self._active

    def set_interval(self, interval_ms: int) -> None:
        """Change the idle interval (also used by tests to avoid slow waits)."""
        self._timer.setInterval(max(_MIN_INTERVAL_MS, int(interval_ms)))

    def start(self) -> None:
        """Activate: chrome visible, countdown running."""
        self._active = True
        self._reveal()

    def stop(self) -> None:
        """Deactivate: chrome visible, countdown stopped."""
        self._active = False
        self._reveal()

    def poke(self) -> None:
        """Register user activity: reveal chrome, restart the countdown."""
        if not self._active:
            return
        self._reveal()

    # -------------------------------------------------------------- internals
    def _reveal(self) -> None:
        if self._active:
            self._timer.start()
        else:
            self._timer.stop()
        if self._is_hidden:
            self._is_hidden = False
            self.shown.emit()

    def _on_timeout(self) -> None:
        if not self._active or self._is_hidden:
            return
        self._is_hidden = True
        self.hidden.emit()
