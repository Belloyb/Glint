"""Packaging-related tests (Phase 11): CLI support options and asset paths.

``app.main`` imports PySide6 at module level, but the ``--version`` and
``--check`` paths never instantiate a QApplication, so these run headless
and fast alongside the other core tests.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import __version__
from app.main import main
from app.utils.paths import asset_dir, config_dir, icon_path, project_root


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == f"Glint {__version__}"


def test_check_passes_in_development_environment(capsys):
    """The sandbox/dev tree has libmpv, assets and a writable config dir."""
    assert main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "preflight: PASS" in out
    assert "engine (libmpv)" in out
    assert "assets" in out


def test_check_fails_when_assets_are_missing(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("GLINT_ASSETS_DIR", str(tmp_path / "no-such-assets"))
    assert main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "preflight: FAIL" in out
    assert "0 icon(s)" in out


def test_asset_dir_lives_inside_the_package():
    """Assets ship as package data since Phase 11 — they must resolve next
    to the code (so a wheel/installed run finds them), not at some
    development-tree-relative location."""
    directory = asset_dir()
    assert directory.name == "assets"
    assert directory.exists()
    assert (directory / "icons").is_dir()
    assert len(list((directory / "icons").glob("*.svg"))) >= 15


def test_asset_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GLINT_ASSETS_DIR", str(tmp_path))
    assert asset_dir() == tmp_path
    assert icon_path("play") == tmp_path / "icons" / "play.svg"


def test_project_root_contains_the_package():
    root = project_root()
    assert (root / "app").is_dir()


def test_config_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GLINT_CONFIG_DIR", str(tmp_path / "cfg"))
    assert config_dir() == tmp_path / "cfg"
    assert config_dir().exists()  # created on demand


def test_wheel_package_data_pattern_covers_all_icons():
    """The package-data glob in pyproject.toml must cover every icon actually
    present, or wheels would silently drop some (regression guard for the
    Phase 11 packaging fix)."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'app = \["assets/icons/\*\.svg"\]', text)
    assert match, "pyproject package-data pattern for app assets is missing or changed"


