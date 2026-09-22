"""Tests for the playlist Qt model: data roles, drops, internal moves."""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QMimeData, QModelIndex, QPersistentModelIndex, Qt, QUrl

from app.player.queue import PlaybackQueue
from app.ui.playlist_model import PlaylistModel
from tests.ui.test_queue import FakeController

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="requires a Qt platform (use xvfb-run on headless Linux)",
)


@pytest.fixture
def env(qapp):
    controller = FakeController()
    queue = PlaybackQueue(controller, seed=42)
    model = PlaylistModel(queue)
    queue.add(["a.mp3", "b.mp3", "c.mp3"])
    return controller, queue, model


def test_rowcount_and_display(env):
    _controller, _queue, model = env
    assert model.rowCount() == 3
    assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == "b"
    assert model.data(model.index(1, 0), PlaylistModel.URI_ROLE) == "b.mp3"


def test_current_marker_and_roles(env):
    _controller, queue, model = env
    queue.play_index(1)
    assert model.data(model.index(1, 0), PlaylistModel.CURRENT_ROLE) is True
    assert model.data(model.index(0, 0), PlaylistModel.CURRENT_ROLE) is False
    assert "▶" in model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole)
    assert model.data(model.index(1, 0), Qt.ItemDataRole.ToolTipRole) == "b.mp3"


def test_external_url_drop_inserts_at_position(env, qapp):
    _controller, queue, model = env
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/new/file.mp4"), QUrl("http://example.com/s.mp4")])
    assert model.dropMimeData(mime, Qt.DropAction.CopyAction, 1, 0, QModelIndex())
    uris = [item.uri for item in queue.playlist.items()]
    assert uris == ["a.mp3", "/new/file.mp4", "http://example.com/s.mp4", "b.mp3", "c.mp3"]


def test_internal_move_via_mime_roundtrip(env):
    _controller, queue, model = env
    # Drag rows 0 and 2…
    mime = model.mimeData([model.index(0, 0), model.index(2, 0)])
    assert mime is not None
    # …and drop them before row 3 (the end).
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, 3, 0, QModelIndex())
    assert [item.uri for item in queue.playlist.items()] == ["b.mp3", "a.mp3", "c.mp3"]


def test_internal_move_to_top(env):
    _controller, queue, model = env
    mime = model.mimeData([model.index(2, 0)])  # c
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, 0, 0, QModelIndex())
    assert [item.uri for item in queue.playlist.items()] == ["c.mp3", "a.mp3", "b.mp3"]


def test_move_keeps_current_marker(env):
    _controller, queue, model = env
    queue.play_index(0)  # a playing
    mime = model.mimeData([model.index(0, 0)])
    model.dropMimeData(mime, Qt.DropAction.MoveAction, 2, 0, QModelIndex())
    assert [item.uri for item in queue.playlist.items()] == ["b.mp3", "a.mp3", "c.mp3"]
    assert queue.playlist.current_index == 1
    assert model.data(model.index(1, 0), PlaylistModel.CURRENT_ROLE) is True


def test_items_changed_resets_model(env):
    _controller, queue, model = env
    assert model.rowCount() == 3
    queue.remove_indices([0, 1, 2])
    assert model.rowCount() == 0


def test_malformed_internal_mime_is_ignored(env):
    _controller, queue, model = env
    mime = QMimeData()
    mime.setData(PlaylistModel.ROW_MIME_TYPE, b"garbage")
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, 1, 0, QModelIndex()) is False
    assert [item.uri for item in queue.playlist.items()] == ["a.mp3", "b.mp3", "c.mp3"]


# --------------------------------------------------- incremental updates (P10)
def _spy(model):
    """Record structural model signals as (kind, row-args).

    The rows* signals deliver a leading parent QModelIndex; it is dropped
    for readability (always the invalid root for a list model).
    """
    events: list[tuple[str, object]] = []

    def record(kind, strip_parent):
        def handler(*args):
            events.append((kind, tuple(args[1:]) if strip_parent else args))

        return handler

    for name, strip in (
        ("rowsAboutToBeInserted", True),
        ("rowsInserted", True),
        ("rowsAboutToBeRemoved", True),
        ("rowsRemoved", True),
        ("rowsAboutToBeMoved", True),
        ("rowsMoved", True),
        ("modelReset", False),
    ):
        getattr(model, name).connect(record(name, strip))
    return events



