# Phase 3 — Engineering notes (2026-09-14)

## What was added

- **Fullscreen** (`F` / double-click / menu / context menu) with auto-hiding
  chrome: controls and cursor hide after 2.5 s idle in fullscreen, any mouse
  activity reveals them (`app/ui/autohide.py`). Menu bar is hidden in
  fullscreen; maximized state is restored on exit.
- **Centralised shortcuts** (`app/core/shortcuts.py` — Qt-free, fully unit
  tested; `app/ui/shortcuts.py` — Qt binding layer). Configurable via
  `<config dir>/shortcuts.json` (partial files merge with defaults; empty
  lists unbind; unknown actions ignored for forward compatibility; conflicts
  are detected and reported). Actions for later phases (next/previous track,
  screenshot) are already declared with stable IDs but not bound.
- **Mouse rules** (`app/ui/video_area.py`): double-click → fullscreen;
  single-click → play/pause; wheel → volume ±5; right-click → context menu;
  movement → activity (auto-hide poke).
- **Playback speed**: presets 0.25×–2× via `[` / `]` / `Backspace`, a speed
  menu in the control bar, the Playback menu and the context menu
  (audio pitch correction stays on, engine-side).
- **Frame stepping**: `.` / `,` / context menu (frame-back-step requires
  libmpv ≥ 0.35 — matches our minimum).
- **Responsive control bar**: volume slider collapses below 640 px width,
  total-time label below 520 px.

## Design decisions worth remembering

1. **Single-click pause is delayed by 260 ms.** The first click of a
   double-click would otherwise pause before the fullscreen toggle (the
   behaviour VLC accepts); the small delay lets us cancel the pause when a
   double-click arrives. The trade-off (imperceptible pause latency) is
   tested: `test_double_click_fullscreen_without_pause`.

2. **The video surface gets an event filter, not subclassing.** The backend
   hands us an opaque widget (a `QOpenGLWidget` we do not want the UI to
   depend on). `VideoArea.set_surface()` installs an event filter on it and
   consumes the mouse events it handles — one code path for events landing on
   the surface and on the area itself, no double delivery. Verified by
   `test_single_click_on_surface_child_pauses`.

3. **macOS shortcut convention**: `ShortcutManager._platform_sequence`
   translates `Ctrl+X` → `Cmd+X` on darwin at bind time; the portable strings
   stay canonical in config files.

4. **Menu-bar fullscreen action defers via `QTimer.singleShot(0)`** — it
   hides the menu bar while its own menu is still closing; deferring avoids
   platform quirks during teardown.

5. **`frame-back-step` transiently unpauses.** mpv internally flips
   `pause=False` for ~40 ms during the backward seek, then re-pauses itself
   (measured; the pause observer saw the flicker). The backend now ignores
   engine-driven *unpause* events while we still intend to be paused
   (`_pause_requested`), so the UI no longer flickers
   PLAYING→PAUSED. Intent flags are cleared by `play()`/`stop()`/`open()`,
   so user-initiated unpause still works normally.

## Environment finding (testing)

Under **Xvfb without a window manager**, `QApplication.activeWindow()` is
`None` and Qt never marks shown windows active — `QShortcut`
(WindowShortcut context) then matches nothing. This is a *test-environment*
artifact (real desktops always activate windows); the UI-test fixture calls
`window.activateWindow()` explicitly. Diagnosed by observing that `Space`
still toggled playback — via the focused play *button*, not the shortcut.

## Test coverage added

- `tests/core/test_shortcuts.py` (16) — defaults, normalisation, merging,
  unbinding, conflicts, round-trip, corrupt-file fallback.
- `tests/core/test_playback.py` (5) — speed clamping and preset stepping.
- `tests/player/test_speed_and_frames.py` (4) — engine speed contract,
  frame-step pause semantics, idle no-ops.
- `tests/ui/test_controls.py` (13) — shortcuts (space/volume/mute/speed/
  seek), fullscreen + Esc, auto-hide reveal/hide, double-click vs
  single-click, wheel over area *and* over the GL child, context-menu signal.

Totals: 48 tests green (21 core, 13 player, 14 UI); lint clean.
