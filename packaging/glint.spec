# -*- coding: utf-8 -*-
# PyInstaller spec for Glint (Windows onedir build).
#
# Build (from the repository root, on Windows, inside the dev environment):
#     pyinstaller packaging/glint.spec
#
# Result: dist/Glint/ — a self-contained folder with Glint.exe, the Qt
# runtime and (when libmpv-2.dll sits in the repository root at build
# time, the documented Windows layout) the media engine. See
# packaging/README.md for the full Windows release pipeline and
# docs/REDISTRIBUTION.md for the licensing obligations.
#
# NOTE: executed and validated on Linux (frozen --check PASS, app smoke
# test); the Windows-specific parts (exe icon, version resource, the
# installer) are validated on real hardware per docs/HARDWARE_VALIDATION
# §2.

from pathlib import Path

# SPECPATH is the directory containing this spec (…/glint/packaging).
root = Path(SPECPATH).resolve().parent

# Bundle the media engine automatically when it sits in the repository
# root (the documented Windows layout). PyInstaller places it in the
# bundle directory (_internal); the loader in app/player/mpv_backend.py
# probes sys._MEIPASS, so this "just works" in the frozen app.
binaries = []
libmpv = root / "libmpv-2.dll"
if libmpv.is_file():
    binaries.append((str(libmpv), "."))

a = Analysis(
    # Absolute: PyInstaller resolves relative script paths against the
    # spec's directory (packaging/), not the build CWD.
    [str(root / "app" / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=[
        # Icons ship as package data; the frozen app resolves them via
        # sys._MEIPASS (app/utils/paths.py), which is where datas land
        # ("assets/icons" destination = <_MEIPASS>/assets/icons).
        (str(root / "app" / "assets" / "icons" / "*.svg"), "assets/icons"),
    ],
    hiddenimports=[
        "app.main",
        # Imported lazily inside main() for --check-without-engine; listed
        # explicitly so a future refactor to a dynamic import cannot
        # silently drop it from the bundle.
        "app.application",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Trim the Qt packages Glint never imports (smaller bundle).
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtXml",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Glint",
    debug=False,
    strip=False,
    upx=False,  # UPX on Qt DLLs is a known source of breakage/AV false hits
    console=False,  # GUI application; logs go to the rotating file.
    # --version/--check attach to the caller's console via AttachConsole
    # (app.main._attach_parent_console), so diagnostics stay visible.
    icon=str(root / "app" / "assets" / "icons" / "app.ico"),
    version=str(root / "packaging" / "exe-version.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Glint",
)
