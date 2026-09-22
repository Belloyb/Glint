"""Contract tests for speed control and frame stepping."""

from __future__ import annotations

import pytest

from app.core.models import PlaybackState
from tests.player.conftest import BackendHarness


def test_speed_roundtrip_and_clamping(harness: BackendHarness):
    backend = harness.backend
    backend.set_speed(1.5)
    assert backend.speed == pytest.approx(1.5)
    backend.set_speed(0.25)
    assert backend.speed == pytest.approx(0.25)
    backend.set_speed(99.0)
    assert backend.speed == pytest.approx(2.0)
    backend.set_speed(0.001)
    assert backend.speed == pytest.approx(0.25)


def test_speed_persists_during_playback(harness: BackendHarness, sample_wav):
    backend = harness.backend
    backend.open(str(sample_wav))
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None
    backend.set_speed(2.0)
    assert harness.wait_for("position", predicate=lambda p: p and p > 0.0) is not None
    assert backend.speed == pytest.approx(2.0)


def test_step_frame_pauses_and_advances(harness: BackendHarness, sample_mp4):
    backend = harness.backend
    backend.open(str(sample_mp4))
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None

    backend.step_frame(forward=True)
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PAUSED) is not None

    # Further stepping while paused must be safe in both directions.
    backend.step_frame(forward=True)
    backend.step_frame(forward=False)
    assert harness.wait_for("position", predicate=lambda p: p is not None and p >= 0.0) is not None
    assert backend.state is PlaybackState.PAUSED


def test_step_frame_while_idle_is_a_safe_noop(harness: BackendHarness):
    harness.backend.step_frame(forward=True)
    harness.backend.step_frame(forward=False)
    assert harness.backend.state is PlaybackState.IDLE
