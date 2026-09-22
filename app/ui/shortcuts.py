"""Qt binding layer for the centralised shortcut configuration.

Bridges the Qt-free :class:`app.core.shortcuts.ShortcutConfig` to live
``QShortcut`` objects on the main window. Only actions the application
explicitly binds get shortcuts — the config may contain actions for later
phases; they stay dormant until their handler is registered.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from app.core.shortcuts import PlayerAction, ShortcutConfig, normalize_sequence
from app.utils.logging import get_logger

logger = get_logger("ui.shortcuts")


class ShortcutManager(QObject):
    """Creates and owns the window's QShortcuts from a ShortcutConfig."""

    def __init__(
        self,
        window: QWidget,
        config: ShortcutConfig,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._config = config
        self._shortcuts: list[QShortcut] = []
        self._owners: dict[str, PlayerAction] = {}  # normalised sequence -> action

    # ------------------------------------------------------------------ API
    def bind(self, action: PlayerAction, handler: Callable[[], None]) -> None:
        """Bind every configured key sequence of ``action`` to ``handler``."""
        sequences = self._config.sequences(action)
        if not sequences:
            logger.debug("action %s has no key bindings", action.value)
            return
        for raw in sequences:
            normalized = normalize_sequence(raw)
            sequence = QKeySequence(self._platform_sequence(normalized))
            if sequence.count() == 0:
                logger.warning("unparsable key sequence %r for %s; skipped", raw, action.value)
                continue
            owner = self._owners.get(normalized)
            if owner is not None and owner is not action:
                logger.warning(
                    "key sequence %s is bound to both %s and %s; keeping %s",
                    normalized,
                    owner.value,
                    action.value,
                    owner.value,
                )
                continue
            shortcut = QShortcut(sequence, self._window)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)
            self._owners[normalized] = action
            logger.debug("bound %s -> %s", normalized, action.value)

    def key_sequences(self, action: PlayerAction) -> list[QKeySequence]:
        """The action's sequences as QKeySequence objects (platform-adjusted)."""
        return [
            QKeySequence(self._platform_sequence(sequence))
            for sequence in self._config.sequences(action)
        ]

    def display_text(self, label: str, action: PlayerAction) -> str:
        """Menu label with the action's first shortcut appended (``label\\tkey``)."""
        sequences = self.key_sequences(action)
        if not sequences:
            return label
        native = sequences[0].toString(QKeySequence.SequenceFormat.NativeText)
        return f"{label}\t{native}"

    # -------------------------------------------------------------- internals
    @staticmethod
    def _platform_sequence(sequence: str) -> str:
        # macOS menu convention: application-level shortcuts use Cmd, not Ctrl.
        if sys.platform == "darwin" and sequence.startswith("Ctrl+"):
            return "Meta+" + sequence[len("Ctrl+") :]
        return sequence
