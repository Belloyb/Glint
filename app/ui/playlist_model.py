"""Qt list model over the playback queue's playlist.

Bridges :class:`app.player.queue.PlaybackQueue` (plain mutations + signals)
to item views: display data, "now playing" marker, drag-and-drop reordering
(custom internal MIME type) and external file/URL drops onto the playlist.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QDataStream,
    QIODevice,
    QMimeData,
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QColor, QFont

from app.player.queue import PlaybackQueue
from app.ui.theme import DARK

_CURRENT_MARKER = "▶ "


class PlaylistModel(QAbstractListModel):
    """List model for the playlist panel."""

    ROW_MIME_TYPE = "application/x-glint-playlist-rows"
    CURRENT_ROLE = Qt.ItemDataRole.UserRole + 1
    URI_ROLE = Qt.ItemDataRole.UserRole + 2
    DURATION_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(self, queue: PlaybackQueue, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._current_row = -1
        self._move_in_progress = False
        self._incremental_done = False
        # Structural updates are incremental (Phase 10): a single insert /
        # contiguous remove / block move no longer resets the view. Mutations
        # the queue cannot express as one span still reset via itemsChanged.
        queue.rowsAboutToBeInserted.connect(self._on_rows_about_to_be_inserted)
        queue.rowsInserted.connect(self._on_rows_inserted)
        queue.rowsAboutToBeRemoved.connect(self._on_rows_about_to_be_removed)
        queue.rowsRemoved.connect(self._on_rows_removed)
        queue.rowsAboutToBeMoved.connect(self._on_rows_about_to_be_moved)
        queue.rowsMoved.connect(self._on_rows_moved)
        queue.playlistAboutToBeReset.connect(self._on_playlist_about_to_be_reset)
        queue.playlistReset.connect(self._on_playlist_reset)
        queue.itemsChanged.connect(self._on_items_changed)
        queue.itemUpdated.connect(self._on_item_updated)
        queue.currentChanged.connect(self._on_current_changed)

    # ---------------------------------------------------------- model API
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008 — canonical Qt signature
        if parent.isValid():
            return 0
        return len(self._queue.playlist)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._queue.playlist.item(index.row())
        if item is None:
            return None
        is_current = index.row() == self._queue.playlist.current_index
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{_CURRENT_MARKER}{item.title}" if is_current else item.title
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.uri
        if role == Qt.ItemDataRole.FontRole and is_current:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(DARK.accent if is_current else DARK.text)
        if role == self.CURRENT_ROLE:
            return is_current
        if role == self.URI_ROLE:
            return item.uri
        if role == self.DURATION_ROLE:
            return item.duration
        return None

    def flags(self, index):
        if index.isValid():
            return (
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )
        # Root (invalid index): drop target only — and exactly this value:
        # Qt's model tester (and its own StringListModel example) requires
        # the parent of drag-enabled rows to be precisely ItemIsDropEnabled.
        return Qt.ItemFlag.ItemIsDropEnabled

    # ------------------------------------------------------------- drag/drop
    def supportedDragActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def supportedDropActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [self.ROW_MIME_TYPE, "text/uri-list"]

    def mimeData(self, indexes):
        rows = sorted({index.row() for index in indexes if index.isValid()})
        if not rows:
            return None
        payload = QByteArray()
        stream = QDataStream(payload, QIODevice.OpenModeFlag.WriteOnly)
        stream.writeInt32(len(rows))
        for row in rows:
            stream.writeInt32(row)
        mime = QMimeData()
        mime.setData(self.ROW_MIME_TYPE, payload)
        return mime

    def dropMimeData(self, data, action, row, column, parent):
        if action == Qt.DropAction.IgnoreAction:
            return True
        if column > 0:
            return False
        target = parent.row() if parent.isValid() else row
        if target < 0 or target > len(self._queue.playlist):
            target = len(self._queue.playlist)

        if data.hasFormat(self.ROW_MIME_TYPE):
            rows = self._decode_rows(data.data(self.ROW_MIME_TYPE))
            if not rows:
                return False
            self._queue.move_rows(rows, target)
            return True
        if data.hasUrls():
            uris = self._urls_to_uris(data)
            if not uris:
                return False
            self._queue.add(uris, index=target)
            return True
        return False

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _decode_rows(payload: QByteArray) -> list[int]:
        stream = QDataStream(payload)
        count = stream.readInt32()
        if count <= 0 or count > 100_000:
            return []
        return [stream.readInt32() for _ in range(count)]

    @staticmethod
    def _urls_to_uris(data: QMimeData) -> list[str]:
        uris: list[str] = []
        for url in data.urls():
            if url.isEmpty():
                continue
            uris.append(url.toLocalFile() if url.isLocalFile() else url.toString())
        return uris

    # ------------------------------------------------------- queue → model
    def _on_rows_about_to_be_inserted(self, first: int, last: int) -> None:
        self.beginInsertRows(QModelIndex(), first, last)

    def _on_rows_inserted(self, first: int, last: int) -> None:
        self.endInsertRows()
        self._incremental_done = True
        self._reconcile_current_row()

    def _on_rows_about_to_be_removed(self, first: int, last: int) -> None:
        self.beginRemoveRows(QModelIndex(), first, last)

    def _on_rows_removed(self, first: int, last: int) -> None:
        self.endRemoveRows()
        self._incremental_done = True
        self._reconcile_current_row()

    def _on_rows_about_to_be_moved(self, first: int, last: int, destination: int) -> None:
        self._move_in_progress = self.beginMoveRows(
            QModelIndex(), first, last, QModelIndex(), destination
        )

    def _on_rows_moved(self, first: int, last: int, destination: int) -> None:
        if self._move_in_progress:
            self.endMoveRows()
            self._move_in_progress = False
        self._incremental_done = True
        self._reconcile_current_row()

    def _on_playlist_about_to_be_reset(self) -> None:
        self.beginResetModel()
        self._incremental_done = True

    def _on_playlist_reset(self) -> None:
        self.endResetModel()

    def _on_items_changed(self) -> None:
        # Only a fallback reset: the queue emits this after every mutation;
        # when an incremental pair already handled the change, skip.
        if getattr(self, "_incremental_done", False):
            self._incremental_done = False
            return
        self.beginResetModel()
        self.endResetModel()

    def _on_item_updated(self, row: int) -> None:
        if 0 <= row < len(self._queue.playlist):
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)

    def _reconcile_current_row(self) -> None:
        """Structural changes can shift the current row without a
        currentChanged signal (e.g. rows inserted above it) — sync the
        tracked row and repaint the two affected rows."""
        new_row = self._queue.playlist.current_index
        old_row, self._current_row = self._current_row, new_row
        count = len(self._queue.playlist)
        for row in {old_row, new_row}:
            if 0 <= row < count:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index)

    def _on_current_changed(self, _row: int) -> None:
        # The "now playing" marker moves between exactly two rows — repaint
        # only those (a full-range dataChanged repaints every visible row,
        # O(playlist) per track change).
        self._reconcile_current_row()
