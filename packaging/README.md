# Building distributable Glint packages

Two distribution modes exist (see `docs/REDISTRIBUTION.md` for the licensing
analysis of each):

1. **Python package (wheel)** — works today on Linux/macOS/Windows:
   ```bash
   python -m pip wheel . --no-deps -w dist
   pip install dist/glint_player-*.whl      # pulls PySide6 + python-mpv
   glint --check                             # verify engine/assets/config
   ```
   On Windows the user additionally places `libmpv-2.dll` next to the
   package (or on `PATH`) — the loader in `app/player/mpv_backend.py`
   resolves it from the application directory first.

2. **Self-contained Windows build + installer** — artefacts in this folder:
   `glint.spec` (PyInstaller) and `windows-installer.iss` (Inno Setup).

   The PyInstaller half is **executed and validated** (Linux: frozen
   `--check` PASS, frozen GUI smoke test green — v0.12.7); the
   Windows-specific parts (exe icon/version resource, console attach,
   Inno compile) are validated on real hardware per
   `docs/HARDWARE_VALIDATION.md` §2.

## Windows build + installer (run on Windows 10/11 x64)

```powershell
# 0) Prerequisites (once): the dev environment, plus the two tools
pip install -e ".[dev]" pyinstaller
winget install JRSoftware.InnoSetup        # or https://jrsoftware.org/isdl.php
#   (after installing Inno Setup, reopen the terminal so iscc is on PATH)

# 1) libmpv-2.dll in the repository root is bundled automatically by the
#    spec (it is there if --check passes). Nothing to copy.

# 2) Build the onedir bundle
pyinstaller packaging\glint.spec

# 3) Smoke-test before packaging — must print preflight: PASS
dist\Glint\Glint.exe --check

# 4) Compile the installer (Inno Setup 6+)
iscc packaging\windows-installer.iss
#    -> dist\installer\GlintSetup-<version>.exe
```

Notes:

* `Glint.exe --check`/`--version` attach to the calling console (GUI
  binaries otherwise print nothing); double-clicking the exe just opens
  the player as usual.
* Keep the version in **four** places in sync — `pyproject.toml`,
  `app/__init__.py`, `packaging/windows-installer.iss` and
  `packaging/exe-version.txt` — a unit test enforces the agreement.
* End-user machines need the **Vulkan runtime** (`vulkan-1.dll`) because
  current libmpv builds import it; the installer warns when it is missing
  and points to the official LunarG download. `Glint --check` names the
  exact dependency if it bites later.

## Linux / macOS notes

* Linux: ship the wheel; the system package manager provides libmpv
  (`apt install libmpv2` on Debian/Ubuntu, `dnf install mpv-libs` on Fedora).
  The frozen build is also validated on Linux (`pyinstaller packaging/glint.spec`).
* macOS: needs real hardware for validation. `brew install mpv` provides
  the dylib; the wheel install path is expected to work unchanged apart
  from the library name resolution.

## Checklist before publishing any artefact

Reproduce `docs/REDISTRIBUTION.md` §5 (licence texts, source offers,
`--check` green on every platform, no VLC assets — grep the tree). For the
installer build specifically: the exact libmpv binary's version and source
URL must be recorded, GPL-3.0 text + REDISTRIBUTION.md ship in `doc\`,
and the source-offer for the GPL-2.0+ libmpv component must be stated in
the release announcement.
