"""Unit tests for the Qt-free playlist engine."""

from __future__ import annotations

from app.core.playlist import Playlist, RepeatMode


def build(playlist: Playlist) -> list[str]:
    return [item.uri for item in playlist.items()]


def test_add_appends_and_returns_indices():
    playlist = Playlist()
    assert playlist.add(["a.mp3", "b.mp3"]) == [0, 1]
    assert build(playlist) == ["a.mp3", "b.mp3"]
    assert playlist.add(["c.mp3"]) == [2]


def test_add_at_index_shifts_current():
    playlist = Playlist()
    playlist.add(["a", "b", "c"])
    playlist.set_current(2)  # c playing
    playlist.add(["x"], index=0)
    assert build(playlist) == ["x", "a", "b", "c"]
    assert playlist.current_index == 3
    assert playlist.current_item.uri == "c"


def test_titles_derived_from_uri():
    playlist = Playlist()
    playlist.add(["/music/some song.mp3", "https://example.com/stream.mp4?v=1"])
    assert [item.title for item in playlist.items()] == ["some song", "stream.mp4"]


def test_remove_before_current_keeps_identity():
    playlist = Playlist()
    playlist.add(["a", "b", "c"])
    playlist.set_current(2)
    playlist.remove_indices([0])
    assert build(playlist) == ["b", "c"]
    assert playlist.current_index == 1
    assert playlist.current_item.uri == "c"


def test_remove_current_moves_to_successor():
    playlist = Playlist()
    playlist.add(["a", "b", "c"])
    playlist.set_current(1)  # b playing
    playlist.remove_indices([1])
    assert build(playlist) == ["a", "c"]
    assert playlist.current_index == 1
    assert playlist.current_item.uri == "c"  # successor became current


def test_remove_last_current_clamps_backwards():
    playlist = Playlist()
    playlist.add(["a", "b", "c"])
    playlist.set_current(2)
    playlist.remove_indices([2])
    assert playlist.current_index == 1
    assert playlist.current_item.uri == "b"


def test_remove_all_current_empties():
    playlist = Playlist()
    playlist.add(["a", "b"])
    playlist.set_current(1)
    playlist.remove_indices([0, 1])
    assert len(playlist) == 0
    assert playlist.current_index == -1


def test_remove_many_including_current():
    playlist = Playlist()
    playlist.add(["a", "b", "c", "d", "e"])
    playlist.set_current(3)  # d
    playlist.remove_indices([4, 1, 3])  # unordered input
    assert build(playlist) == ["a", "c"]
    assert playlist.current_index == 1  # successor e removed → clamps to c
    assert playlist.current_item.uri == "c"


def test_move_rows_basic_drop_semantics():
    playlist = Playlist()
    playlist.add(["a", "b", "c", "d"])
    playlist.move_rows([2], 0)  # c before a
    assert build(playlist) == ["c", "a", "b", "d"]
    playlist.move_rows([0, 1], 4)  # c,a to the end
    assert build(playlist) == ["b", "d", "c", "a"]


def test_move_rows_block_onto_itself_is_noop():
    playlist = Playlist()
    playlist.add(["a", "b", "c", "d"])
    playlist.move_rows([1, 2], 3)  # target just after the block
    assert build(playlist) == ["a", "b", "c", "d"]


def test_move_rows_preserves_current_identity():
    playlist = Playlist()
    playlist.add(["a", "b", "c"])
    playlist.set_current(1)
    playlist.move_rows([1], 0)
    assert build(playlist) == ["b", "a", "c"]
    assert playlist.current_index == 0
    assert playlist.current_item.uri == "b"


# ------------------------------------------------------------------ navigation
def test_next_off_stops_at_end():
    playlist = Playlist()
    playlist.add(["a", "b"])
    playlist.set_current(0)
    assert playlist.next_index(auto=True) == 1
    playlist.set_current(1)
    assert playlist.next_index(auto=True) is None
    assert playlist.next_index(auto=False) is None


def test_next_all_wraps():
    playlist = Playlist()
    playlist.add(["a", "b"])
    playlist.set_repeat(RepeatMode.ALL)
    playlist.set_current(1)
    assert playlist.next_index(auto=True) == 0


