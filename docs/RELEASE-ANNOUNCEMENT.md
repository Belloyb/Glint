# Glint 0.13.0 — release announcement (DRAFT)

> Fill in the bracketed `[FILL]` items before publishing (they depend on
> where you host the file and the source). Everything else is final text.
> This document is the last redistribution checkpoint required by
> `docs/REDISTRIBUTION.md` §5: it names every bundled component, its
> licence, its exact version and where its source can be obtained.

---

## Glint — a fast, original desktop media player

Glint is a free, open-source media player for Windows inspired by the
workflow classics (VLC among them) but built as an original project: its
own codebase, its own icon set and UI identity. It is **not** VLC, is not
affiliated with VideoLAN, and contains no VLC code or assets. Under the
hood it is powered by libmpv — the engine of the mpv player — which does
the decoding, so it plays what mpv plays.

**Highlights**

- Plays video and audio through libmpv (FFmpeg + libass underneath):
  MP4, MKV, WebM, MOV, AVI, MP3, FLAC, Opus, OGG, WAV, AAC/M4A and more
- Playlist with drag-and-drop (files *and* folders), shuffle, repeat
  (off/all/one), M3U8 save/load, recent files
- Subtitles: embedded + external tracks, automatic sidecar loading,
  delay control, appearance settings
- Hardware-accelerated video with graceful audio-only fallback
- Playback speed 0.25×–2× with pitch correction; frame stepping
- Volume up to 200% (100% = unity; above it is amplification, clearly
  marked in the UI)
- Fullscreen that is video-only, with auto-hiding controls
- Dark and light themes; keyboard-driven throughout
- Media information dialog with container/track details
- Network streams (HTTP/HTTPS direct URLs) with ICY title display

## System requirements

- Windows 10 or 11, 64-bit
- The **Vulkan runtime** (`vulkan-1.dll`) — present on most machines
  with a current GPU driver; the installer warns if it is missing and
  points to the official LunarG download
- ~400 MB disk space

## Download and install

- **`GlintSetup-0.13.0.exe`** — [FILL: download URL], `[FILL: size]` MB
- SHA-256: `[FILL: run "Get-FileHash dist\installer\GlintSetup-0.13.0.exe"
  and paste the hash here]`
- The installer needs **no administrator rights** (a per-machine option
  is offered). It shows the GPL-3.0 licence, and optionally creates a
  desktop icon and media file associations (18 formats, per-user,
  removed cleanly on uninstall).
- Uninstalling preserves your settings and logs in `%APPDATA%\glint`.

**SmartScreen note:** the installer is not code-signed (no signing
certificate yet), so Windows may show "Windows protected your PC".
Choose *More info → Run anyway* — or verify the SHA-256 above first.

**Verify an installation** (optional, from a terminal):

```
"C:\Program Files\Glint\Glint.exe" --check
```

(per-user install: `%LOCALAPPDATA%\Programs\Glint\Glint.exe --check`)

## Licensing and source offers (redistribution notice)

Glint and its distribution bundle contain these components:

| Component | Licence | Where its source is |
|---|---|---|
| Glint itself | GPL-3.0-or-later | [FILL: repository URL when published] |
| libmpv (media engine) | GPL-2.0+ | see below |
| python-mpv (engine binding) | GPL-2.0+ | https://github.com/jaseg/python-mpv |
| PySide6 / Qt 6 (UI toolkit) | LGPL-3.0 (with Qt exceptions) | https://code.qt.io/qt6/ — shipped as separate DLLs, user-replaceable |
| Python 3.13 runtime | PSF license | https://www.python.org/downloads/source/ |

**libmpv provenance:** the bundled engine is
**mpv v0.41.0-1012-ge8673660a** (x86_64) from the mpv-for-Windows
project: https://sourceforge.net/projects/mpv-player-windows/files/libmpv/
This binary is compiled from https://github.com/mpv-player/mpv with the
build system at https://github.com/shinchiro/mpv-winbuild-cmake and
incorporates **FFmpeg** and **libass**. The complete corresponding
source code for the GPL-licensed libmpv component (and the exact build
scripts) is available at the URLs above; `[FILL: contact/offering
statement — e.g. "a written offer to provide the exact source on
request for at least three years: <email>"]`.

The combined work is distributed under the terms of the GNU General
Public License version 3 or later (see `doc\LICENSE` and
`doc\REDISTRIBUTION.md` inside the installed folder). The installer was
produced with Inno Setup 6.7.3 (free for non-commercial use).

## Known limitations (honest list)

- Video over Remote Desktop / pure-software GL environments may show
  black (audio continues) — a limitation of mpv's renderer; play locally
  with hardware GL
- macOS is not yet validated (no hardware available to the project)
- Live streams have no duration display; some stream errors take up to
  30 s to surface
- ICY stream titles do not rewrite playlist rows
- The Linux build is validated (wheel + PyInstaller); macOS and the
  Python package on PyPI are future work

— the Glint contributors, 2026-09-22