def test_support_cli_does_not_import_the_engine():
    """--version/--check must work without libmpv installed.

    python-mpv raises ``OSError`` at *import time* on Windows when the dll
    is missing, so ``app.main`` must not import ``app.application`` (and
    thereby the engine) at module level — found in Phase 12 field use on
    Windows, fixed in 0.12.1.
    """
    import subprocess
    import sys as _sys

    code = (
        "import sys; import app.main; "
        "assert 'app.application' not in sys.modules, 'engine imported at module level'; "
        "print('ok')"
    )
    result = subprocess.run(
        [_sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def _build_minimal_pe(path) -> None:
    """A minimal but structurally valid PE32+ (x64) with two imports."""
    import struct

    e_lfanew = 0x80
    dos = bytearray(e_lfanew)
    dos[0:2] = b"MZ"
    dos[0x3C:0x40] = struct.pack("<I", e_lfanew)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x2022)
    optional = bytearray(240)
    optional[0:2] = struct.pack("<H", 0x20B)  # PE32+
    # data directory entry 1 (imports) at optional-header offset 112
    optional[112 + 8 : 112 + 16] = struct.pack("<II", 0x1000, 0x3C)
    section = struct.pack("<8sIIII", b".rsrc", 0x2000, 0x1000, 0x2000, 0x400) + b"\x00" * 20

    pe = bytearray()
    pe += dos + b"PE\x00\x00" + coff + optional + section
    pe += b"\x00" * (0x400 - len(pe))  # pad to the section's raw offset

    descriptor = struct.pack("<IIIII", 0x1010, 0, 0, 0x1100, 0x1010)
    descriptor2 = struct.pack("<IIIII", 0x1010, 0, 0, 0x1120, 0x1010)
    pe += descriptor + descriptor2 + b"\x00" * 20
    pe += b"\x00" * (0x500 - len(pe))
    pe += b"libwinpthread-1.dll\x00"
    pe += b"\x00" * (0x520 - len(pe))
    pe += b"KERNEL32.dll\x00"
    path.write_bytes(bytes(pe))


def test_pe_import_parser_reads_import_table(tmp_path):
    from app.main import _pe_imported_dlls

    dll = tmp_path / "libmpv-2.dll"
    _build_minimal_pe(dll)
    machine, imports = _pe_imported_dlls(dll)
    assert machine == "x64"
    assert imports == ["libwinpthread-1.dll", "KERNEL32.dll"]


def test_pe_import_parser_rejects_non_pe(tmp_path):
    from app.main import _pe_imported_dlls

    junk = tmp_path / "junk.dll"
    junk.write_bytes(b"definitely not a PE file" * 16)
    machine, imports = _pe_imported_dlls(junk)
    assert machine is None
    assert imports == []


def test_arch_problem_detection():
    from app.main import _arch_problem

    assert _arch_problem(None) is None
    # A mismatched dll arch must be reported; matching must not be.
    host = __import__("platform").machine().upper()
    expected = {"AMD64": "x64", "ARM64": "ARM64", "X86": "x86"}.get(host)
    assert _arch_problem(expected) is None
    assert _arch_problem("x86" if expected != "x86" else "ARM64") is not None


# ------------------------------------------------------------- release files
def test_release_versions_agree():
    """pyproject, app.__version__, installer and exe resource must match."""
    from app import __version__

    root = Path(__file__).resolve().parents[2]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject

    iss = (root / "packaging" / "windows-installer.iss").read_text(encoding="utf-8")
    assert f'#define MyAppVersion "{__version__}"' in iss

    version_file = (root / "packaging" / "exe-version.txt").read_text(encoding="utf-8")
    parts = [str(int(part)) for part in __version__.split(".")] + ["0"]
    dotted = "filevers=(" + ", ".join(parts) + ")"
    assert dotted in version_file, f"exe-version.txt out of sync: {dotted!r}"
    assert f"'{__version__}.0'" in version_file


def test_frozen_assets_resolve_from_bundle_dir(tmp_path, monkeypatch):
    """v0.12.7: frozen assets live under sys._MEIPASS (PyInstaller _internal),
    not next to the exe — the bundle layout the spec actually produces."""
    import sys

    from app.utils.paths import asset_dir, project_root

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    try:
        assert asset_dir() == tmp_path / "assets"
        assert project_root() != tmp_path / "assets"  # exe dir, for the dll
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_attach_parent_console_is_safe_noop_when_unfrozen(capsys):
    """The Windows console-attach must never disturb unfrozen/non-Windows
    runs (it returns before touching stdout there)."""
    from app.main import _attach_parent_console

    _attach_parent_console()
    print("still-here")
    assert "still-here" in capsys.readouterr().out


def test_installer_script_basics():
    root = Path(__file__).resolve().parents[2]
    iss = (root / "packaging" / "windows-installer.iss").read_text(encoding="utf-8")
    # Upgrade identity must stay stable and the bundle must carry licences.
    assert "AppId={{A1C3E5F7-2B4D-4E6F-8A0C-5D7E9B1F3A5C}" in iss
    assert "REDISTRIBUTION.md" in iss
    assert "vulkan-1.dll" in iss  # the runtime warning must not be dropped
    # Inno's REQUIRED [Setup] directives (a v0.12.7 rewrite accidentally
    # dropped DefaultDirName/GroupName — caught only at first Windows compile).
    assert "DefaultDirName=" in iss
    assert "DefaultGroupName=" in iss
    assert "OutputDir=" in iss and "LicenseFile=" in iss
    # Privileges must be explicit: Inno defaults to "admin", which warns
    # against this script's per-user HKCU associations and can misplace
    # them under an elevating account (first Windows compile, v0.12.8).
    assert "PrivilegesRequired=lowest" in iss


def test_association_include_is_plain_registry_lines():
    """The per-extension include must be plain [Registry] text (a parameterised
    ISPP macro was unreadable by Inno's section parser — first real compile,
    v0.12.8). Every active line: full association entry, HKCU, uninstall
    cleanup, gated on the fileassoc task."""
    root = Path(__file__).resolve().parents[2]
    inc = (root / "packaging" / "assoc-extensions.iss.inc").read_text(encoding="utf-8")
    active = [
        line.strip()
        for line in inc.splitlines()
        if line.strip() and not line.strip().startswith(";")
    ]
    assert len(active) >= 18, "expected the full media-extension list"
    for line in active:
        assert line.startswith('Root: HKCU; Subkey: "Software\\Classes\\.'), line
        assert line.endswith("Tasks: fileassoc"), line
        assert "uninsdeletevalue" in line
    assert "AssocExt(" not in inc  # the macro approach must not come back
