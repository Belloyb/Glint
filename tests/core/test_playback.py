"""Unit tests for playback speed helpers."""

from __future__ import annotations

import pytest

from app.core.playback import (
    MAX_SPEED,
    MIN_SPEED,
    SPEED_PRESETS,
    VOLUME_MAX,
    VOLUME_UNITY,
    clamp_speed,
    clamp_volume,
    next_speed,
)


def test_clamp_speed():
    assert clamp_speed(1.0) == 1.0
    assert clamp_speed(99.0) == MAX_SPEED
    assert clamp_speed(0.01) == MIN_SPEED
    assert clamp_speed(-3) == MIN_SPEED


def test_next_speed_steps_through_presets():
    assert next_speed(1.0, +1) == 1.25
    assert next_speed(1.0, -1) == 0.75
    assert next_speed(0.25, -1) == 0.25  # sticky lower end
    assert next_speed(2.0, +1) == 2.0  # sticky upper end
    assert next_speed(0.25, +1) == 0.5


def test_next_speed_snaps_off_preset_values():
    assert next_speed(1.1, +1) == 1.25
    assert next_speed(1.1, -1) == 1.0
    assert next_speed(0.3, -1) == 0.25
    assert next_speed(0.3, +1) == 0.5


def test_next_speed_direction_zero_is_clamp():
    assert next_speed(3.0, 0) == MAX_SPEED


def test_presets_are_sorted_and_exact():
    assert list(SPEED_PRESETS) == sorted(SPEED_PRESETS)
    for preset in SPEED_PRESETS:
        assert pytest.approx(preset) == preset  # trivially exact binary fractions



def test_clamp_volume():
    assert clamp_volume(0) == 0
    assert clamp_volume(57) == 57
    assert clamp_volume(VOLUME_UNITY) == VOLUME_UNITY
    assert clamp_volume(150) == 150  # amplified zone is valid
    assert clamp_volume(VOLUME_MAX) == VOLUME_MAX
    assert clamp_volume(250) == VOLUME_MAX
    assert clamp_volume(-3) == 0
    assert clamp_volume(100.6) == 101  # floats round, never truncate