def test_single_insert_is_incremental(env):
    _c, queue, model = env
    events = _spy(model)
    queue.add(["d.mp3"])
    assert ("rowsInserted", (3, 3)) in [e for e in events if e[0] == "rowsInserted"]
    assert not any(e[0] == "modelReset" for e in events)
    assert model.rowCount() == 4
    assert model.data(model.index(3, 0), Qt.ItemDataRole.DisplayRole) == "d"


def test_insert_at_front_shifts_rows(env):
    _c, queue, model = env
    persistent = QPersistentModelIndex(model.index(2, 0))  # "c"
    queue.add(["zero.mp3"], index=0)
    assert model.rowCount() == 4
    assert model.data(model.index(3, 0), Qt.ItemDataRole.DisplayRole) == "c"
    assert persistent.row() == 3  # survived the shift


def test_contiguous_remove_is_incremental(env):
    _c, queue, model = env
    events = _spy(model)
    queue.remove_indices([1])
    assert ("rowsRemoved", (1, 1)) in [e for e in events if e[0] == "rowsRemoved"]
    assert not any(e[0] == "modelReset" for e in events)
    assert model.rowCount() == 2
    assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == "c"


def test_scattered_remove_falls_back_to_reset(env):
    _c, queue, model = env
    events = _spy(model)
    queue.remove_indices([0, 2])
    assert any(e[0] == "modelReset" for e in events)
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "b"


def test_block_move_is_incremental(env):
    _c, queue, model = env
    events = _spy(model)
    queue.move_rows([1], 3)  # move "b" to the end: [a, c, b]
    assert any(e[0] == "rowsMoved" for e in events)
    assert not any(e[0] == "modelReset" for e in events)
    assert [model.data(model.index(r, 0), Qt.ItemDataRole.DisplayRole) for r in range(3)] == [
        "a", "c", "b"
    ]


def test_move_onto_itself_emits_no_structure(env):
    _c, queue, model = env
    events = _spy(model)
    queue.move_rows([0], 1)  # block already before index 1: visual no-op
    assert not any(e[0] in ("rowsMoved", "rowsAboutToBeMoved") for e in events)


def test_scattered_move_falls_back_to_reset(env):
    _c, queue, model = env
    events = _spy(model)
    queue.move_rows([0, 2], 3)
    assert any(e[0] == "modelReset" for e in events)
    assert model.rowCount() == 3


def test_load_resets(env):
    _c, queue, model = env
    events = _spy(model)
    queue.load(["x.mp3", "y.mp3"])
    assert any(e[0] == "modelReset" for e in events)
    assert model.rowCount() == 2


def test_current_change_repaints_only_two_rows(env):
    _c, queue, model = env
    changed: list[tuple[int, int]] = []

    def on_changed(top, bottom, _roles=None):
        changed.append((top.row(), bottom.row()))

    model.dataChanged.connect(on_changed)
    queue.play_index(1)  # nothing was current before: only the new row repaints
    assert changed == [(1, 1)]
    queue.play_index(2)  # marker moves 1 -> 2: exactly those two rows repaint
    assert changed == [(1, 1), (1, 1), (2, 2)]


def test_insert_above_current_keeps_marker_right(env):
    _c, queue, model = env
    queue.play_index(2)  # "c" current
    queue.add(["zero.mp3"], index=0)
    assert model.data(model.index(3, 0), PlaylistModel.CURRENT_ROLE) is True
    assert model.data(model.index(0, 0), PlaylistModel.CURRENT_ROLE) is False


def test_model_protocol_validated_by_qt(env, qtmodeltester):
    """Qt's own model tester validates the incremental protocol."""
    _c, queue, model = env
    qtmodeltester.check(model)
    queue.add(["d.mp3"])
    queue.add(["zero.mp3"], index=0)
    queue.remove_indices([1])
    queue.remove_indices([0, 2])
    queue.move_rows([0], 2)
    queue.load(["n1.mp3", "n2.mp3", "n3.mp3"])
    queue.add(["n4.mp3"])
    queue.play_index(1)
