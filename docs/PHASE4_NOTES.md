# Phase 4 — Engineering notes (2026-09-14)

## What was added

**Playlist core (Qt-free, `app/core/`)**
- `playlist.py` — items, current tracking by *identity* (removing rows before
  the current one never loses "now playing"), navigation (`next_index(auto)` /
  `previous_index()`) over a play order, seeded shuffle that always starts at
  the currently playing item, repeat OFF/ALL/ONE with VLC semantics
  (repeat-one only replays on *automatic* advance; a manual next moves on).
- `m3u.py` — M3U/M3U8 read+write: EXTINF durations/titles, relative-path
  resolution, UTF-8 BOM + Latin-1 fallback, hostile-input guards (line-length
  cap, entry cap), no execution of anything inside a playlist.
- `scanner.py` — extension-based media discovery (a *filter*, not a
  playability claim), recursive/non-recursive, unreadable directories logged
  and skipped, results sorted.
- `recents.py` — newest-first, de-duplicated, capped at 10, JSON-persisted,
  corrupt-file-safe.

**Orchestration (`app/player/queue.py`)**
- `PlaybackQueue`: the UI-facing API for queue-level operations
  (add/load/remove/move/clear, play_index, next/previous, shuffle/repeat).
- Auto-advance on end-of-media; skip-after-error with a consecutive-error
  guard (`max(3, playlist length)`) so a folder of corrupt files cannot
  loop forever.
- Removing the *currently playing* item keeps it playing to its end, then
  plays its successor (instead of skipping it) — tracked via an intent flag.
- Durations/titles of played items are back-filled from the engine
  (`mediaLoaded` + `durationChanged` — the duration arrives *after*
  file-loaded, a real timing detail the tests caught).

**UI (`app/ui/`)**
- `PlaylistPanel` + `PlaylistModel`: QListView with drag-reordering (custom
  MIME type), external file/URL drops at a position, "now playing" marker
  (accent + bold + ▶), footer with item count and accumulated duration,
  toolbar (add files/folder, remove, clear, shuffle, repeat, save, load),
  context menu, Delete-to-remove (panel-local key).
- `workers.py` — folder scanning on the global `QThreadPool` (UI never
  freezes); results delivered via signals.
- Main window: Playlist & View menus, recents submenu (rebuilt on show),
  previous/next buttons, drag-and-drop of files *and folders* anywhere on the
  window, status bar for transient feedback, dynamic idle/finished overlay
  text, `Ctrl+L` playlist toggle, `Ctrl+S` save playlist.
- New shortcuts now live: `N` (next), `P` (previous).

## Design decisions worth remembering

1. **Drops on folders scan recursively; the "Add Folder" dialog does not.**
   A drop is usually a whole library; an explicit dialog choice deserves
   predictable, shallow behaviour. Both are one-line changes if feedback
   says otherwise.

2. **`dropEvent` is a thin wrapper around `handle_dropped_urls(urls)`.**
   Synthesising `QDropEvent`s in PySide6 tests segfaults (`event.mimeData()`
   on a Python-constructed event); the behaviour lives in a plain method that
   is testable without Qt drag machinery. Real drag events reach the same
   code through the two-line wrapper.

3. **Playlist mutations adjust the shuffle order minimally** (insert appends
   to the order; removal filters+shifts it), *except* row moves, which
   rebuild the order around the current item — moving rows while shuffled
   otherwise desynchronises view and play order. Documented trade-off.

4. **Model resets on any mutation** (`beginResetModel`) — simple and robust;
  the playlist sizes involved do not warrant fine-grained row diffs yet.
  Revisit in the Phase 10 performance pass if profiling ever shows it.

5. **"Open File" replaces the playlist; "Add File(s)" appends** (VLC
  semantics). Drops append and start playback only when nothing is playing.

## Bugs found during this phase (all by tests)

- Queue-level: `mediaLoaded` carried `duration=None` (duration arrives via a
  separate `durationChanged` signal) → the queue now listens to both.
- Initialisation order: the Playlist menu referenced the playlist panel
  before the UI existed → connection deferred until after `_build_ui`.
- `QDropEvent` synthesis segfault → testable `handle_dropped_urls` (above).
- Shuffle-order removal: the play order is re-validated on every navigation
  and rebuilt if stale, making it self-healing.

## Test coverage added

- `tests/core/test_playlist.py` (18) — add/remove/move identity semantics,
  navigation across repeat modes, seeded-shuffle determinism and coverage.
- `tests/core/test_m3u.py` (10) — round-trip, relative paths, CRLF, BOM,
  Latin-1, hostile lines, orphan EXTINF.
- `tests/core/test_scanner.py` (6) — filtering, recursion, error paths.
- `tests/core/test_recents.py` (7) — ordering, cap, persistence, corruption.
- `tests/ui/test_queue.py` (15) — orchestration with a fake controller
  (fast, no engine): auto-advance, repeat-one, error-skip limits, the
  removed-current-item rule.
- `tests/ui/test_playlist_model.py` (8) — roles, marker, external/internal
  drops, malformed MIME.
- `tests/ui/test_playlist_integration.py` (7) — real-engine: auto-advance,
  repeat-one replay, error-skip, next/prev navigation + shortcuts, footer
  back-fill, dropped-folder scan-and-play through the thread pool.

Totals: **126 tests green** (69 core, 13 player, 44 UI); lint clean.
