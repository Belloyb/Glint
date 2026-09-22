# Lumen Player — Phase 1: Architecture & Technology Decision

> Working title **"Lumen"** — a placeholder; final naming is an open decision (§12).
> This document is the Phase 1 deliverable: backend choice, architecture, structure,
> dependencies, roadmap, risks, cross-platform and licensing analysis.
> No application code is written until this plan is approved.

---

## 0. Executive summary

**Recommended stack**

| Layer | Choice | License |
|---|---|---|
| Language | Python 3.12+ (verified on 3.13) | PSF |
| GUI | **PySide6** (Qt 6) | LGPL-3.0 |
| Playback engine | **libmpv** (mpv's engine) | GPL-2.0+ default / LGPL-2.1+ build possible |
| Python↔engine bridge | **python-mpv** | GPL-2.0+/LGPL-2.1+ (follows libmpv) |
| Video embedding | mpv **render API** into a Qt `QOpenGLWidget` | — |

**Why:** your feature list (speed, frame stepping, audio/subtitle sync, aspect/crop,
screenshots, track selection, streams, hardware decode) maps almost 1:1 onto
libmpv commands and properties. mpv gives us a battle-tested FFmpeg + libass
playback core with excellent A/V sync, and — critically — one uniform embedding
path on Windows, Linux (X11 **and** Wayland) and macOS, with no per-platform
window-reparenting hacks.

**Verified, not assumed:** the engine was installed and exercised headlessly in the
development sandbox (Debian 13, libmpv 0.40, python-mpv 1.0.8). Load, duration,
accurate seek, pause, volume, track-list introspection, property observers and
log capture all work; a deliberately corrupt MKV fails cleanly with a capturable
error message and no crash. Details in §5.4.

**The one open variable is licensing intent.** Stock libmpv builds are GPL-2.0+;
if you want to keep a proprietary option open we either self-build libmpv as
LGPL or switch to libVLC (LGPL-2.1). The architecture below hedges this: the
engine sits behind a thin internal backend protocol, so a swap is contained to
one package.

---

## 1. Requirements → engine capability mapping

A key finding of this phase: **almost nothing in your requirements list needs to be
built at the media level.** It needs to be built at the *application* level (UI,
playlists, settings, shortcuts) and delegated to the engine.

| Requirement (your §1) | libmpv facility | Layer |
|---|---|---|
| Play/pause/stop/seek | `pause` property, `stop` / `seek` commands (`absolute+exact`) | backend |
| Volume / mute | `volume`, `mute` properties | backend |
| Playback speed (audio-corrected) | `speed` + `audio-pitch-correction` | backend |
| Frame stepping | `frame-step`, `frame-back-step` commands | backend |
| Audio / video / subtitle track selection | `track-list` property; `aid` / `vid` / `sid` | backend |
| Subtitles (SRT/ASS/VTT, embedded) | engine-side parsing + libass rendering; `sub-add` command | backend |
| Subtitle sync / audio sync | `sub-delay`, `audio-delay` | backend |
| Subtitle font/size/color/position | `sub-font`, `sub-font-size`, `sub-color`, `sub-pos`, `sub-scale` | backend |
| Aspect ratio / crop / zoom | `video-aspect-override`, `video-crop` (feature-detected), `video-zoom`, `video-pan-x/y` | backend |
| Deinterlacing | `deinterlace` | backend |
| Screenshot | `screenshot-to-file` (video mode) | backend |
| Hardware acceleration | `hwdec=auto-safe` (graceful software fallback) | backend |
| Network streams (HTTP/HLS/DASH/RTSP) | FFmpeg protocol layer; `network-timeout` | backend |
| Buffering/network state | `paused-for-cache`, `demuxer-cache-state` | backend |
| Media information | `duration`, `file-size`, `file-format`, `container-fps`, `video-params`, `audio-params`, `track-list` | backend |
| A/V synchronization, clock, drift correction | engine core (mpv's core competency) | engine |
| Playlist, shuffle/repeat, M3U, recents | — | **our core (Qt-free)** |
| Settings, themes, shortcuts, dialogs, DnD | — | **our UI/services** |

What we deliberately do **not** build: demuxers, decoders, A/V clocks, audio
output device management, subtitle renderers, protocol stacks. Those are the
engine's job. Our engineering value-add is the application around it.

---

## 2. Backend evaluation

### 2.1 What a playback engine actually does

"Play a video" is not one task. A real engine concurrently:

1. Demuxes containers (buffering, seeking indexes, attachment extraction)
2. Decodes audio and video (with hardware paths: DXVA/D3D11VA/NVDEC, VA-API, VideoToolbox)
3. Maintains the playback clock and corrects A/V drift (dropping/duplicating frames, resampling audio)
4. Owns audio output (WASAPI, CoreAudio, PulseAudio, PipeWire, ALSA)
5. Renders video with correct timing, color conversion, scaling, deinterlacing
6. Parses and renders subtitles (libass for ASS/SSA with font handling; SRT/VTT conversion)
7. Handles seeking semantics (keyframe vs. accurate), track switching, network retry/buffering

That is man-decades of work and it is exactly what the VLC and mpv teams do
full-time. Your spec explicitly (and correctly) forbids reimplementing it.

### 2.2 Candidates

#### (a) FFmpeg directly — PyAV / ctypes / CLI

FFmpeg is a codec/demux **toolbox**, not a player. Using it directly means we own
items 1–7 above, including cross-platform audio output (no good pure-Python
WASAPI/CoreAudio story), frame presentation timing, and libass integration.
Performance would suffer further because per-frame work would cross the GIL.
**Rejected as the engine** — exactly per your §2. PyAV remains a *candidate for
metadata probing only* in Phase 6 (BSD-3-Clause binding; wheels bundle FFmpeg
binaries — license notes would apply if adopted).

#### (b) GStreamer

A genuine application framework; `playbin` covers play/pause/seek/tracks, and
GStreamer powers real products. But for this project:

- GLib main loop must be integrated with Qt's event loop (extra moving part, subtle bugs)
- Bindings via PyGI are verbose, C-flavored, and GLib-level errors can abort the process without a Python traceback
- Subtitle story is weaker: `subparse` + pango is fine for SRT/VTT, but embedded ASS in MKV with font attachments is markedly less reliable than mpv/VLC
- Frame stepping, crop, screenshot are not first-class `playbin` features; each requires manual pipeline surgery
- Codec coverage depends on plugin sets (good/bad/ugly/libav) — the classic "user hits missing decoder" problem

Viable runner-up; rejected on integration friction and per-feature friction.

#### (c) libVLC

The engine of VLC. Enormous format coverage, robust, LGPL-2.1+, official
binaries from VideoLAN. Genuine strengths. The decisive weaknesses for us are in
**embedding and binding ergonomics**:

- Windows (HWND) and X11 embedding are easy; **native Wayland is not supported** (XWayland workaround)
- **macOS embedding into Qt is the classic pain point**: reparenting an NSView under Qt is fragile across macOS/Qt versions
- `python-vlc` is an auto-generated thin ctypes layer: C-style API, and the callback/threading discipline (never call back into libVLC from its own event threads) is entirely on us
- Feature list checks out (next-frame, take-snapshot, spu/audio delay, track APIs), but each is slightly more awkward than mpv's property model

**Designated fallback** — it becomes the primary if licensing requires LGPL-only
binaries (§9), and our backend abstraction keeps that swap cheap.

#### (d) libmpv — **recommended**

mpv is a modern engine built on FFmpeg + libass with a state-of-the-art renderer.
For a desktop player front-end it is the best fit:

- **Feature surface**: your requirements are almost literally mpv's command/property list (§1)
- **Embedding**: the render API renders into *our* OpenGL context — one code path on Windows, macOS, X11 **and** Wayland; no window reparenting; survives fullscreen toggles; we own the widget (so our own overlays, context menus, DnD just work)
- **python-mpv binding**: clean property-based API (`player.pause = True`, `player.vid = 2`), property observers, event callbacks, log handler — verified working (§5.4)
- **Playback quality**: mpv's A/V sync, seeking accuracy (`absolute+exact`), speed control with pitch correction, and libass subtitle rendering are best-in-class
- **Hardware decode**: `hwdec=auto-safe` with automatic software fallback

Trade-offs (honest):

- Default binary builds are **GPLv2+** (LGPL requires a self-build with `--enable-lgpl`) → §9 licensing gate
- mpv's property surface evolves between versions (renames, additions) → we pin a minimum version and feature-detect newer options
- python-mpv is a third-party binding (single primary maintainer) → mitigated by: it is small, pure, pure-ctypes; and our backend protocol contains the blast radius (worst case: vendor it or wrap libmpv directly)

### 2.3 Comparison table

| Criterion | Raw FFmpeg (PyAV) | GStreamer | libVLC | **libmpv** |
|---|---|---|---|---|
| What it is | codec toolkit | pipeline framework | full engine | full engine |
| Format coverage | excellent | very good (plugin-dependent) | excellent | excellent (FFmpeg-based) |
| A/V sync | **you build it** | built-in | built-in | built-in (excellent) |
| Subtitles (ASS esp.) | you build it (libass manual) | partial | excellent (libass) | excellent (libass) |
| HW decode | you plumb it per-platform | yes | yes | yes (`auto-safe`) |
| Qt embedding | you build it | per-platform overlay; Wayland OK; macOS fragile | Win/X11 easy; **Wayland = XWayland only**; **macOS fragile** | **render API: one path, all platforms** |
| Python binding | PyAV (good) | PyGI (verbose, GLib loop) | python-vlc (C-style) | python-mpv (clean, property-based) |
| Frame stepping | DIY | low-level STEP events | `next_frame()` | `frame-step` / `frame-back-step` |
| Screenshot | DIY | DIY (appsink) | `take_snapshot` | `screenshot-to-file` |
| Network streams | DIY protocols | plugins | excellent (VLC's stack) | excellent (FFmpeg protocols, HLS/DASH) |
| Engine license | LGPL-2.1+ / GPL build | LGPL core, plugin mix | **LGPL-2.1+** | GPL-2.0+ (LGPL build possible) |
| Effort to a reliable player | enormous | high | medium | **medium-low** |

### 2.4 Verdict

**libmpv**, embedded via its render API, wrapped in our own `PlayerBackend`
abstraction. libVLC is the pre-planned fallback if §9's licensing gate demands it.

---

## 3. Recommended architecture

### 3.1 Layering

```
┌────────────────────────────────────────────────────────────────┐
│ UI (PySide6)                                                   │
│   main_window · video_surface · controls · seekbar             │
│   playlist_panel · dialogs · context menus · theme (QSS)       │
│   → imports NOTHING from the player backend                    │
├────────────────────────────────────────────────────────────────┤
│ Application services (Qt objects, signal/slot API)             │
│   PlayerController · PlaylistModel · SettingsService           │
│   ShortcutManager · RecentFilesService · ScanWorkers           │
├────────────────────────────────────────────────────────────────┤
│ Player layer                                                   │
│   backend.py  — PlayerBackend protocol + events + types        │
│   mpv_backend.py — implementation (python-mpv)                 │
│   mpv_surface.py — QOpenGLWidget + mpv render context          │
│   (future: vlc_backend.py — the licensing hedge)               │
├────────────────────────────────────────────────────────────────┤
│ Core (Qt-free, pure Python — the unit-testable heart)          │
│   playlist · m3u persistence · settings schema                 │
│   shortcut config · data models · scanner · paths              │
└────────────────────────────────────────────────────────────────┘
                    ↓ beneath everything: libmpv (native)
```

Rules:

- **UI never imports mpv or the backend.** It talks to `PlayerController`
  (Qt signals/slots) — per your §6. The main window asks the controller for a
  *video surface widget* (`controller.create_video_surface(parent)`); whether
  that is an mpv GL surface or a libVLC native-window container is the backend's
  business.
- **Core never imports Qt.** Playlist logic, settings schema, M3U8 parsing,
  shortcut configuration are plain Python with dataclasses — testable in
  milliseconds without a display. (Verified: this sandbox runs the backend
  headless; CI can too.)
- **One composition root** (`app/application.py`): builds services, wires
  signals, hands them to the window. `main.py` stays ~20 lines.

### 3.2 The `PlayerBackend` contract (engine-agnostic)

```python
class PlayerBackend(Protocol):
    # lifecycle
    def create_video_surface(self, parent) -> "QWidget": ...
    def shutdown(self) -> None: ...
    # transport
    def open(self, uri: str) -> None: ...          # file path or URL
    def play(self) / pause(self) / stop(self) ...
    def seek(self, seconds: float, precise: bool = True) -> None: ...
    def step_frame(self, forward: bool = True) -> None: ...
    # output
    def set_volume(self, v: int) / set_mute(self, m: bool) / set_speed(self, s: float) ...
    # tracks & sync
    def select_track(self, kind: TrackKind, track_id: int | None) -> None: ...
    def set_delay(self, kind: TrackKind, seconds: float) -> None: ...
    def add_subtitle_file(self, path: str) -> None: ...
    # video
    def set_aspect(self, ratio: str) / set_crop(self, rect) / set_scale(self, s) ...
    def screenshot(self, path: str) -> None: ...
    # queries
    def properties(self) -> PlayerSnapshot: ...    # cached, cheap
```

Events flow one way, up, via callbacks that the controller *immediately*
converts to Qt signals:

`on_state_changed`, `on_media_loaded(MediaInfo)`, `on_tracks_changed(list[TrackInfo])`,
`on_position(float)`, `on_duration(float)`, `on_end_media(reason)`,
`on_buffering(bool)`, `on_error(PlayerError)`, `on_log(level, component, message)`.

`PlayerError` is a dataclass with a `PlayerErrorCode` enum (UnsupportedFormat,
FileNotFound, AccessDenied, DecoderFailed, AudioOutputFailed, NetworkFailed,
Timeout, Unknown) — enough for user-facing messages that actually help (§16 of
your spec), with technical detail reserved for the log.

### 3.3 Video path (libmpv render API in Qt)

- `QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)` **before** creating
  `QApplication` (in `main.py`). Without this, toggling fullscreen destroys the
  widget's native window and its GL context — the classic libmpv+Qt crash.
  With sharing, the mpv render context survives window-flag churn.
- `MpvVideoSurface(QOpenGLWidget)`:
  - `initializeGL` → create `mpv_render_context` using the widget's
    `getProcAddress`; `vo` forced to `libmpv`
  - `paintGL` → `mpv_render_context_render` into FBO 0 with current size and
    `flip_y` (Qt's origin is top-left)
  - mpv's "frame ready" callback fires on an mpv thread → the surface only
    schedules a queued repaint (`update()` via signal) — **never** renders from
    the mpv thread
  - teardown hooks into `context().aboutToBeDestroyed` (render context must die
    while GL is current) — the other classic pitfall
- `hwdec=auto-safe`: hardware decode when reliable, silent software fallback.

### 3.4 Threading laws (project-wide, enforced in review)

1. All backend calls happen on the **GUI thread**. `PlayerController` is the
   single gatekeeper (it also implements your §6 API: `player.open()`,
   `player.play()` … as thin, documented methods).
2. Engine callbacks arrive on **engine threads**. Inside a callback we do
   exactly one thing: emit a Qt signal (queued) or schedule a repaint. Never
   call back into the engine from a callback — python-mpv documents this as a
   deadlock hazard.
3. Folder scanning, file validation and playlist IO run on **QThreadPool
   workers**, returning results via signals (§10 of your spec: UI never freezes
   on big folders).
4. Core spawns **no threads** and imports **no Qt**.
5. **No busy-polling.** Position/duration/buffering arrive as engine property
   observers (measured: `time-pos` observer fires ~16×/s here — §5.4); the
   controller throttles UI updates to ~10 Hz so the seek bar is smooth but the
   Python/Qt overhead stays trivial. Everything else is event-driven.

### 3.5 State & data model

- `PlaybackState` enum: `Idle · Loading · Playing · Paused · Stopped · Ended · Error`
- Dataclasses in core: `MediaItem` (path, title, added_at), `TrackInfo`
  (id, kind, codec, language, title, is_default, is_forced, is_external),
  `MediaInfo` (duration, container, size, video params, audio params)
- `RepeatMode` enum: `Off · One · All`; shuffle implemented as an indexed
  playback order over the playlist (stable item list, shuffled *order*, so
  previous/next behave like VLC's)
- Settings: nested dataclasses ↔ versioned JSON, atomic writes
  (temp file + `os.replace`), invalid file ⇒ defaults + warning, never a crash

### 3.6 Persistence formats (decided now to avoid churn)

| Data | Format | Where |
|---|---|---|
| Settings | JSON (schema-versioned) | platform config dir (see §6) |
| Playlists (user saves) | **M3U8** (`#EXTM3U`, `#EXTINF:<duration>,<title>`) | user-chosen |
| Recent files | JSON (inside settings) | platform config dir |
| Resume positions | JSON (path → position, capped) | platform cache dir |

M3U8 is chosen for playlists because it is the interoperable lingua franca
(VLC/mpV/Winamp-family all read it); JSON stays for app-private data where
richness matters.

---

## 4. Project structure

```
lumen/                          # working title — root name TBD
├── app/
│   ├── __init__.py
│   ├── main.py                 # ~20 lines: AA_ShareOpenGLContexts, QApplication, run
│   ├── application.py          # composition root: build & wire services
│   │
│   ├── core/                   # NO Qt imports — pure, fast-tested logic
│   │   ├── __init__.py
│   │   ├── models.py           # MediaItem, TrackInfo, MediaInfo, enums
│   │   ├── playlist.py         # Playlist ops, shuffle order, repeat modes
│   │   ├── m3u.py              # M3U8/M3U read+write (defensive parsing)
│   │   ├── settings.py         # schema dataclasses ↔ JSON (versioned, atomic)
│   │   ├── shortcuts.py        # action enum, default bindings, config (de)serialization
│   │   ├── scanner.py          # media-file discovery/filtering (pure functions)
│   │   └── resume.py           # playback-position memory store (Phase 8)
│   │
│   ├── player/                 # engine layer
│   │   ├── __init__.py
│   │   ├── backend.py          # PlayerBackend protocol, event types, PlayerError
│   │   ├── mpv_backend.py      # python-mpv implementation
│   │   ├── mpv_surface.py      # QOpenGLWidget + render context (Qt glue)
│   │   └── controller.py       # PlayerController: Qt signal façade (your §6 API)
│   │
│   ├── ui/                     # PySide6 widgets only
│   │   ├── __init__.py
│   │   ├── main_window.py      # window, menus, layout, fullscreen, DnD target
│   │   ├── controls.py         # bottom control bar
│   │   ├── seekbar.py          # scrubbing-aware progress slider + time labels
│   │   ├── playlist_panel.py   # side panel (QAbstractListModel-backed)
│   │   ├── dialogs.py          # media info, settings, open-URL, errors
│   │   ├── theme.py            # QSS themes, spacing/typography tokens
│   │   └── resources.py        # SVG icon set (Qt resources)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logging.py          # rotating file + console, URL redaction
│       ├── paths.py            # config/cache/pictures dirs, Qt-free (XDG/APPDATA)
│       └── platform_.py        # OS detection, per-OS helpers
│
├── assets/
│   ├── icons/                  # app icon, custom glyphs (original identity)
│   └── themes/                 # dark.qss, light.qss
├── tests/
│   ├── core/                   # playlist, m3u, settings, shortcuts, scanner
│   ├── player/                 # backend contract tests (headless libmpv)
│   └── ui/                     # offscreen GUI smoke tests (pytest-qt, later)
├── docs/
│   └── PHASE1_ARCHITECTURE.md  # this file
├── pyproject.toml
├── requirements.txt            # dev convenience export
├── README.md                   # added in Phase 2, kept in sync from then on
└── LICENSE                     # chosen after §9 decision (placeholder until then)
```

**Deviations from your proposed layout, and why** (per your §4 "explain changes"):

1. **`core/` replaces `settings/`, `playlist/`, `shortcuts/` as separate
   packages.** The important boundary is *Qt-free vs Qt*, not feature-vs-feature.
   One package with that boundary enforced makes the rule obvious and the test
   suite instant.
2. **`player/` merges `playback.py`/`tracks.py`/`subtitles.py`/
   `synchronization.py`.** With libmpv those "subsystems" are not subsystems —
   they are property assignments on one handle. Five files each wrapping the
   same handle would be ceremony, not architecture. They reappear naturally as
   *methods* on the backend + dataclasses in `core/models.py`.
3. **`media/` is deferred.** `scanner.py` moves to `core` (it must be threadable
   and Qt-free); `media_info`/`metadata` are satisfied by the engine
   (`track-list`, `video-params`, … — verified in §5.4). If Phase 6 needs deeper
   probing than the engine gives, a `core/probe.py` (PyAV or ffprobe subprocess)
   is added then, with its own license review.
4. **`application.py` added** (composition root) — keeps `main.py` trivial and
   service wiring explicit and testable.
5. **`mpv_surface.py` lives in `player/`**, not `ui/` — it is engine glue. The
   UI receives it as an opaque widget via the controller, preserving rule 3.1.

---

## 5. Dependencies

### 5.1 Runtime (the entire list — deliberately tiny)

| Dependency | What / why | Alternatives considered | License | Platforms | Packaging impact |
|---|---|---|---|---|---|
| **PySide6** | Qt 6 GUI: widgets, dialogs, DnD, OpenGL widget, SVG icons, accessibility. The only realistic modern Python desktop toolkit. | Tkinter (inadequate), wxPython (stagnant), Dear PyGui (not desktop-native) | LGPL-3.0 (official Qt for Python) | Win/Linux/macOS wheels | PyInstaller bundles it; large but standard |
| **python-mpv** | ctypes bindings to libmpv; property API, observers, events, log handler (all verified §5.4). | hand-rolled ctypes (unnecessary), libmpv via cffi (no benefit) | GPL-2.0+/LGPL-2.1+ — follows the libmpv build you link (project README) | pure Python | trivial (one module) |
| **libmpv** (native, not pip) | the entire media engine: FFmpeg demux/decode + libass subtitles + sync + outputs + protocols | libVLC, GStreamer (§2) | GPL-2.0+ default; **LGPL-2.1+ if built `--enable-lgpl`** (mpv README) | system package / bundled DLL/dylib | the main packaging task (§Phase 11) |

**Not needed** — explicitly rejected to keep the tree clean: no subtitle parser
(engine handles SRT/ASS/VTT), no audio library (engine owns output), no FFmpeg
CLI (engine embeds FFmpeg), no metadata library until Phase 6 says otherwise.

### 5.2 Development-only

`pytest` (MIT) from Phase 2; `pytest-qt` when GUI tests begin (Phase 3/4);
`ruff` + `mypy` optional but recommended from Phase 2.

### 5.3 Install matrix (per OS)

| | Command |
|---|---|
| **Windows 10/11** | `winget install Python.Python.3.12` → `pip install PySide6 python-mpv` → download **mpv-dev** build (contains `libmpv-2.dll`) from the mpv-for-Windows project (SourceForge `mpv-player-windows/libmpv`, x86_64) → place `libmpv-2.dll` in the project dir (our loader finds it there first) |
| **Debian/Ubuntu** | `sudo apt install libmpv2` → `pip install PySide6 python-mpv` |
| **Fedora** | `sudo dnf install mpv-libs` → pip as above |
| **Arch** | `sudo pacman -S mpv` → pip as above |
| **macOS** | `brew install mpv` (provides libmpv) → pip as above |

Minimum versions: **Python 3.12**, **PySide6 ≥ 6.6**, **libmpv ≥ 0.35**
(recommend ≥ 0.37; newer options like `video-crop` are feature-detected at
runtime with graceful fallback), **python-mpv ≥ 1.0**.

### 5.4 What was actually verified today (2026-09-13, Debian 13 sandbox)

```
libmpv2 0.40.0 installed via apt; python-mpv 1.0.8 via pip
Generated 3 s WAV; played headless (vo=null, ao=null):
  duration: 3.0                          ← property read
  media-title: tone.wav
  time-pos after seek(1.0, absolute+exact): 1.29   ← accurate seek works
  paused: True / volume: 37.0            ← property writes work
  track-list: [{'id': 1, 'type': 'audio', 'codec': 'pcm_s16le',
                'codec-desc': 'PCM signed 16-bit little-endian',
                'demux-samplerate': 8000, 'demux-channels': 'mono',
                'demux-bitrate': 128000, ...}]     ← rich track introspection
  wait_for_playback returned after 1.3 s
  time-pos observer samples: 28          ← ~16 Hz event rate → event-driven UI viable
Corrupt MKV (random bytes):
  wait_for_playback returned normally; no crash
  mpv log captured: [error/cplayer] Failed to recognize file format.
  → error path: watch end-file reason + engine log → PlayerError → UI banner
SMOKE TEST OK
```

This becomes the seed of `tests/player/test_mpv_backend_contract.py` — the
backend can be CI-tested without any display.

---

## 6. Cross-platform considerations

| Area | Windows | Linux | macOS |
|---|---|---|---|
| libmpv source | bundled `libmpv-2.dll` (app dir → PATH) | distro package (or bundled in AppImage) | brew dylib; bundled into `.app` at packaging time |
| Video embedding | render API into QOpenGLWidget — same code | same (X11 **and** Wayland native) | same |
| Wayland | n/a | render API immune to the X11-window-ID problem that hits libVLC/embedding approaches; DnD/clipboard via Qt | n/a |
| HiDPI | Qt 6 per-monitor v2 DPI; SVG icons | same; fractional scaling | Retina: render with device-pixel-correct framebuffer size |
| Dark/light chrome | dark titlebar via DWM attribute / Qt 6.8 color scheme hints | follows toolkit theme | dark mode supported |
| Menus/keys | standard menu bar | standard | **global menu bar convention; `Cmd`-based shortcuts; `Cmd+,` for Settings** — ShortcutManager carries per-OS defaults |
| Packaging (Phase 11) | PyInstaller → exe + bundled DLLs | PyInstaller → AppImage (bundle libmpv) or system-depend .deb | PyInstaller → `.app`; dylib `@rpath` fixes, ad-hoc signing for local use; Developer ID + notarization for distribution |
| Known gaps | — | mix of distro libmpv versions (min 0.35 + feature detection handles it) | I can develop/test Windows-adjacent and Linux in sandbox; **macOS must be tested on real hardware by you** — flagged as a standing item |

Fullscreen is implemented at the **window level** (`showFullScreen()`), not via
mpv — under the render API mpv never owns a window, so `set_fullscreen` lives on
the main window / controller façade, not the backend protocol (documented
deviation from your §6 sketch, for a technical reason).

---

## 7. Development roadmap (mapping your 12 phases)

Each phase ships **code + tests + a manual checklist**, and the app must run at
the end of every phase (your §20). Acceptance criteria listed are the gates.

| Phase | Deliverables | Acceptance criteria |
|---|---|---|
| **2 — Minimal player** | `main.py`, `application.py`, `main_window`, `mpv_surface`, `mpv_backend`, `controller`, basic `controls` + `seekbar`, logging, error banner/dialog, Open File | Launches dark UI; plays MP4/MKV/MP3; play/pause/stop/seek/volume+mute work; missing & corrupt files → clean error, logged; exits cleanly mid-playback; backend contract test green headless |
| **3 — Pro controls** | Fullscreen + auto-hiding controls + cursor hide; `core/shortcuts.py` + `ShortcutManager` (configurable, conflict detection); mouse rules (dblclick, wheel, right-click menu); speed menu; frame step; tooltips | Shortcut config round-trip unit test; manual keyboard/mouse checklist; fullscreen survives GL context (the §3.3 pitfall) |
| **4 — Playlist** | `core/playlist.py`, `m3u.py`, `playlist_panel`, shuffle/repeat, auto-advance, save/load M3U8, recents, folder scan workers, app-level DnD | Unit tests: playlist ops, seeded-shuffle determinism, M3U8 round-trip incl. hostile lines; 10k-file folder scan doesn't freeze UI |
| **5 — Subtitles** | Track menu, enable/disable, external sub load + auto-match by filename, delay nudge, appearance settings (font/size/color/position) | Manual matrix: SRT/ASS/VTT × embedded/external; no custom parser shipped |
| **6 — Media info** | Info dialog from engine properties; optional `core/probe.py` (decision + license review then) | Correct info incl. multi-audio MKV; copy-to-clipboard |
| **7 — Settings** | Settings dialog (Playback/Interface/Subtitles/Audio/Video), live apply, defaults, reset | Settings unit tests: defaults, versioned migration, atomic write, corrupt-file recovery |
| **8 — Advanced playback** | Audio/video track menus, audio+sub delay, aspect/crop/zoom menus, screenshot (with toast), precise frame step, resume-position memory | Feature-detected `video-crop` falls back cleanly on old libmpv; resume works across restart |
| **9 — Streaming** | Open URL (http(s)/HLS/DASH/RTSP), buffering indicator (`paused-for-cache`), timeouts, surfaced network errors; optional yt-dlp integration (off by default, documented) | Streams play with buffering UI; dead URL → clean timeout error, no hang |
| **10 — Performance** | Profile startup, memory, UI update rates (py-spy, tracemalloc, QElapsedTimer); fix measured bottlenecks only | Numbers documented in README before/after |
| **11 — Packaging** | PyInstaller per OS; libmpv bundling; macOS signing/notarization docs; **license compliance kit** (§9 review) | App runs from the artifact on each OS |
| **12 — Polish** | Light theme final, accessibility pass (tab order, names, contrast), error-copy review, README w/ screenshots, full suite green, CHANGELOG | Manual QA checklist per OS |

---

## 8. Major technical risks & mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **GL context loss on fullscreen/window-flag changes** (classic Qt+libmpv crash) | certain if unhandled | crash | `AA_ShareOpenGLContexts` before QApplication (§3.3); explicit teardown order; tested in Phase 3 acceptance |
| 2 | **Deadlock by calling engine from its own callbacks** | high if careless | freeze | Threading law #2 (§3.4); callbacks only emit queued Qt signals; enforced in review |
| 3 | **libmpv version/property drift across distros** | medium | feature gaps | min-version check at startup + runtime feature detection with fallbacks |
| 4 | **GPL exposure if we later want proprietary distribution** | decided now | licensing | §9 decision gate + `PlayerBackend` protocol hedge (libVLC swap contained) |
| 5 | **macOS unbundled-dylib/signing pain** | medium (packaging-time) | delay | Dedicated work in Phase 11; early `@rpath` discipline; real-hardware testing flagged |
| 6 | **Pathological media (hangs instead of failing)** | low-medium | hang | engine `network-timeout`, load watchdog (stuck-in-Loading state → offer skip), contract tests with corrupt inputs |
| 7 | **python-mpv maintenance risk** | low | moderate | small pure-ctypes dep; vendorable; backend protocol contains the surface |
| 8 | **Python overhead on UI updates** | low | jank | event-driven + 10 Hz throttle (§3.4 law 5); zero per-frame Python work (render stays native) |
| 9 | **Screenshot limitations under render API** (`window` capture mode unavailable) | certain but known | minor | use mpv `screenshot-to-file` **video** mode (decoder frame — verified feature of libmpv); documented |
| 10 | **Codec patent reality** (H.264/HEVC/AAC decoders patent-encumbered in some jurisdictions) | inherent | legal | affects *every* player equally; noted in §9; not legal advice |

---

## 9. Licensing analysis (verified against primary sources, 2026-09-13)

Facts with sources:

1. **mpv/libmpv**: *"GPLv2 'or later' by default, LGPLv2.1 'or later' with
   --enable-lgpl"* — mpv repository README. Stock distro packages and the
   Windows mpv-dev builds are GPL.
2. **python-mpv**: dual **GPL-2.0+/LGPL-2.1+** — the project states it follows
   the license of the libmpv build it is used with.
3. **libVLC**: **LGPL-2.1+** (relicensed by VideoLAN in 2011; the VLC *app*
   remains GPL-2+). VideoLAN's own wiki states proprietary apps are possible
   under LGPL terms (dynamic linking strongly advised, LGPL-only plugin set
   strongly advised — official VLC binaries contain some GPL plugins that a
   proprietary bundler must exclude).
4. **python-vlc**: **LGPL-2.1+** (PyPI metadata).
5. **PySide6**: **LGPL-3.0** — usable with open or closed source under LGPL
   terms (notices, allow user relinking, dynamic linking).
6. **FFmpeg** (embedded inside every engine above): LGPL-2.1+ by default, GPL-2+
   if built `--enable-gpl`. Codec **patents** (H.264, HEVC, AAC…) are a separate,
   jurisdiction-dependent issue that applies to any player; not legal advice.
7. **libass** (subtitle renderer, via mpv/VLC): ISC (permissive).
8. **PyAV** (optional, Phase 6 only): BSD-3-Clause binding, wheels bundle
   FFmpeg binaries (their LGPL notices would apply if adopted).

### The decision, and the two paths

**Path A (recommended): open-source, license the app GPL-3.0-or-later.**
Everything composes cleanly under one license: libmpv (GPLv2+ → choose GPLv3+),
PySide6 (LGPL-3 ↔ GPL-3 compatible), python-mpv (either). We may bundle stock
libmpv binaries everywhere. Simplest, most capable, zero licensing work beyond
standard GPL hygiene (license texts, source offer, notices).

**Path B: keep a proprietary option open.** Then either (a) self-build libmpv
with `--enable-lgpl` on all three platforms (real packaging burden), or
(b) switch to **libVLC** (LGPL-2.1) + `python-vlc`, and at bundling time use an
LGPL-only plugin set. PySide6 LGPL-3 compliance applies on this path.

Per your §23, the **final redistribution review happens at Phase 11** with the
actual artifact in hand. I am an engineer, not a lawyer; if this will be
commercially distributed, get a review at that point.

---

## 10. Security design (your §24, concretized)

- Media files, playlists, subtitle files, settings files and URLs are
  **untrusted input**.
- **No shell, ever.** If Phase 6/9 adds ffprobe or yt-dlp: `subprocess` with
  list arguments, never `shell=True`, timeouts, bounded output capture.
- Engine hardening: `config=False` (ignore any user `mpv.conf`), scripts
  disabled, `ytdl=False` until Phase 9 makes an explicit, documented choice.
- M3U8 parser: length caps, defensive UTF-8, scheme allow-list for non-file
  entries; nothing from a playlist is ever *executed*.
- Settings JSON: schema-validated on load; corrupt ⇒ defaults + warning.
- Logging: URLs redacted of `user:pass@`; no environment dumps.
- Filenames are data — never interpolated into commands or paths unsafely.

---

## 11. Testing strategy

- **Unit (fast, no display)**: `core/` — playlist ops, shuffle determinism
  (seeded), repeat state machine, M3U8 round-trip + hostile inputs, settings
  defaults/migration/atomicity, shortcut config validation, scanner filtering.
- **Backend contract (headless)**: `MpvBackend` against real libmpv with
  `vo=null`/`ao=null` — today's smoke test (§5.4) is the seed; runs in CI.
- **GUI (later phases)**: pytest-qt with `QT_QPA_PLATFORM=offscreen` for smoke
  ("window builds, signals fire"); per-OS **manual checklists** are first-class
  acceptance criteria because rendering/audio truly need a desktop.
- **Rule**: a feature and its tests ship in the same phase.

---

## 12. Open decisions (blocking Phase 2)

1. **License path** — A (GPL-3.0-or-later, stock libmpv) or B (proprietary
   option → libVLC or LGPL libmpv build). This is the one decision that changes
   the stack.
2. **Primary development/test OS** — determines which platform gets the tightest
   early validation (I verify Linux headlessly in-sandbox; Windows via your
   testing; macOS flagged for hardware).
3. **Application name** — "Lumen" is a placeholder; naming doesn't block Phase 2
   (a rename is mechanical), but nice to settle early.

---

*End of Phase 1. Awaiting approval before any application code is written.*
