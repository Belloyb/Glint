"""Unit tests for the centralised shortcut configuration."""

from __future__ import annotations

import json

import pytest

from app.core.shortcuts import (
    DEFAULT_BINDINGS,
    PlayerAction,
    ShortcutConfig,
    normalize_sequence,
)


def test_defaults_cover_all_actions():
    """Every declared action has an entry in the default bindings table."""
    assert set(DEFAULT_BINDINGS) == set(PlayerAction)


def test_defaults_have_no_conflicts():
    config = ShortcutConfig.defaults()
    assert config.conflicts() == {}


def test_defaults_bind_phase3_actions():
    for action in (
        PlayerAction.PLAY_PAUSE,
        PlayerAction.SEEK_BACK_SHORT,
        PlayerAction.VOLUME_UP,
        PlayerAction.MUTE,
        PlayerAction.FULLSCREEN,
        PlayerAction.SPEED_UP,
        PlayerAction.FRAME_STEP_FORWARD,
    ):
        assert ShortcutConfig.defaults().sequences(action), f"{action} unbound"


def test_normalize_sequence():
    assert normalize_sequence(" ctrl+o ") == "Ctrl+O"
    assert normalize_sequence("SHIFT+LEFT") == "Shift+Left"
    assert normalize_sequence("esc") == "Escape"
    assert normalize_sequence("space") == "Space"
    assert normalize_sequence("m") == "M"
    assert normalize_sequence("Backspace") == "Backspace"
    assert normalize_sequence("") == ""


def test_from_dict_partial_overrides_merge_with_defaults():
    config = ShortcutConfig.from_dict(
        {"bindings": {"play_pause": ["Ctrl+Space"], "volume_up": ["Ctrl+Up", "="]}}
    )
    # overridden actions
    assert config.sequences(PlayerAction.PLAY_PAUSE) == ("Ctrl+Space",)
    assert config.sequences(PlayerAction.VOLUME_UP) == ("Ctrl+Up", "=")
    # untouched actions keep defaults
    assert config.sequences(PlayerAction.FULLSCREEN) == ("F",)


def test_from_dict_accepts_flat_mapping_and_strings():
    config = ShortcutConfig.from_dict({"mute": "m"})
    assert config.sequences(PlayerAction.MUTE) == ("M",)


def test_from_dict_empty_list_unbinds():
    config = ShortcutConfig.from_dict({"bindings": {"play_pause": []}})
    assert config.sequences(PlayerAction.PLAY_PAUSE) == ()


def test_from_dict_ignores_unknown_actions_and_garbage():
    config = ShortcutConfig.from_dict(
        {"bindings": {"teleport": ["T"], "mute": 42, "quit": ["Ctrl+Q"]}}
    )
    assert config.sequences(PlayerAction.MUTE) == ("M",)  # garbage skipped, default kept
    assert config.sequences(PlayerAction.QUIT) == ("Ctrl+Q",)


def test_round_trip_through_dict():
    original = ShortcutConfig.from_dict(
        {"bindings": {"play_pause": ["Ctrl+Space"], "volume_up": []}}
    )
    restored = ShortcutConfig.from_dict(original.to_dict())
    assert restored.bindings == original.bindings


def test_conflict_detection():
    config = ShortcutConfig.from_dict(
        {"bindings": {"play_pause": ["F"], "fullscreen": ["f"], "mute": ["M"]}}
    )
    conflicts = config.conflicts()
    assert set(conflicts["F"]) == {PlayerAction.PLAY_PAUSE, PlayerAction.FULLSCREEN}
    assert "M" not in conflicts


def test_duplicate_binding_within_one_action_is_a_conflict():
    config = ShortcutConfig.from_dict({"bindings": {"mute": ["M", "m"]}})
    assert config.conflicts() == {"M": [PlayerAction.MUTE, PlayerAction.MUTE]}


def test_load_missing_file_gives_defaults(tmp_path):
    config = ShortcutConfig.load(tmp_path / "shortcuts.json")
    assert config.bindings == ShortcutConfig.defaults().bindings


def test_load_valid_file(tmp_path):
    path = tmp_path / "shortcuts.json"
    path.write_text(
        json.dumps({"bindings": {"play_pause": ["Ctrl+Space"]}}), encoding="utf-8"
    )
    config = ShortcutConfig.load(path)
    assert config.sequences(PlayerAction.PLAY_PAUSE) == ("Ctrl+Space",)
    assert config.sequences(PlayerAction.MUTE) == ("M",)  # default filled


@pytest.mark.parametrize(
    "content",
    [
        "{ not json",
        "[]",
        '{"bindings": 42}',
    ],
)
def test_load_corrupt_file_falls_back_to_defaults(tmp_path, content):
    path = tmp_path / "shortcuts.json"
    path.write_text(content, encoding="utf-8")
    config = ShortcutConfig.load(path)
    assert config.bindings == ShortcutConfig.defaults().bindings


def test_phase8_default_bindings():
    """Advanced-playback actions ship with their documented defaults."""
    config = ShortcutConfig.defaults()
    assert config.sequences(PlayerAction.CYCLE_AUDIO) == ("B",)
    assert config.sequences(PlayerAction.AUDIO_DELAY_DOWN) == ("-",)
    assert config.sequences(PlayerAction.AUDIO_DELAY_UP) == ("+", "=")
    assert config.sequences(PlayerAction.AUDIO_DELAY_RESET) == ("Shift+-",)
    assert config.sequences(PlayerAction.SCREENSHOT) == ("S",)
    assert config.sequences(PlayerAction.OPEN_URL) == ("Ctrl+U",)
