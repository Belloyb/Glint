"""Filesystem locations.

Deliberately Qt-free (plain environment/platform logic) so that core modules
and tests can use it without instantiating a Qt application.

Environment overrides (also useful for portable installs and tests):

* ``GLINT_ASSETS_DIR``  — assets root (icons, themes)
* ``GLINT_CONFIG_DIR``  — per-user config directory (settings, logs, recents)

Both fall back to their legacy ``LUMEN_*`` spellings (the project was
renamed Lumen → Glint in v0.13.0) so pre-rename scripts keep working.

The rename also migrates data: on the first Glint run, a legacy ``lumen``
config directory is copied to the new ``glint`` one (see
:func:`config_dir`), so settings, recents and logs survive.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "glint"
_LEGACY_APP_NAME = "lumen"  # pre-v0.13.0 name; migration source only


def _env(*names: str) -> str | None:
    """First set, non-empty value among ``names`` (new name wins)."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def project_root() -> Path:
    """The project root (the directory containing ``app/``).

    Frozen builds (PyInstaller): the directory of the executable — that is
    also where a bundled ``libmpv-2.dll`` is looked up on Windows.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def asset_dir() -> Path:
    """Directory holding bundled assets (icons, themes).

    Assets ship *inside* the package (``app/assets``), so a wheel/installed
    run finds them next to the code. A frozen build reads them from the
    PyInstaller bundle directory (``sys._MEIPASS`` — the ``_internal``
    folder next to the exe in onedir builds); a portable layout can point
    ``GLINT_ASSETS_DIR`` anywhere.
    """
    override = _env("GLINT_ASSETS_DIR", "LUMEN_ASSETS_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def icon_path(name: str) -> Path:
    """Path of ``assets/icons/<name>.svg``."""
    return asset_dir() / "icons" / f"{name}.svg"


def config_dir() -> Path:
    """Per-user configuration directory (created if missing).

    Respects the platform convention:
    Windows ``%APPDATA%\\\\glint``, macOS ``~/Library/Application Support/glint``,
    else ``$XDG_CONFIG_HOME/glint`` (defaulting to ``~/.config/glint``).
    """
    override = _env("GLINT_CONFIG_DIR", "LUMEN_CONFIG_DIR")
    if override:
        path = Path(override)
    else:
        home = Path.home()
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        elif sys.platform == "darwin":
            base = home / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        path = base / APP_NAME
    _migrate_legacy_config(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _migrate_legacy_config(new_path: Path) -> None:
    """Copy a pre-rename (Lumen) config directory onto the Glint one, once.

    Best effort, never raises: the worst case is simply starting with fresh
    settings. Skipped when the new directory already has settings, when an
    explicit override is in effect pointing at the legacy name, or when no
    legacy directory exists.
    """
    if new_path.name == _LEGACY_APP_NAME:
        return
    legacy = new_path.parent / _LEGACY_APP_NAME
    try:
        if not legacy.is_dir() or (new_path / "settings.json").exists():
            return
        shutil.copytree(legacy, new_path, dirs_exist_ok=True)
    except OSError:
        pass  # best effort only


def log_dir() -> Path:
    """Per-user log directory (created if missing)."""
    path = config_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