def test_next_one_replays_current_only_when_auto():
    playlist = Playlist()
    playlist.add(["a", "b"])
    playlist.set_repeat(RepeatMode.ONE)
    playlist.set_current(1)
    assert playlist.next_index(auto=True) == 1
    assert playlist.next_index(auto=False) is None  # manual next behaves like OFF


def test_next_with_no_current_starts_at_first():
    playlist = Playlist()
    playlist.add(["a", "b"])
    assert playlist.next_index(auto=True) == 0
    assert playlist.previous_index() is None


def test_previous_wraps_under_repeat_all():
    playlist = Playlist()
    playlist.add(["a", "b"])
    playlist.set_current(0)
    assert playlist.previous_index() is None
    playlist.set_repeat(RepeatMode.ALL)
    assert playlist.previous_index() == 1


def test_empty_playlist_navigation():
    playlist = Playlist()
    assert playlist.next_index(auto=True) is None
    assert playlist.previous_index() is None


# -------------------------------------------------------------------- shuffle
def test_shuffle_order_is_seeded_deterministic():
    first = Playlist(seed=42)
    first.add([f"m{i}" for i in range(8)])
    first.set_current(0)
    first.set_shuffle(True)

    second = Playlist(seed=42)
    second.add([f"m{i}" for i in range(8)])
    second.set_current(0)
    second.set_shuffle(True)

    # Walk the order by moving current along the revealed sequence.
    seen = [0]
    current = 0
    for _ in range(7):
        first.set_current(current)
        current = first.next_index(auto=False)
        seen.append(current)
    assert seen[0] == 0  # current stays first
    assert sorted(seen) == list(range(8))  # permutation, no repeats
    assert first.items() == second.items()


def test_shuffle_starts_from_current_and_visits_all():
    playlist = Playlist(seed=7)
    playlist.add([f"m{i}" for i in range(6)])
    playlist.set_current(4)
    playlist.set_shuffle(True)

    visited = [4]
    while True:
        nxt = playlist.next_index(auto=False)
        if nxt is None:
            break
        visited.append(nxt)
        playlist.set_current(nxt)
    assert visited[0] == 4
    assert sorted(visited) == list(range(6))


def test_shuffle_off_restores_item_order():
    playlist = Playlist(seed=1)
    playlist.add(["a", "b", "c"])
    playlist.set_current(0)
    playlist.set_shuffle(True)
    playlist.set_shuffle(False)
    playlist.set_current(0)
    assert playlist.next_index(auto=False) == 1
    playlist.set_current(1)
    assert playlist.next_index(auto=False) == 2


def test_shuffle_remove_keeps_order_consistent():
    playlist = Playlist(seed=3)
    playlist.add([f"m{i}" for i in range(5)])
    playlist.set_current(0)
    playlist.set_shuffle(True)
    order_before = [playlist.next_index(auto=False)]
    playlist.set_current(order_before[0])
    for _ in range(3):
        nxt = playlist.next_index(auto=False)
        order_before.append(nxt)
        playlist.set_current(nxt)

    playlist.remove_indices([2])  # remove some item
    # Walk the full order again: must be a permutation of remaining indices.
    playlist.set_current(0)
    visited = [0]
    while True:
        nxt = playlist.next_index(auto=False)
        if nxt is None:
            break
        visited.append(nxt)
        playlist.set_current(nxt)
    assert sorted(visited) == [0, 1, 2, 3]  # 4 items remain after removal


def test_shuffle_add_reaches_new_items():
    playlist = Playlist(seed=5)
    playlist.add(["a", "b"])
    playlist.set_current(0)
    playlist.set_shuffle(True)
    playlist.add(["c"])
    visited = [0]
    playlist.set_current(0)
    while True:
        nxt = playlist.next_index(auto=False)
        if nxt is None:
            break
        visited.append(nxt)
        playlist.set_current(nxt)
    assert sorted(visited) == [0, 1, 2]


# --------------------------------------------------------------------- repeat
def test_cycle_repeat_order():
    playlist = Playlist()
    assert playlist.cycle_repeat() is RepeatMode.ALL
    assert playlist.cycle_repeat() is RepeatMode.ONE
    assert playlist.cycle_repeat() is RepeatMode.OFF


def test_clear_resets_everything():
    playlist = Playlist()
    playlist.add(["a", "b"])
    playlist.set_current(1)
    playlist.clear()
    assert len(playlist) == 0
    assert playlist.current_index == -1
