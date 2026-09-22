"""Playback queue: orchestrates the playlist and the player controller.

This is the application-level API the UI uses for *queue-level* operations
(open/add/next/previous/shuffle/repeat), while :class:`PlayerController`
remains the engine-level façade. Auto-advance on end-of-media and
skip-after-error live here, behind guards against endless error loops.

Removal subtlety: when the *currently playing* item is removed from the
playlist, playback continues to its end; the successor (which became the new
current) is then played next instead of being skipped.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QObject, Signal

from app.core.models import MediaInfo, PlaybackState
from app.core.playlist import Playlist, RepeatMode
from app.player.controller import PlayerController
from app.utils.logging import get_logger

logger = get_logger("player.queue")

#: Skip at most this many consecutive failures (or the playlist length, if
#: larger) before giving up and leaving the last error on screen.
_MIN_CONSECUTIVE_ERRORS = 3


class PlaybackQueue(QObject):
    """Playlist + player orchestration with Qt signals."""

    itemsChanged = Signal()
    itemUpdated = Signal(int)
    currentChanged = Signal(int)
    shuffleChanged = Signal(bool)
    repeatChanged = Signal(object)  # RepeatMode
    # Fine-grained structural notifications (Phase 10). Emitted *in addition
    # to* itemsChanged (which stays for cheap listeners like the footer
    # label). Each mutation either emits one about/after pair describing a
    # single contiguous span — letting the playlist model update
    # incrementally — or only itemsChanged, which the model maps to a reset.
    # Contract: "about" fires before the underlying Playlist changes (models
    # call begin* there), the plain signal after (models call end*).
    rowsAboutToBeInserted = Signal(int, int)  # first, last (inclusive)
    rowsInserted = Signal(int, int)
    rowsAboutToBeRemoved = Signal(int, int)  # first, last (inclusive)
    rowsRemoved = Signal(int, int)
    rowsAboutToBeMoved = Signal(int, int, int)  # first, last, destination
    rowsMoved = Signal(int, int, int)
    playlistAboutToBeReset = Signal()
    playlistReset = Signal()

    def __init__(
        self,
        controller: PlayerController,
        seed: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.playlist = Playlist(seed=seed)
        self._consecutive_errors = 0
        self._current_not_started = False

        controller.stateChanged.connect(self._on_state_changed)
        controller.mediaLoaded.connect(self._on_media_loaded)
        controller.durationChanged.connect(self._on_duration_changed)

    # ------------------------------------------------------------- playlist
    def add(self, uris: Iterable[str], index: int | None = None) -> list[int]:
        """Append (or insert) URIs; returns their indices."""
        uris = list(uris)
        if not uris:
            return []
        insert_at = len(self.playlist) if index is None else max(0, min(index, len(self.playlist)))
        self.rowsAboutToBeInserted.emit(insert_at, insert_at + len(uris) - 1)
        added = self.playlist.add(uris, insert_at)
        # Core add() inserts every item unconditionally, so the announced
        # span always matches the actual one.
        self.rowsInserted.emit(insert_at, insert_at + len(uris) - 1)
        self.itemsChanged.emit()
        return added

    def load(self, uris: Iterable[str]) -> None:
        """Replace the whole playlist (nothing starts playing by itself)."""
        uris = list(uris)
        self.playlistAboutToBeReset.emit()
        self.playlist.clear()
        self.playlist.add(uris)
        self.playlistReset.emit()
        self.itemsChanged.emit()
        self.currentChanged.emit(-1)

    def remove_indices(self, indices: Iterable[int]) -> None:
        indices = list(indices)
        if not indices:
            return
        current = self.playlist.current_index
        current_removed = current in set(indices)
        was_playing = self._controller.state in (
            PlaybackState.PLAYING,
            PlaybackState.PAUSED,
            PlaybackState.LOADING,
        )
        # Same validity filter as the core (invalid rows are dropped).
        rows = sorted({i for i in indices if 0 <= i < len(self.playlist)})
        if not rows:
            return
        contiguous = rows[-1] - rows[0] == len(rows) - 1
        if contiguous:
            self.rowsAboutToBeRemoved.emit(rows[0], rows[-1])
        self.playlist.remove_indices(indices)
        if contiguous:
            self.rowsRemoved.emit(rows[0], rows[-1])
        self.itemsChanged.emit()
        self.currentChanged.emit(self.playlist.current_index)
        if current_removed and was_playing:
            # The engine keeps playing the removed file; when it ends, play
            # the new current item instead of skipping past it.
            self._current_not_started = True

    def move_rows(self, rows: Iterable[int], target: int) -> None:
        rows = list(rows)
        n = len(self.playlist)
        ordered = sorted({r for r in rows if 0 <= r < n})
        target = max(0, min(target, n))
        # Qt moves are single contiguous blocks; a multi-span drag falls
        # back to a model reset (same cost class as before Phase 10).
        incremental = bool(ordered) and ordered[-1] - ordered[0] == len(ordered) - 1
        if incremental:
            first, last = ordered[0], ordered[-1]
            # Qt's beginMoveRows destination uses the same old-numbering
            # drop semantics as the core's ``target``: "the block lands
            # before old row <target>" (verified against QAbstractItemModel
            # docs: moving 2-4 to destination 8 yields 1,5,6,7,2,3,4,8,9).
            destination = target
            # A destination within first..last+1 is a visual no-op.
            if first <= destination <= last + 1:
                incremental = False
        if incremental:
            self.rowsAboutToBeMoved.emit(first, last, destination)
        self.playlist.move_rows(rows, target)
        if incremental:
            self.rowsMoved.emit(first, last, destination)
        self.itemsChanged.emit()
        self.currentChanged.emit(self.playlist.current_index)

    def clear(self) -> None:
        self.load([])

    def set_shuffle(self, enabled: bool) -> None:
        self.playlist.set_shuffle(enabled)
        self.shuffleChanged.emit(self.playlist.shuffle)

    def toggle_shuffle(self) -> None:
        self.set_shuffle(not self.playlist.shuffle)

    def set_repeat(self, mode: RepeatMode) -> None:
        self.playlist.set_repeat(mode)
        self.repeatChanged.emit(mode)

    def cycle_repeat(self) -> RepeatMode:
        mode = self.playlist.cycle_repeat()
        self.repeatChanged.emit(mode)
        return mode

    # ------------------------------------------------------------- playback
    def play_index(self, index: int) -> None:
        item = self.playlist.item(index)
        if item is None:
            return
        self._current_not_started = False
        self.playlist.set_current(index)
        self.currentChanged.emit(index)
        self._controller.open(item.uri)

    def next(self, auto: bool = False) -> bool:
        """Advance to the next item; ``False`` when there is nowhere to go."""
        index = self.playlist.next_index(auto)
        if index is None:
            return False
        self.play_index(index)
        return True

    def previous(self) -> bool:
        index = self.playlist.previous_index()
        if index is None:
            return False
        self.play_index(index)
        return True

    @property
    def is_idle(self) -> bool:
        """True when nothing is loaded/playing (a drop may start playback)."""
        return self._controller.state in (
            PlaybackState.IDLE,
            PlaybackState.STOPPED,
            PlaybackState.ENDED,
            PlaybackState.ERROR,
        )

    # --------------------------------------------------------- engine events
    def _on_state_changed(self, state: PlaybackState) -> None:
        if state is PlaybackState.PLAYING:
            self._consecutive_errors = 0
        elif state is PlaybackState.ENDED:
            self._on_media_ended()
        elif state is PlaybackState.ERROR:
            self._skip_after_error()

    def _on_media_ended(self) -> None:
        if self._current_not_started:
            self._current_not_started = False
            index = self.playlist.current_index
            if index >= 0:
                self.play_index(index)
                return
        self.next(auto=True)

    def _skip_after_error(self) -> None:
        count = len(self.playlist)
        if count <= 1:
            return  # single item: the error banner already says it all
        self._consecutive_errors += 1
        limit = max(_MIN_CONSECUTIVE_ERRORS, count)
        if self._consecutive_errors >= limit:
            logger.warning(
                "stopped auto-skipping after %d consecutive errors", self._consecutive_errors
            )
            return
        logger.info("skipping to next item after error")
        self.next(auto=True)

    def _on_duration_changed(self, duration: float) -> None:
        """The engine reports the duration slightly after file-loaded."""
        self._update_current_item(duration=duration)

    def _on_media_loaded(self, info: MediaInfo) -> None:
        self._update_current_item(title=info.title)

    def _update_current_item(
        self, duration: float | None = None, title: str | None = None
    ) -> None:
        index = self.playlist.current_index
        item = self.playlist.item(index) if index >= 0 else None
        if item is None:
            return
        changed = False
        if duration is not None and duration > 0 and item.duration != duration:
            item.duration = duration
            changed = True
        if title and title != item.title:
            item.title = title
            changed = True
        if changed:
            self.itemUpdated.emit(index)
