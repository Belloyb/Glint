"""Qt-free playlist engine: items, navigation order, shuffle and repeat.

The playlist stores *items* (uri, title, duration). Navigation is defined
over a play order: with shuffle off this is simply the item order; with
shuffle on it is a seeded permutation that always starts at the currently
playing item (so enabling shuffle mid-play never interrupts playback and
never replays what already played in this order).

Structural mutations (add/remove/move/clear) keep the play order consistent.
The current index is tracked by item *identity* across removals and moves,
so "now playing" is never lost when earlier rows change.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.utils.logging import get_logger

logger = get_logger("core.playlist")


class RepeatMode(Enum):
    """Playlist repeat behaviour."""

    OFF = "off"
    ALL = "all"
    ONE = "one"


#: The order used when cycling the repeat mode in the UI.
REPEAT_CYCLE: tuple[RepeatMode, RepeatMode, RepeatMode] = (
    RepeatMode.OFF,
    RepeatMode.ALL,
    RepeatMode.ONE,
)


@dataclass
class PlaylistItem:
    """One playlist entry. ``duration`` is filled in once known (played)."""

    uri: str
    title: str
    duration: float | None = None

    @classmethod
    def from_uri(cls, uri: str) -> PlaylistItem:
        return cls(uri=uri, title=title_for_uri(uri))


def title_for_uri(uri: str) -> str:
    """Human-friendly title for a URI without touching the engine."""
    if "://" in uri:
        tail = uri.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        return tail or uri
    return Path(uri).stem or uri


class Playlist:
    """Ordered media items plus navigation state (shuffle/repeat/current)."""

    def __init__(self, seed: int | None = None) -> None:
        self._items: list[PlaylistItem] = []
        self._current = -1
        self._shuffle = False
        self._repeat = RepeatMode.OFF
        # Only meaningful while shuffle is on; rebuilt defensively if stale.
        self._order: list[int] = []
        self._rng = random.Random(seed)

    # ------------------------------------------------------------- queries
    def __len__(self) -> int:
        return len(self._items)

    def items(self) -> list[PlaylistItem]:
        """A shallow copy of the item list."""
        return list(self._items)

    def item(self, index: int) -> PlaylistItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    @property
    def current_index(self) -> int:
        return self._current

    @property
    def current_item(self) -> PlaylistItem | None:
        return self.item(self._current)

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def repeat(self) -> RepeatMode:
        return self._repeat

    # ----------------------------------------------------------- mutations
    def add(self, uris: Iterable[str], index: int | None = None) -> list[int]:
        """Insert items (in the given order) at ``index`` (default: end).

        Returns the indices of the newly inserted items.
        """
        uris = list(uris)
        if not uris:
            return []
        count = len(self._items)
        if index is None or index > count:
            index = count
        index = max(index, 0)

        new_items = [PlaylistItem.from_uri(uri) for uri in uris]
        inserted = list(range(index, index + len(new_items)))

        # Keep the current index pointing at the same item.
        if self._current >= index:
            self._current += len(new_items)

        for offset, item in enumerate(new_items):
            self._items.insert(index + offset, item)

        if self._shuffle:
            self._adjust_order_for_insert(index, len(new_items))
            self._order.extend(inserted)
        return inserted

    def remove_indices(self, indices: Iterable[int]) -> None:
        """Remove the given item indices (order-independent input)."""
        rows = sorted({i for i in indices if 0 <= i < len(self._items)})
        if not rows:
            return
        removed = set(rows)
        total_before = len(self._items)

        current_object = (
            self._items[self._current] if 0 <= self._current < total_before else None
        )
        current_removed = 0 <= self._current < total_before and self._current in removed

        self._items = [item for i, item in enumerate(self._items) if i not in removed]

        if current_removed:
            # The successor of the removed current becomes the new current,
            # clamped backwards when the removed item was last, none if empty.
            successor = next(
                (i for i in range(self._current, total_before) if i not in removed), None
            )
            if successor is None:
                successor = next(
                    (i for i in range(self._current, -1, -1) if i not in removed), None
                )
            if successor is None:
                self._current = -1
            else:
                self._current = sum(1 for i in range(successor) if i not in removed)
        elif current_object is not None:
            self._current = next(
                i for i, item in enumerate(self._items) if item is current_object
            )

        if self._shuffle:
            self._order = self._shift_order_after_removal(rows)

    def move_rows(self, rows: Iterable[int], target: int) -> None:
        """Move the given items so they land before old index ``target``.

        ``target`` uses drop semantics (0..len, computed against the old
        numbering). Moving a block onto itself is naturally a no-op.
        """
        n = len(self._items)
        rows = sorted({r for r in rows if 0 <= r < n})
        target = max(0, min(target, n))
        if not rows:
            return
        row_set = set(rows)

        current_object = (
            self._items[self._current] if 0 <= self._current < len(self._items) else None
        )
        moving = [self._items[r] for r in rows]
        remaining = [item for i, item in enumerate(self._items) if i not in row_set]
        insert_at = target - sum(1 for r in rows if r < target)
        insert_at = max(0, min(insert_at, len(remaining)))
        self._items = remaining[:insert_at] + moving + remaining[insert_at:]

        if current_object is not None:
            self._current = next(
                i for i, item in enumerate(self._items) if item is current_object
            )
        if self._shuffle:
            # The play order no longer matches the visual move; rebuild it
            # around the current item (documented behaviour).
            self._rebuild_shuffled_order()

    def clear(self) -> None:
        self._items = []
        self._current = -1
        self._order = []

    def set_current(self, index: int) -> None:
        if -1 <= index < len(self._items):
            self._current = index

    def set_shuffle(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._shuffle:
            return
        self._shuffle = enabled
        if enabled:
            self._rebuild_shuffled_order()

    def toggle_shuffle(self) -> bool:
        self.set_shuffle(not self._shuffle)
        return self._shuffle

    def set_repeat(self, mode: RepeatMode) -> None:
        self._repeat = mode

    def cycle_repeat(self) -> RepeatMode:
        """OFF → ALL → ONE → OFF."""
        index = REPEAT_CYCLE.index(self._repeat)
        self._repeat = REPEAT_CYCLE[(index + 1) % len(REPEAT_CYCLE)]
        return self._repeat

    # ---------------------------------------------------------- navigation
    def next_index(self, auto: bool) -> int | None:
        """The index that follows the current one.

        ``auto`` is True when playback reached the end by itself (respects
        RepeatMode.ONE by replaying the current item) and False for an
        explicit user "next" (repeat-one behaves like off, as in VLC).
        """
        n = len(self._items)
        if n == 0:
            return None
        if auto and self._repeat is RepeatMode.ONE and self._current >= 0:
            return self._current
        order = self._play_order()
        if self._current < 0:
            return order[0]
        try:
            position = order.index(self._current)
        except ValueError:
            return order[0]
        if position + 1 < len(order):
            return order[position + 1]
        if self._repeat is RepeatMode.ALL:
            return order[0]
        return None

    def previous_index(self) -> int | None:
        n = len(self._items)
        if n == 0 or self._current < 0:
            return None
        order = self._play_order()
        try:
            position = order.index(self._current)
        except ValueError:
            return order[0]
        if position > 0:
            return order[position - 1]
        if self._repeat is RepeatMode.ALL:
            return order[-1]
        return None

    # -------------------------------------------------------------- helpers
    def _play_order(self) -> list[int]:
        if not self._shuffle:
            return list(range(len(self._items)))
        expected = set(range(len(self._items)))
        if len(self._order) != len(self._items) or set(self._order) != expected:
            self._rebuild_shuffled_order()
        return list(self._order)

    def _rebuild_shuffled_order(self) -> None:
        rest = [i for i in range(len(self._items)) if i != self._current]
        self._rng.shuffle(rest)
        head = [self._current] if 0 <= self._current < len(self._items) else []
        self._order = head + rest

    def _adjust_order_for_insert(self, index: int, count: int) -> None:
        self._order = [i + count if i >= index else i for i in self._order]

    def _shift_order_after_removal(self, rows: list[int]) -> list[int]:
        removed = set(rows)

        def shift(index: int) -> int | None:
            if index in removed:
                return None
            return index - sum(1 for r in rows if r < index)

        return [shifted for shifted in (shift(i) for i in self._order) if shifted is not None]
