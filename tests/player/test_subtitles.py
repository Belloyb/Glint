"""Headless contract tests for subtitle support (real libmpv, no display)."""

from __future__ import annotations

import pytest

from app.core.models import PlaybackState, TrackKind
from app.core.subtitles import SubtitleAppearance, mpv_color_to_rgb
from app.player.backend import PlayerErrorCode
from tests.player.conftest import BackendHarness


def _subtitle_tracks(harness: BackendHarness):
    return [t for t in harness.backend.tracks() if t.kind is TrackKind.SUBTITLE]


def _wait_playing(harness: BackendHarness, uri: str):
    harness.backend.open(uri)
    assert harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING) is not None


def test_tracks_event_and_embedded_track(harness: BackendHarness, subtitle_mkv):
    _wait_playing(harness, str(subtitle_mkv))
    tracks = harness.wait_for(
        "tracks", predicate=lambda ts: any(t.kind is TrackKind.SUBTITLE for t in ts)
    )
    assert tracks is not None, "tracks event with a subtitle track never arrived"

    embedded = [t for t in _subtitle_tracks(harness) if not t.is_external]
    assert len(embedded) == 1
    assert embedded[0].codec == "subrip"
    assert embedded[0].kind is TrackKind.SUBTITLE


def test_external_subtitles_auto_loaded(harness: BackendHarness, subtitle_mkv):
    """sub-auto=fuzzy picks up movie.srt and movie.en.srt next to the video."""
    _wait_playing(harness, str(subtitle_mkv))
    harness.wait_for("tracks", predicate=lambda ts: any(t.kind is TrackKind.SUBTITLE for t in ts))
    external = [t for t in _subtitle_tracks(harness) if t.is_external]
    assert len(external) == 2, f"expected 2 auto-loaded externals, got {len(external)}"


def test_select_and_disable_subtitle_track(harness: BackendHarness, subtitle_mkv):
    backend = harness.backend
    _wait_playing(harness, str(subtitle_mkv))
    harness.wait_for("tracks", predicate=lambda ts: any(t.kind is TrackKind.SUBTITLE for t in ts))

    # Note: mpv auto-selects the first auto-loaded external subtitle, so the
    # initial selection is a valid id (or None with no matching externals).
    assert backend.selected_subtitle_track() in (None, 1, 2, 3)
    backend.select_subtitle_track(1)
    assert backend.selected_subtitle_track() == 1
    backend.select_subtitle_track(None)
    assert backend.selected_subtitle_track() is None


def test_add_subtitle_file_selects_it(harness: BackendHarness, subtitle_mkv, tmp_path):
    backend = harness.backend
    _wait_playing(harness, str(subtitle_mkv))
    harness.wait_for("tracks", predicate=lambda ts: any(t.kind is TrackKind.SUBTITLE for t in ts))

    extra = tmp_path / "extra.srt"
    extra.write_text("1\n00:00:00,000 --> 00:00:01,000\nExtra\n\n", encoding="utf-8")
    backend.add_subtitle_file(str(extra), title="Extra")

    selected = harness.wait_for(
        "tracks",
        predicate=lambda ts: any(t.is_external and t.title == "Extra" for t in ts),
    )
    assert selected is not None, "added external track never appeared"
    assert backend.selected_subtitle_track() is not None  # sub-add selects


def test_add_missing_subtitle_file_reports_error(harness: BackendHarness, subtitle_mkv, tmp_path):
    backend = harness.backend
    _wait_playing(harness, str(subtitle_mkv))
    backend.add_subtitle_file(str(tmp_path / "nope.srt"))
    error = harness.wait_for("error", predicate=lambda e: e.code is PlayerErrorCode.FILE_NOT_FOUND)
    assert error is not None


def test_subtitle_delay_roundtrip(harness: BackendHarness, subtitle_mkv):
    backend = harness.backend
    _wait_playing(harness, str(subtitle_mkv))
    assert backend.subtitle_delay == pytest.approx(0.0)
    backend.set_subtitle_delay(0.5)
    assert backend.subtitle_delay == pytest.approx(0.5)
    backend.set_subtitle_delay(-1.25)
    assert backend.subtitle_delay == pytest.approx(-1.25)


def test_subtitle_visibility_roundtrip(harness: BackendHarness, subtitle_mkv):
    backend = harness.backend
    _wait_playing(harness, str(subtitle_mkv))
    assert backend.subtitle_visibility is True
    backend.set_subtitle_visibility(False)
    assert backend.subtitle_visibility is False
    backend.set_subtitle_visibility(True)
    assert backend.subtitle_visibility is True


def test_subtitle_appearance_roundtrip(harness: BackendHarness, subtitle_mkv):
    backend = harness.backend
    _wait_playing(harness, str(subtitle_mkv))

    backend.set_subtitle_appearance(
        SubtitleAppearance(font="serif", size=50, color="#FFFF00", position=85)
    )
    appearance = backend.subtitle_appearance
    assert appearance.font == "serif"
    assert appearance.size == pytest.approx(50)
    assert mpv_color_to_rgb(appearance.color) == "#FFFF00"  # engine readback is #AARRGGBB
    assert appearance.position == pytest.approx(85)


def test_invalid_color_is_rejected_not_fatal(harness: BackendHarness, subtitle_mkv):
    backend = harness.backend
    _wait_playing(harness, str(subtitle_mkv))
    before = backend.subtitle_appearance
    backend.set_subtitle_appearance(
        SubtitleAppearance(font=before.font, size=before.size, color="not-a-color", position=before.position)
    )
    # unchanged, and the backend is still alive
    assert mpv_color_to_rgb(backend.subtitle_appearance.color) == mpv_color_to_rgb(before.color)


def test_subtitle_calls_ignored_when_idle(harness: BackendHarness):
    backend = harness.backend
    backend.select_subtitle_track(1)  # no media loaded: must not raise
    backend.set_subtitle_delay(2.0)
    backend.set_subtitle_visibility(False)
    backend.set_subtitle_appearance(SubtitleAppearance())
    assert backend.state is PlaybackState.IDLE
