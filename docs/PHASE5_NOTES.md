# Phase 5 — Engineering notes (2026-09-17)

## What was added

**Track introspection (backend level)**
- `track-list` is observed and parsed into engine-agnostic `TrackInfo`
  objects (`core/models.py`: id, kind, title, language, codec,
  default/forced/external/selected flags + a `display_name` for menus).
- The backend ABC grew the subtitle API: `tracks()`,
  `select_subtitle_track(id|None)`, `selected_subtitle_track()`,
  subtitle visibility, `add_subtitle_file(path, title)`, subtitle delay,
  and `set_subtitle_appearance(SubtitleAppearance)` / readback property.
- The controller exposes all of it plus `cycle_subtitles()` (VLC-style
  none → track 1 → … → none), `nudge_subtitle_delay()`,
  `reset_subtitle_delay()` and a `subtitleDelayChanged` signal for
  status-bar feedback.

**External subtitle auto-load (zero custom code)**
- `sub-auto=fuzzy` in the engine options: subtitle files whose name
  contains the video stem (`movie.srt`, `movie.en.srt` next to
  `movie.mkv`) are loaded by the engine itself and appear as external
  tracks. No directory scanning or matching code of our own — verified
  against libmpv 0.40.

**UI**
- New **Subtitles** menu: dynamic track list (exclusive group, rebuilt on
  every open so state is always fresh), "Add Subtitle File…", "Show
  Subtitles" toggle, Delay submenu (Earlier / Later / Reset with live
  status-bar readout), Appearance submenu (size, vertical position and
  color presets).
- New shortcuts: `J` cycle subtitles, `Z`/`X` delay earlier/later
  (0.1 s steps), `Shift+Z` reset.

## Engine facts established by probing (not guessing)

| Question | Answer (libmpv 0.40) |
|---|---|
| Disable subtitles via property | `sid = False` (readback `False`) |
| Sub delay semantics | `sub-delay` in seconds, signed; stored as **float32** (tests use `abs=1e-6`) |
| Color format | set accepts `#RRGGBB` / `#AARRGGBB`; **readback is `#AARRGGBB`** (alpha first) — `mpv_color_to_rgb()` helper converts |
| `sub-pos` semantics | vertical position in % of screen height, **100 = original (bottom) position, larger moves further DOWN**, range 0–150 |
| Auto-load with externals | `sub-auto=fuzzy` loads name-contains-stem matches **and auto-selects the first one** (a track is active right after open) |
| `sub-add` | `command("sub-add", path, "select", title)` adds an external track, marks it external in `track-list` and selects it |

The auto-select behavior (last row) was *discovered by a failing test* —
the suite assumed "nothing selected by default", which is only true when
no external files match. The tests now encode the real contract.

## Design decisions worth remembering

1. **Appearance presets instead of a dialog.** Full subtitle appearance
   editing (font picker, color picker, sliders) belongs to the Phase 7
   settings dialog; menus with presets stay honest and usable now.
   `SubtitleAppearance` is already a clean dataclass for that dialog.
2. **Partial appearance updates** build on the current readback
   (`set_subtitle_appearance(size=…)` keeps font/color/position) —
   verified by test.
3. **`add_subtitle_file` validates and reports through the normal error
   path** (missing file → `PlayerError(FILE_NOT_FOUND)` → banner), never
   raises into the UI.
4. Colors from users are validated (`#RRGGBB`/`#AARRGGBB`) before they
   reach the engine; invalid values are logged and ignored.

## Test coverage added

- `tests/player/test_subtitles.py` (10) — track events, embedded +
  auto-loaded externals, select/disable, manual add (+ select), missing
  file error, delay, visibility, appearance round-trip, invalid color,
  idle no-ops.
- `tests/ui/test_subtitles_integration.py` (7) — menu contents, cycle
  semantics from any starting selection, `J`/`Z`/`X`/`Shift+Z` shortcuts,
  status-bar feedback, appearance presets incl. partial-update survival,
  controller-level file add.
- Fixtures: `subtitle_media_dir` / `subtitle_mkv` / `external_srt`
  (ffmpeg-generated MKV with embedded SRT + two matching externals).

Totals: **143 tests green** (69 core, 23 player, 51 UI); lint clean.
