"""Application entry point.

Run with::

    python -m app.main        # or: glint (installed console script)

Support options (processed before any Qt machinery starts):

* ``--version`` — print the version and exit.
* ``--check``   — preflight: verify the engine library, assets and config
  directory, print a diagnostic report, exit 0/1 (support & packaging aid).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import struct
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app import __version__
from app.utils.paths import asset_dir, config_dir, project_root

_WINDOWS_DLL_NAMES = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")


#: Common runtime dependencies of Windows libmpv builds, with the fix for
#: each. ``--check`` probes these when libmpv-2.dll exists but will not load
#: ("or one of its dependencies" — Windows does not say *which* one).
_MINGW_RUNTIME_FIX = (
    "MinGW runtime dll — copy it next to libmpv-2.dll; it ships inside the "
    "mpv *player* package from the same SourceForge project "
    "(mpv-x86_64-*.7z), or in any MSYS2 mingw-w64 installation"
)

#: Advice per runtime dll commonly imported dynamically by libmpv builds.
#: ``--check`` reports only what the engine's own import table actually
#: needs (see :func:`_pe_imported_dlls`); this table supplies the fix.
_RUNTIME_ADVICE: dict[str, str] = {
    "msvcp140.dll": "install the Microsoft Visual C++ 2015-2022 Redistributable (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe",
    "vcruntime140.dll": "install the Microsoft Visual C++ 2015-2022 Redistributable (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe",
    "vcruntime140_1.dll": "install the Microsoft Visual C++ 2015-2022 Redistributable (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe",
    "libwinpthread-1.dll": _MINGW_RUNTIME_FIX,
    "libgcc_s_seh-1.dll": _MINGW_RUNTIME_FIX,
    "libstdc++-6.dll": _MINGW_RUNTIME_FIX,
    "libunwind.dll": _MINGW_RUNTIME_FIX,
    "vulkan-1.dll": (
        "install the official Vulkan Runtime from https://vulkan.lunarg.com/sdk/home "
        "(Runtime Installer, Windows x64) — or update your GPU driver, which normally "
        "includes it; no Vulkan-capable GPU is needed, the loader just has to exist"
    ),
}


def _pe_imported_dlls(path: Path) -> tuple[str | None, list[str]]:
    """Read a PE file's import table (pure stdlib, never raises).

    Returns ``(machine, imported_dll_names)`` — machine is ``"x64"`` /
    ``"ARM64"`` / ``"x86"``, or ``None`` when the file is not a parsable PE.
    """
    machines = {0x8664: "x64", 0xAA64: "ARM64", 0x014C: "x86"}
    try:
        with open(path, "rb") as handle:

            def read(offset: int, size: int) -> bytes:
                handle.seek(offset)
                return handle.read(size)

            if read(0, 2) != b"MZ":
                return None, []
            (e_lfanew,) = struct.unpack("<I", read(0x3C, 4))
            if read(e_lfanew, 4) != b"PE\x00\x00":
                return None, []
            machine_code, num_sections, _, _, _, size_opt, _ = struct.unpack(
                "<HHIIIHH", read(e_lfanew + 4, 20)
            )
            machine = machines.get(machine_code)
            optional = e_lfanew + 24
            (magic,) = struct.unpack("<H", read(optional, 2))
            if magic not in (0x10B, 0x20B):
                return machine, []
            data_dir = optional + (96 if magic == 0x10B else 112)
            import_rva, _size = struct.unpack("<II", read(data_dir + 8, 8))
            if import_rva == 0:
                return machine, []

            sections: list[tuple[int, int, int]] = []
            table = optional + size_opt
            for index in range(min(num_sections, 96)):
                entry = read(table + index * 40, 40)
                if len(entry) < 40:
                    break
                virtual_address, size_raw, pointer_raw = struct.unpack("<III", entry[12:24])
                sections.append((virtual_address, size_raw, pointer_raw))

            def rva_to_offset(rva: int) -> int | None:
                for virtual_address, size_raw, pointer_raw in sections:
                    if virtual_address <= rva < virtual_address + size_raw:
                        return rva - virtual_address + pointer_raw
                return None

            base = rva_to_offset(import_rva)
            if base is None:
                return machine, []
            names: list[str] = []
            for index in range(2048):  # sanity cap on descriptor count
                chunk = read(base + index * 20, 20)
                if len(chunk) < 20 or chunk == b"\x00" * 20:
                    break
                (name_rva,) = struct.unpack("<I", chunk[12:16])
                name_offset = rva_to_offset(name_rva)
                if name_offset is None:
                    continue
                raw = read(name_offset, 260)
                name = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
                if name:
                    names.append(name)
            return machine, names
    except (OSError, ValueError, struct.error):
        return None, []


def _loadable(name: str) -> bool:
    try:
        ctypes.CDLL(name)
    except OSError:
        return False
    return True


def _arch_problem(machine: str | None) -> str | None:
    if machine is None:
        return None
    host = platform.machine().upper()  # AMD64 (Win) / X86_64 (Linux) / ARM64 / X86
    expected = {
        "AMD64": "x64",
        "X86_64": "x64",
        "ARM64": "ARM64",
        "X86": "x86",
        "I386": "x86",
        "I686": "x86",
    }.get(host)
    if expected and machine != expected:
        return (
            f"architecture mismatch — the dll is a {machine} build but this "
            f"Python is running {host}; download the {expected} mpv-dev package"
        )
    return None


def _explain_dll_load_failure(dll: Path, exc: OSError | None = None) -> str:
    """Name the exact reason a found libmpv dll will not load.

    Windows reports WinError 126 ("or one of its dependencies") without
    saying *which* dependency — so read the dll's own import table, probe
    every import, and check the architecture against the running Python.
    """
    size_note = ""
    try:
        size = dll.stat().st_size
        if size < 1_000_000:  # official builds are ~70-120 MB
            size_note = " (warning: suspiciously small — wrong or corrupted extract? re-extract the mpv-dev archive)"
    except OSError:
        pass

    machine, imports = _pe_imported_dlls(dll)
    arch = _arch_problem(machine)
    if arch:
        return f"found {dll}{size_note} but {arch}"

    if imports:
        missing = [name for name in imports if not _loadable(name)]
        if missing:
            details = "; ".join(
                f"{name} — {_RUNTIME_ADVICE.get(name.lower(), 'copy it next to libmpv-2.dll')}"
                for name in missing
            )
            return (
                f"found {dll}{size_note}; it imports {len(imports)} dlls, "
                f"of which these are missing: {details}"
            )
        return (
            f"found {dll}{size_note}; all {len(imports)} imported dlls resolve, so the "
            "failure has another cause — try PowerShell 'Unblock-File' on the dll "
            "(downloaded-file marking) and re-extracting the archive with 7-Zip"
        )

    # Import table unreadable: fall back to probing the usual suspects.
    missing_probes = [
        f"{name} — {advice}" for name, advice in _RUNTIME_ADVICE.items() if not _loadable(name)
    ]
    if missing_probes:
        return (
            f"found {dll}{size_note}; could not read its import table, but these "
            f"common runtimes are missing on this system: " + "; ".join(missing_probes)
        )
    return f"found {dll}{size_note} but could not load it: {exc}"


def _check_libmpv() -> tuple[bool, str]:
    """Try to locate the mpv engine library (never raises).

    Deliberately does NOT import python-mpv (it raises at import time on
    Windows when the dll is missing — ``--check`` must survive that and
    report the problem instead).
    """
    if sys.platform == "win32":
        for name in _WINDOWS_DLL_NAMES:
            try:
                ctypes.CDLL(name)
                return True, f"loaded {name} (on PATH)"
            except OSError:
                continue
        # The documented install: libmpv-2.dll dropped into the project
        # root (or next to the frozen executable).
        directories: list[Path] = []
        if getattr(sys, "frozen", False):
            directories.append(Path(sys.executable).resolve().parent)
        directories.append(project_root())
        for directory in directories:
            for name in _WINDOWS_DLL_NAMES:
                dll = directory / name
                if dll.is_file():
                    try:
                        os.add_dll_directory(str(directory))
                        try:
                            ctypes.CDLL(str(dll))
                        except OSError:
                            # Legacy search order (also consults %PATH%):
                            # resolves dependencies the secure mode misses.
                            ctypes.CDLL(str(dll), winmode=0)
                        return True, f"loaded {dll}"
                    except OSError as exc:
                        return False, _explain_dll_load_failure(dll, exc)
        return False, (
            "libmpv not found — download the mpv-dev build (x86_64) from the "
            "mpv-for-Windows project (SourceForge) and place libmpv-2.dll in "
            f"{project_root()} (or anywhere on PATH)"
        )
    found = ctypes.util.find_library("mpv")
    if found:
        try:
            ctypes.CDLL(found)
            return True, f"loaded {found}"
        except OSError as exc:
            return False, f"found {found} but could not load it: {exc}"
    return False, "libmpv not found (install libmpv2 / libmpv-dev)"


def run_preflight_check() -> int:
    """Print a support/packaging diagnostic report; 0 = all good."""
    checks: list[tuple[str, bool, str]] = []

    ok, detail = _check_libmpv()
    checks.append(("engine (libmpv)", ok, detail))

    icons = asset_dir() / "icons"
    icon_count = len(list(icons.glob("*.svg"))) if icons.is_dir() else 0
    checks.append(("assets", icon_count > 0, f"{icon_count} icon(s) in {icons}"))

    try:
        config = config_dir()
        probe = config / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(("config directory", True, str(config)))
    except OSError as exc:
        checks.append(("config directory", False, f"{config} not writable: {exc}"))

    print(f"Glint {__version__} preflight check")
    print(f"  Python {sys.version.split()[0]} on {sys.platform}")
    all_ok = True
    for name, ok, detail in checks:
        all_ok &= ok
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
    print("preflight: PASS" if all_ok else "preflight: FAIL")
    return 0 if all_ok else 1


def _attach_parent_console() -> None:
    """Frozen Windows: make ``--version``/``--check`` output visible.

    The bundle is a GUI-subsystem binary (no console window on a normal
    launch). When it is launched *from* a console we attach to that
    console and rebind stdout/stderr, so diagnostic output reaches the
    terminal instead of being silently swallowed. Best effort; a no-op on
    non-Windows platforms and unfrozen runs.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        # -1 == ATTACH_PARENT_PROCESS
        if not ctypes.windll.kernel32.AttachConsole(-1):
            return  # launched by double-click / no parent console: nothing
            # to attach to; diagnostics then go to the log file only.
        # NOTE: open() must keep the default closefd=True — Python raises
        # ValueError for closefd=False with a *filename* ("CONOUT$" is a
        # device name, not a fd). v0.12.7 shipped exactly that bug: the
        # ValueError was swallowed and --check printed nothing (field
        # report, Windows 11/PowerShell; untestable in the Linux sandbox
        # because the function no-ops there).
        sys.stdout = open("CONOUT$", "w", encoding="utf-8")  # noqa: SIM115 — deliberate
        sys.stderr = open("CONOUT$", "w", encoding="utf-8")  # noqa: SIM115 — console
        sys.stdin = open("CONIN$", "r", encoding="utf-8")  # noqa: SIM115 — device handles
    except (OSError, AttributeError, ValueError):
        pass  # e.g. launched by double-click: nothing to attach to


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--version" in args or "--check" in args:
        _attach_parent_console()
    if "--version" in args:
        print(f"Glint {__version__}")
        return 0
    if "--check" in args:
        return run_preflight_check()

    # Imported lazily: --version/--check must work on machines where the
    # engine library is missing (python-mpv raises at import time there).
    from app.application import Application

    # Must be set before QApplication exists: it keeps the mpv render context
    # alive across fullscreen toggles and window-flag changes.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Glint")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("glint-player")

    application = Application(app)
    application.show()

    app.aboutToQuit.connect(application.shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
