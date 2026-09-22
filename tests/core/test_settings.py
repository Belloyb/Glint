"""Unit tests for the settings schema, validation and store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.settings import (
    AppSettings,
    PlaybackSettings,
    SettingsStore,
    SubtitleSettings,
)


def test_defaults():
    settings = AppSettings()
    assert settings.playback.default_volume == 100
    assert settings.playback.default_speed == 1.0
    assert settings.playback.autoplay_on_open is True
    assert settings.interface.theme == "dark"
    assert settings.interface.show_playlist_at_start is True
    assert settings.interface.font_scale == "normal"
    assert settings.subtitles.size == 38.0
    assert settings.subtitles.color == "#FFFFFF"
    assert settings.subtitles.auto_load_external is True
    assert settings.audio.output_device == "auto"
    assert settings.video.hardware_decoding is True
    assert settings.video.deinterlace is False


def test_round_trip(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = AppSettings(
        playback=PlaybackSettings(default_volume=42, default_speed=1.5, autoplay_on_open=False),
        subtitles=SubtitleSettings(font="serif", size=50, color="#FFFF00", default_delay=-0.5),
    )
    store.save(settings)
    assert store.load() == settings


def test_save_is_atomic_and_valid_json(tmp_path: Path):
    path = tmp_path / "settings.json"
    SettingsStore(path).save(AppSettings())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    # no temporary leftovers
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_load_missing_file_gives_defaults(tmp_path: Path):
    assert SettingsStore(tmp_path / "nope.json").load() == AppSettings()


@pytest.mark.parametrize("content", ["{ not json", "[]", '"a string"', ""])
def test_load_corrupt_file_gives_defaults(tmp_path: Path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    assert SettingsStore(path).load() == AppSettings()


def test_unknown_schema_version_gives_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    assert SettingsStore(path).load() == AppSettings()


def test_unknown_keys_and_sections_ignored(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "playback": {"default_volume": 33, "teleport": True},
                "future_section": {"anything": 1},
            }
        ),
        encoding="utf-8",
    )
    settings = SettingsStore(path).load()
    assert settings.playback.default_volume == 33
    assert settings == AppSettings(playback=PlaybackSettings(default_volume=33))


def test_wrong_types_fall_back_to_field_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "playback": {
                    "default_volume": "loud",
                    "default_speed": None,
                    "autoplay_on_open": "yes",
                },
                "interface": {"theme": "solarized", "font_scale": 3},
            }
        ),
        encoding="utf-8",
    )
    settings = SettingsStore(path).load()
    assert settings.playback.default_volume == 0  # invalid int → 0 (then clamped into range)
    assert settings.playback.default_speed == 1.0
    assert settings.playback.autoplay_on_open is False
    assert settings.interface.theme == "dark"
    assert settings.interface.font_scale == "normal"


def test_numeric_ranges_are_clamped():
    settings = AppSettings.from_dict(
        {
            "schema_version": 1,
            "playback": {"default_volume": 250, "default_speed": 9.0},
            "subtitles": {"size": 5000, "default_delay": 10**9},
        }
    )
    assert settings.playback.default_volume == 200
    assert settings.playback.default_speed == 2.0
    assert settings.subtitles.size == 200.0
    assert settings.subtitles.default_delay == 3600.0


def test_color_validation_and_normalisation():
    settings = AppSettings.from_dict(
        {"schema_version": 1, "subtitles": {"color": "#ff00ff", "size": 40}}
    )
    assert settings.subtitles.color == "#FF00FF"
    bad = AppSettings.from_dict({"schema_version": 1, "subtitles": {"color": "blue"}})
    assert bad.subtitles.color == "#FFFFFF"


def test_malformed_section_uses_whole_section_defaults():
    settings = AppSettings.from_dict(
        {"schema_version": 1, "subtitles": ["not", "a", "dict"]}
    )
    assert settings.subtitles == SubtitleSettings()


def test_to_dict_includes_schema_version():
    data = AppSettings().to_dict()
    assert data["schema_version"] == 1
    assert set(data) == {
        "playback", "interface", "subtitles", "audio", "video", "schema_version",
    }


def test_amplified_default_volume_is_valid():
    """v0.12.6: 100..200 is the VLC-style amplified zone, not an error."""
    settings = AppSettings.from_dict(
        {"schema_version": 1, "playback": {"default_volume": 150}}
    )
    assert settings.playback.default_volume == 150
