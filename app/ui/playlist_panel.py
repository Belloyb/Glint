"""Playlist side panel: view, toolbar, footer, interactions.

File dialogs are *not* opened here — the panel emits requests and the main
window (which owns dialogs) handles them. The panel talks to the
:class:`PlaybackQueue` directly for in-playlist operations.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListView,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.playlist import RepeatMode
from app.player.queue import PlaybackQueue
from app.ui.icons import load_icon
from app.ui.playlist_model import PlaylistModel
from app.utils.format import format_time

_BUTTON_SIZE = 34, 28


class PlaylistPanel(QWidget):
    """Playlist list with add/remove/shuffle/repeat toolbar."""

    addFilesRequested = Signal()
    addFolderRequested = Signal()
    saveRequested = Signal()
    loadRequested = Signal()

    def __init__(self, queue: PlaybackQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaylistPanel")
        self._queue = queue

        self._model = PlaylistModel(queue, self)
        self._view = self._build_view()
        self._toolbar = self._build_toolbar()

        footer = self._footer_label = QPushButton("0 items")
        footer.setObjectName("PlaylistFooter")
        footer.setFlat(True)
        footer.setEnabled(False)
        footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        footer.setCursor(Qt.CursorShape.ArrowCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._view, 1)
        layout.addWidget(footer)

        queue.itemsChanged.connect(self._update_footer)
        queue.itemUpdated.connect(lambda _row: self._update_footer())
        queue.currentChanged.connect(self._on_current_changed)
        queue.shuffleChanged.connect(self._on_shuffle_changed)
        queue.repeatChanged.connect(self._on_repeat_changed)

        self._on_shuffle_changed(queue.playlist.shuffle)
        self._on_repeat_changed(queue.playlist.repeat)
        self._update_footer()

    # ------------------------------------------------------------------ setup
    def _build_view(self) -> QListView:
        view = QListView()
        view.setModel(self._model)
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        view.setDefaultDropAction(Qt.DropAction.MoveAction)
        view.setAlternatingRowColors(False)
        view.setWordWrap(False)
        view.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        # All rows are single-line items of equal height: letting the view
        # assume uniform sizes avoids a full re-layout on every insert/remove
        # (measured on 10k rows: a single-row insert drops from ~240 ms to
        # ~20 ms under Xvfb — see docs/PHASE10_NOTES.md).
        view.setUniformItemSizes(True)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._show_context_menu)
        view.activated.connect(self._on_activated)
        view.setTabKeyNavigation(True)
        # Delete-to-remove is a panel-local convenience key, not a global
        # configurable action (it only makes sense while the panel has focus).
        delete_key = QShortcut(Qt.Key.Key_Delete, view)
        delete_key.activated.connect(self.remove_selected)
        return view

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.btn_add = self._make_button("plus", "Add files")
        self.btn_add_folder = self._make_button("folder-open", "Add folder")
        self.btn_remove = self._make_button("minus", "Remove selected (Del)")
        self.btn_clear = self._make_button("trash", "Clear playlist")
        self.btn_shuffle = self._make_button("shuffle", "Shuffle: off")
        self.btn_repeat = self._make_button("repeat", "Repeat: Off")
        self.btn_save = self._make_button("save", "Save playlist")
        self.btn_load = self._make_button("list", "Open playlist")

        self.btn_shuffle.setCheckable(True)
        self.btn_repeat.setCheckable(True)

        for button in (
            self.btn_add,
            self.btn_add_folder,
            self.btn_remove,
            self.btn_clear,
            self.btn_shuffle,
            self.btn_repeat,
        ):
            layout.addWidget(button)
        layout.addStretch()
        layout.addWidget(self.btn_save)
        layout.addWidget(self.btn_load)

        self.btn_add.clicked.connect(self.addFilesRequested.emit)
        self.btn_add_folder.clicked.connect(self.addFolderRequested.emit)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self._queue.clear)
        self.btn_shuffle.clicked.connect(self._queue.toggle_shuffle)
        self.btn_repeat.clicked.connect(self._queue.cycle_repeat)
        self.btn_save.clicked.connect(self.saveRequested.emit)
        self.btn_load.clicked.connect(self.loadRequested.emit)
        return bar

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

    # ------------------------------------------------------------ interactions
    def _on_activated(self, index) -> None:
        self._queue.play_index(index.row())

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self._view.selectedIndexes()})
        if rows:
            self._queue.remove_indices(rows)

    def _show_context_menu(self, position) -> None:
        index = self._view.indexAt(position)
        menu = QMenu(self)
        if index.isValid():
            menu.addAction("Play", lambda: self._queue.play_index(index.row()))
            menu.addSeparator()
            menu.addAction("Remove", self.remove_selected)
        else:
            menu.addAction("Add files…", self.addFilesRequested.emit)
            menu.addAction("Add folder…", self.addFolderRequested.emit)
        menu.addAction("Clear playlist", self._queue.clear)
        menu.exec(self._view.viewport().mapToGlobal(position))

    # -------------------------------------------------------------- state sync
    def _on_current_changed(self, row: int) -> None:
        if row >= 0:
            index = self._model.index(row, 0)
            self._view.setCurrentIndex(index)
            self._view.scrollTo(index)

    def _on_shuffle_changed(self, enabled: bool) -> None:
        self.btn_shuffle.setChecked(enabled)
        self.btn_shuffle.setToolTip("Shuffle: on" if enabled else "Shuffle: off")

    def _on_repeat_changed(self, mode: RepeatMode) -> None:
        self.btn_repeat.setChecked(mode is not RepeatMode.OFF)
        icon_name = {
            RepeatMode.ALL: "repeat",
            RepeatMode.ONE: "repeat-one",
        }.get(mode, "repeat")
        self.btn_repeat.setIcon(load_icon(icon_name))
        self.btn_repeat.setToolTip(f"Repeat: {mode.value.capitalize()}")

    def _update_footer(self) -> None:
        items = self._queue.playlist.items()
        total = sum(item.duration or 0.0 for item in items)
        label = f"{len(items)} item{'s' if len(items) != 1 else ''}"
        if total > 0:
            label += f" · {format_time(total)}"
        self._footer_label.setText(label)
