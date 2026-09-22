"""Config-directory migration tests (v0.13.0 rename Lumen → Glint).

The first Glint run must copy a legacy ``lumen`` config directory onto the
new ``glint`` one (settings, recents, logs survive), exactly once, and
must never raise on odd filesystem states.
"""

from __future__ import annotations

import json

from app.utils.paths import config_dir


def _use(monkeypatch, tmp_path, name):
    target = tmp_path / name
    monkeypatch.setenv("GLINT_CONFIG_DIR", str(target))
    return target


def test_legacy_config_migrates_once(monkeypatch, tmp_path):
    legacy = tmp_path / "lumen"
    legacy.mkdir()
    (legacy / "settings.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    (legacy / "recents.json").write_text("[]", encoding="utf-8")

    target = _use(monkeypatch, tmp_path, "glint")
    got = config_dir()
    assert got == target
    assert json.loads((target / "settings.json").read_text())["theme"] == "light"
    assert (target / "recents.json").exists()

    # Second call must not overwrite newer settings with stale legacy data.
    (target / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    config_dir()
    assert json.loads((target / "settings.json").read_text())["theme"] == "dark"


def test_no_legacy_directory_means_fresh_start(monkeypatch, tmp_path):
    target = _use(monkeypatch, tmp_path, "glint")
    got = config_dir()
    assert got == target and got.is_dir()
    assert not (target / "settings.json").exists()


def test_legacy_env_override_still_honoured(monkeypatch, tmp_path):
    # Pre-rename scripts using LUMEN_CONFIG_DIR keep working unchanged
    # (the new GLINT_* name takes precedence when BOTH are set).
    monkeypatch.delenv("GLINT_CONFIG_DIR", raising=False)
    legacy_target = tmp_path / "old-style"
    monkeypatch.setenv("LUMEN_CONFIG_DIR", str(legacy_target))
    assert config_dir() == legacy_target
