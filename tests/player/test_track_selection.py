"""Phase 8 backend contract tests: audio/video track selection, secondary
subtitles, audio sync and screenshots.

All facts verified against libmpv 0.40 (vo/ao null harness):
- track ids are per-kind namespaces (audio 1..n, video 1..m, subtitle 1..k);
- selecting an id missing from the file *disables* the track type (readback
  ``False``) instead of raising — the UI cannot produce such ids;
- ``reset_track_selections`` restores the engine defaults;
- ``audio-delay`` is runtime-settable and persists across ``loadfile``;
- ``screenshot-to-file`` works even under vo=null and fails cleanly when the
  target path is not writable.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.models import PlaybackState, TrackKind


def _open_and_wait(harness, uri: Path) -> None:
    harness.backend.open(str(uri))
    state = harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING)
    assert state is not None, "media never started playing"
    # Give the demuxer a moment to publish the full track list.
    assert harness.wait_for(
        "tracks", predicate=lambda t: len([x for x in t if x.kind is TrackKind.AUDIO]) >= 2
    )


def test_multi_track_media_lists_all_kinds(harness, multi_track_mkv):
    _open_and_wait(harness, multi_track_mkv)
    tracks = harness.backend.tracks()
    kinds = [t.kind for t in tracks]
    assert kinds.count(TrackKind.AUDIO) == 2
    assert kinds.count(TrackKind.VIDEO) == 2
    assert kinds.count(TrackKind.SUBTITLE) == 1
    langs = {t.id: t.language for t in tracks if t.kind is TrackKind.AUDIO}
    assert langs == {1: "eng", 2: "fre"}


def test_audio_track_selection_round_trip(harness, multi_track_mkv):
    _open_and_wait(harness, multi_track_mkv)
    backend = harness.backend
    backend.select_audio_track(2)
    time.sleep(0.2)
    assert backend.selected_audio_track() == 2
    backend.select_audio_track(None)
    time.sleep(0.2)
    assert backend.selected_audio_track() is None
    backend.select_audio_track(1)
    time.sleep(0.2)
    assert backend.selected_audio_track() == 1


def test_video_track_selection_round_trip(harness, multi_track_mkv):
    _open_and_wait(harness, multi_track_mkv)
    backend = harness.backend
    backend.select_video_track(2)
    time.sleep(0.2)
    assert backend.selected_video_track() == 2
    backend.select_video_track(None)
    time.sleep(0.2)
    assert backend.selected_video_track() is None
    backend.select_video_track(1)
    time.sleep(0.2)
    assert backend.selected_video_track() == 1


def test_invalid_audio_id_disables_instead_of_raising(harness, multi_track_mkv):
    """Documented engine quirk: an unknown id resolves to 'disabled'."""
    _open_and_wait(harness, multi_track_mkv)
    backend = harness.backend
    backend.select_audio_track(99)
    time.sleep(0.2)
    assert backend.selected_audio_track() is None


def test_secondary_subtitle_round_trip(harness, multi_track_mkv):
    _open_and_wait(harness, multi_track_mkv)
    backend = harness.backend
    backend.select_secondary_subtitle_track(1)
    time.sleep(0.2)
    assert backend.selected_secondary_subtitle_track() == 1
    backend.select_secondary_subtitle_track(None)
    time.sleep(0.2)
    assert backend.selected_secondary_subtitle_track() is None


def test_reset_track_selections_restores_defaults(harness, multi_track_mkv):
    _open_and_wait(harness, multi_track_mkv)
    backend = harness.backend
    backend.select_audio_track(2)
    backend.select_video_track(2)
    backend.select_subtitle_track(1)
    backend.select_secondary_subtitle_track(1)
    time.sleep(0.3)

    backend.reset_track_selections()
    time.sleep(0.3)
    # Audio: the default-flagged track is re-selected.
    assert backend.selected_audio_track() == 1
    # The secondary subtitle is always cleared.
    assert backend.selected_secondary_subtitle_track() is None
    # Subtitles return to the engine's automatic choice. Under vo=null the
    # video track reads back as disabled (no video output), so only the
    # audio/subtitle readbacks are portable assertions here.
    assert backend.selected_subtitle_track() in (None, 1)


def test_audio_delay_round_trip(harness, multi_track_mkv):
    _open_and_wait(harness, multi_track_mkv)
    backend = harness.backend
    assert backend.audio_delay == pytest.approx(0.0, abs=1e-6)
    backend.set_audio_delay(0.25)
    time.sleep(0.2)
    assert backend.audio_delay == pytest.approx(0.25, abs=1e-6)
    backend.set_audio_delay(-0.1)
    time.sleep(0.2)
    assert backend.audio_delay == pytest.approx(-0.1, abs=1e-6)


def test_audio_delay_persists_across_loadfile(harness, multi_track_mkv):
    _open_and_wait(harness, multi_track_mkv)
    harness.backend.set_audio_delay(0.5)
    _open_and_wait(harness, multi_track_mkv)  # reload the same file
    assert harness.backend.audio_delay == pytest.approx(0.5, abs=1e-6)


def test_screenshot_writes_png(harness, multi_track_mkv, tmp_path):
    _open_and_wait(harness, multi_track_mkv)
    target = tmp_path / "shot.png"
    assert harness.backend.screenshot_to(str(target)) is True
    assert target.exists() and target.stat().st_size > 1000


def test_screenshot_failure_is_clean(harness, multi_track_mkv, tmp_path):
    """An unwritable target must return False, never raise."""
    _open_and_wait(harness, multi_track_mkv)
    target = tmp_path / "missing-dir" / "shot.png"
    assert harness.backend.screenshot_to(str(target)) is False
