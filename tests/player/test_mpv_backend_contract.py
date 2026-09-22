"""Headless contract tests for the libmpv backend.

These verify the behaviour the UI depends on — transport, accurate seeking,
volume/mute, the state machine, and clean error paths — without any display
(``vo=null``/``ao=null``). They are the CI gate for engine regressions.
"""

from __future__ import annotations

import pytest

from app.core.models import PlaybackState
from app.player.backend import PlayerErrorCode
from tests.player.conftest import BackendHarness


def test_missing_file_reports_clean_error(harness: BackendHarness, tmp_path):
    harness.backend.open(str(tmp_path / "missing.mp4"))
    error = harness.wait_for("error", predicate=lambda e: e.code is PlayerErrorCode.FILE_NOT_FOUND)
    assert error is not None
    assert harness.backend.state is PlaybackState.ERROR


def test_directory_is_rejected(harness: BackendHarness, tmp_path):
    harness.backend.open(str(tmp_path))
    error = harness.wait_for("error", predicate=lambda e: e.code is PlayerErrorCode.UNSUPPORTED_FORMAT)
    assert error is not None


def test_playback_lifecycle(harness: BackendHarness, sample_wav):
    backend = harness.backend

    backend.open(str(sample_wav))
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None

    duration = harness.wait_for("duration", predicate=lambda d: d and d > 0)
    assert duration == pytest.approx(3.0, abs=0.1)

    info = harness.wait_for("loaded")
    assert info is not None
    assert info.title == "tone"
    assert info.uri.endswith("tone.wav")

    # Accurate absolute seek.
    backend.seek(1.0)
    assert harness.wait_for("position", predicate=lambda p: 0.9 <= p <= 1.9) is not None

    backend.pause()
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PAUSED) is not None

    backend.play()
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None

    backend.stop()
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.STOPPED) is not None


def test_play_after_stop_reopens_last_media(harness: BackendHarness, sample_wav):
    backend = harness.backend
    backend.open(str(sample_wav))
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None
    backend.stop()
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.STOPPED) is not None
    backend.play()
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None


def test_reaches_end_of_media(harness: BackendHarness, sample_wav):
    harness.backend.open(str(sample_wav))
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None
    # 3-second file at normal speed; allow generous margins for slow CI.
    assert harness.wait_for("state", timeout=15.0, predicate=lambda s: s is PlaybackState.ENDED) is not None


def test_volume_and_mute_roundtrip(harness: BackendHarness):
    backend = harness.backend
    backend.set_volume(37)
    assert backend.volume == 37
    backend.set_volume(150)  # amplified zone (volume-max=200)
    assert backend.volume == 150
    backend.set_volume(250)  # clamped to 200
    assert backend.volume == 200
    backend.set_volume(-5)  # clamped to 0
    assert backend.volume == 0
    backend.set_volume(80)
    backend.set_mute(True)
    assert backend.muted is True
    backend.set_mute(False)
    assert backend.muted is False


def test_corrupt_file_fails_with_unsupported_format(harness: BackendHarness, corrupt_file):
    harness.backend.open(str(corrupt_file))
    error = harness.wait_for(
        "error", timeout=15.0, predicate=lambda e: e.code is PlayerErrorCode.UNSUPPORTED_FORMAT
    )
    assert error is not None
    assert error.detail  # engine detail for the log
    assert harness.backend.state is PlaybackState.ERROR


def test_seek_ignored_when_idle(harness: BackendHarness):
    harness.backend.seek(5.0)  # must be a no-op, never a crash
    harness.backend.seek_relative(-10.0)
    assert harness.backend.state is PlaybackState.IDLE


def test_open_empty_uri_is_a_programming_error(harness: BackendHarness):
    with pytest.raises(ValueError):
        harness.backend.open("")
