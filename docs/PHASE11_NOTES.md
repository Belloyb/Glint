# Phase 11 — Engineering notes (2026-09-18)

## What was done

Packaging: the project is now a correctly-built, correctly-bundled,
installable Python package — verified end-to-end in this sandbox — plus the
Windows distribution recipes and the redistribution licence review promised
in Phase 1.

## Changes

- **Assets moved into the package** (`assets/` → `app/assets/`, icons ship
  as package data via `[tool.setuptools.package-data]`). This closes a real
  bug found by building the wheel: package data outside a package is
  silently dropped, and the old `asset_dir()` computed a project-root
  relative path that resolves to `site-packages/assets` in an installed run
  — every icon would have been missing. Resolution order is now:
  `LUMEN_ASSETS_DIR` → frozen executable dir → `app/assets` next to the
  code (the last one covers both the source tree and wheel installs).
- **Support CLI** (`app/main.py`): `lumen --version` and `lumen --check`
  (preflight: engine library load, bundled icons, writable config dir;
  exits 0/1; prints a diagnostic report; runs without any display —
  designed for troubleshooting and packaging validation).
- **Redistribution licence review**: [`docs/REDISTRIBUTION.md`](REDISTRIBUTION.md)
  — component inventory (Lumen GPL-3.0-or-later, PySide6 LGPL-3.0,
  python-mpv GPL-2.0+, stock libmpv GPL-2.0+ incl. FFmpeg/libass,
  build tools PyInstaller/Inno Setup), compatibility analysis (all
  GPL-2.0+ components are upgrade-compatible with the project's
  GPL-3.0-or-later; LGPL obligations apply only when we ship Qt binaries),
  per-mode obligations (wheel vs installer), explicit warnings (verify the
  *exact* libmpv binary's build licence before shipping) and the final
  release checklist for Phase 12.
- **Windows distribution recipes** in [`packaging/`](../packaging/README.md):
  `lumen.spec` (PyInstaller onedir; icons listed as datas — they are not
  auto-collected; unused Qt modules excluded; UPX off for Qt DLLs; console
  off), `windows-installer.iss` (Inno Setup: GPL licence page, optional
  desktop icon and media file associations via HKCU, uninstaller leaves
  user config intact), `assoc-extensions.iss.inc` (reviewable extension
  list). **Clearly labelled: authored and reviewed, but not executable in
  this sandbox — validated on Windows hardware in Phase 12.**
- Tests: `tests/core/test_packaging.py` (8) — CLI flags (incl. the failure
  path with a broken assets dir), asset-dir resolution (must live inside
  the package, override honoured), config override, and a regression guard
  asserting the pyproject package-data glob still matches the shipped
  icons.

## Verification performed in this sandbox

1. `python -m pip wheel . --no-deps` builds
   `lumen_player-0.10.0-py3-none-any.whl` (rebuilt at 0.11.0 after the
   bump); zip listing shows all 19 icons under `app/assets/icons/`,
   entry point `lumen = app.main:main`, `License: GPL-3.0-or-later`,
   `Requires-Python: >=3.12`, LICENSE file included.
2. Installed the wheel into a clean target directory and ran, from a
   neutral cwd: `--version`, `--check` (PASS — assets resolve *inside the
   install*), and the generated `bin/lumen` console script.
3. Headless GUI boot **from the installed tree** under Xvfb: window shows,
   real (non-null) icons load, engine initialises, clean shutdown.
4. `lumen --check` green in the development tree; failure path verified
   (bogus `LUMEN_ASSETS_DIR` → FAIL, exit 1).

A first smoke run initially "failed" because it was launched from the
repository root — `python -m` prepends the cwd, so the dev tree shadowed
the install. The installed layout was then verified from a neutral
directory (recorded here so the mistake is not repeated).

## Verification status

| Suite | Result |
|---|---|
| `ruff check app tests` | clean |
| `tests/core tests/player` | **172 passed** (8 new packaging tests) |
| `tests/ui` (full, default order) | **96 passed — 3 consecutive runs** |
| **Total** | **268 passed** |

## Known limitations

- The PyInstaller spec and Inno Setup script have never run on Windows
  (no Windows hardware here) — Phase 12 validates and, if needed, adjusts
  them. They are documented as such everywhere they are mentioned.
- No sdist published to PyPI (publishing is a separate decision, not a
  phase goal); the wheel builds from the source tree.
- macOS is wheel-installable in principle but untested on real hardware
  (library name resolution via `find_library("mpv")` expects Homebrew's
  mpv).
- `--check` reports the *libmpv library* load, not a full playback
  pipeline (that stays in the test suite).

## Next step

Phase 12 — polish: real-GPU pixel verification and the Windows-hardware
validation of the packaging recipes, an in-app About/third-party-licenses
dialog (feeding off REDISTRIBUTION.md), language-code display names for
track menus, container-name prettifying in the info dialog, and the
software-GL warning banner — closing every "Phase 12" marker accumulated
since Phase 2.
