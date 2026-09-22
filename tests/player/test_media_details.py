"""Headless contract tests for the media-details snapshot (real libmpv)."""

from __future__ import annotations

import pytest

from app.core.media_info import MediaDetails, tracks_of_kind
from app.core.models import PlaybackState, TrackKind
from tests.player.conftest import BackendHarness


def _open_and_settle(harness: BackendHarness, uri: str):
    harness.backend.open(uri)
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None
    assert harness.wait_for("duration", predicate=lambda d: d and d > 0) is not None


def test_media_details_for_audio_file(harness: BackendHarness, sample_wav):
    _open_and_settle(harness, str(sample_wav))
    details = harness.backend.media_details()

    assert details.container == "wav"
    assert details.file_path == str(sample_wav)
    assert details.file_size == sample_wav.stat().st_size
    assert details.duration == pytest.approx(3.0, abs=0.25)
    assert details.title == "tone"
    assert details.pixel_format is None  # audio-only

    audio = tracks_of_kind(details, TrackKind.AUDIO)
    assert len(audio) == 1
    assert audio[0].codec == "pcm_s16le"
    assert audio[0].sample_rate == 8000
    assert audio[0].channels == 1
    assert audio[0].bitrate == 128_000


def test_media_details_for_video_file(harness: BackendHarness, subtitle_mkv):
    _open_and_settle(harness, str(subtitle_mkv))
    details = harness.backend.media_details()

    assert details.container == "mkv"
    assert details.file_size == subtitle_mkv.stat().st_size
    assert details.duration == pytest.approx(4.0, abs=0.3)

    video = tracks_of_kind(details, TrackKind.VIDEO)
    assert len(video) == 1
    assert video[0].codec == "mpeg4"
    assert video[0].dimensions == "320×180"
    assert video[0].framerate == pytest.approx(12.0, abs=0.1)

    audio = tracks_of_kind(details, TrackKind.AUDIO)
    assert len(audio) == 1
    assert audio[0].sample_rate == 44_100
    assert audio[0].channels == 1

    subs = tracks_of_kind(details, TrackKind.SUBTITLE)
    assert len(subs) >= 1  # embedded (+ auto-loaded externals)
    assert any(not s.is_external for s in subs)

    # Selected-video extras from the engine's output parameters.
    assert details.pixel_format == "yuv420p"
    assert details.display_aspect == "16:9"


def test_media_details_when_idle_is_empty_but_safe(harness: BackendHarness):
    details = harness.backend.media_details()
    assert isinstance(details, MediaDetails)
    assert details.is_empty
    assert details.tracks == ()
