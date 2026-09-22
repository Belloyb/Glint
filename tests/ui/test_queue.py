"""Fast queue-orchestration tests using a fake controller (no engine).

Exercises auto-advance, error-skip, repeat/shuffle orchestration and the
removed-current-item semantics without any playback.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from app.core.models import PlaybackState
from app.core.playlist import RepeatMode
from app.player.queue import PlaybackQueue


class FakeController(QObject):
    """Minimal stand-in for PlayerController (signals + open recorder)."""

    stateChanged = Signal(object)
    mediaLoaded = Signal(object)
    durationChanged = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.state = PlaybackState.IDLE
        self.opened: list[str] = []

    def open(self, uri: str) -> None:
        self.opened.append(uri)

    def emit_state(self, state: PlaybackState) -> None:
        self.state = state
        self.stateChanged.emit(state)


@pytest.fixture
def controller():
    return FakeController()


@pytest.fixture
def queue(controller):
    return PlaybackQueue(controller, seed=42)


def test_play_index_opens_and_tracks_current(controller, queue):
    queue.add(["a.mp3", "b.mp3"])
    queue.play_index(1)
    assert controller.opened == ["b.mp3"]
    assert queue.playlist.current_index == 1


def test_auto_advance_on_ended(controller, queue):
    queue.add(["a.mp3", "b.mp3"])
    queue.play_index(0)
    controller.emit_state(PlaybackState.ENDED)
    assert controller.opened == ["a.mp3", "b.mp3"]
    assert queue.playlist.current_index == 1


def test_auto_advance_stops_at_playlist_end(controller, queue):
    queue.add(["a.mp3"])
    queue.play_index(0)
    controller.emit_state(PlaybackState.ENDED)
    assert controller.opened == ["a.mp3"]  # nothing more opened


def test_repeat_one_replays_on_auto_advance(controller, queue):
    queue.add(["a.mp3", "b.mp3"])
    queue.set_repeat(RepeatMode.ONE)
    queue.play_index(0)
    controller.emit_state(PlaybackState.ENDED)
    assert controller.opened == ["a.mp3", "a.mp3"]
    assert queue.playlist.current_index == 0


def test_manual_next_ignores_repeat_one(controller, queue):
    queue.add(["a.mp3", "b.mp3"])
    queue.set_repeat(RepeatMode.ONE)
    queue.play_index(0)
    queue.next(auto=False)
    assert controller.opened == ["a.mp3", "b.mp3"]


def test_error_skips_to_next(controller, queue):
    queue.add(["bad.mkv", "good.mp3"])
    queue.play_index(0)
    controller.emit_state(PlaybackState.ERROR)
    assert controller.opened == ["bad.mkv", "good.mp3"]


def test_single_item_error_does_not_skip(controller, queue):
    queue.add(["bad.mkv"])
    queue.play_index(0)
    controller.emit_state(PlaybackState.ERROR)
    assert controller.opened == ["bad.mkv"]


def test_error_skip_gives_up_after_limit(controller, queue):
    uris = [f"bad{i}.mkv" for i in range(12)]
    queue.add(uris)
    queue.play_index(0)
    for _ in range(12):
        controller.emit_state(PlaybackState.ERROR)
    # limit = max(3, 12) = 12 → opens stop after the 12th failure
    assert len(controller.opened) == 12
    assert controller.opened[-1] == "bad11.mkv"


def test_playing_resets_error_counter(controller, queue):
    queue.add(["a", "b", "c"])
    queue.play_index(0)
    controller.emit_state(PlaybackState.ERROR)  # skip to b
    controller.emit_state(PlaybackState.PLAYING)  # b works → counter reset
    controller.emit_state(PlaybackState.ERROR)  # skip to c
    assert controller.opened == ["a", "b", "c"]


def test_removing_current_playing_item_plays_successor_after_end(controller, queue):
    queue.add(["a.mp3", "b.mp3", "c.mp3"])
    queue.play_index(1)  # b playing
    controller.state = PlaybackState.PLAYING
    queue.remove_indices([1])  # remove the playing item
    assert queue.playlist.current_index == 1  # c is the new current
    controller.emit_state(PlaybackState.ENDED)  # b finishes
    assert controller.opened == ["b.mp3", "c.mp3"]  # c plays, not skipped


def test_load_replaces_and_signals(controller, queue):
    queue.add(["a", "b"])
    queue.play_index(0)
    queue.load(["x", "y", "z"])
    assert [item.uri for item in queue.playlist.items()] == ["x", "y", "z"]
    assert queue.playlist.current_index == -1


def test_is_idle_reflects_controller_state(controller, queue):
    assert queue.is_idle is True
    controller.state = PlaybackState.PLAYING
    assert queue.is_idle is False
    controller.state = PlaybackState.ENDED
    assert queue.is_idle is True


def test_media_loaded_updates_duration_and_title(controller, queue):
    from app.core.models import MediaInfo

    queue.add(["/music/track.mp3"])
    queue.play_index(0)
    controller.mediaLoaded.emit(MediaInfo(uri="/music/track.mp3", title="Track"))
    controller.durationChanged.emit(98.5)
    item = queue.playlist.item(0)
    assert item.duration == 98.5
    assert item.title == "Track"


def test_shuffle_toggle_signals(controller, queue):
    states = []
    queue.shuffleChanged.connect(states.append)
    queue.toggle_shuffle()
    queue.toggle_shuffle()
    assert states == [True, False]


def test_repeat_cycle_signals(controller, queue):
    modes = []
    queue.repeatChanged.connect(modes.append)
    queue.cycle_repeat()
    queue.cycle_repeat()
    queue.cycle_repeat()
    assert modes == [RepeatMode.ALL, RepeatMode.ONE, RepeatMode.OFF]
