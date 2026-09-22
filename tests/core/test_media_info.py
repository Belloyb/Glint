"""Unit tests for the media-details model and report builder."""

from __future__ import annotations

from app.core.media_info import (
    MediaDetails,
    estimate_overall_bitrate,
    format_details_report,
    selected_or_first,
    tracks_of_kind,
)
from app.core.models import TrackInfo, TrackKind


def make_details() -> MediaDetails:
    video = TrackInfo(
        id=1, kind=TrackKind.VIDEO, codec="h264", codec_desc="H.264 / AVC",
        is_selected=True, width=1920, height=1080, framerate=23.976,
    )
    audio = TrackInfo(
        id=1, kind=TrackKind.AUDIO, codec="aac", codec_desc="AAC",
        language="eng", is_selected=True, sample_rate=48000, channels=2,
        channel_layout="stereo", bitrate=128000,
    )
    audio2 = TrackInfo(id=2, kind=TrackKind.AUDIO, codec="ac3", language="jpn")
    sub = TrackInfo(id=1, kind=TrackKind.SUBTITLE, codec="subrip", language="eng")
    sub_ext = TrackInfo(id=2, kind=TrackKind.SUBTITLE, codec="ass", title="Signs", is_external=True)
    return MediaDetails(
        uri="/movies/film.mkv",
        title="film",
        file_path="/movies/film.mkv",
        file_size=1_500_000,
        container="mkv",
        duration=100.0,
        pixel_format="yuv420p",
        display_aspect="16:9",
        tracks=(video, audio, audio2, sub, sub_ext),
    )


def test_tracks_of_kind_filters():
    details = make_details()
    assert len(tracks_of_kind(details, TrackKind.AUDIO)) == 2
    assert len(tracks_of_kind(details, TrackKind.VIDEO)) == 1
    assert len(tracks_of_kind(details, TrackKind.SUBTITLE)) == 2


def test_selected_or_first():
    tracks = tracks_of_kind(make_details(), TrackKind.AUDIO)
    assert selected_or_first(tracks).id == 1  # selected wins
    none_selected = [t for t in tracks if t.id == 2]
    assert selected_or_first(none_selected).id == 2  # falls back to first
    assert selected_or_first([]) is None


def test_estimate_overall_bitrate():
    details = make_details()
    assert estimate_overall_bitrate(details) == 120_000  # 1.5e6 * 8 / 100
    empty = MediaDetails()
    assert estimate_overall_bitrate(empty) is None
    no_duration = MediaDetails(file_size=100, duration=None)
    assert estimate_overall_bitrate(no_duration) is None


def test_report_contains_all_sections():
    report = format_details_report(make_details())
    assert "Media Information" in report
    assert "/movies/film.mkv" in report
    assert "1.4 MiB" in report
    assert "mkv" in report
    assert "h264 (H.264 / AVC)" in report
    assert "1920×1080" in report
    assert "23.98 fps" in report
    assert "48 kHz" in report
    assert "2 (stereo)" in report
    assert "128 kbps" in report
    assert "eng" in report
    assert "Signs" in report
    assert "external" in report
    assert "embedded" in report
    assert "yuv420p" in report
    assert "16:9" in report


def test_report_empty_details():
    report = format_details_report(MediaDetails())
    assert "No media loaded." in report


def test_report_video_only_media():
    video = TrackInfo(id=1, kind=TrackKind.VIDEO, codec="mpeg4", width=320, height=180)
    report = format_details_report(MediaDetails(uri="x.mp4", title="x", tracks=(video,)))
    assert "Video" in report
    assert "Audio" not in report
    assert "320×180" in report
    assert "none" in report  # subtitle section states none


def test_dimensions_property():
    video = TrackInfo(id=1, kind=TrackKind.VIDEO, width=320, height=180)
    assert video.dimensions == "320×180"
    assert TrackInfo(id=1, kind=TrackKind.VIDEO).dimensions is None


def test_container_names_prettified():
    from app.core.media_info import format_container_name

    assert format_container_name("mov,mp4,m4a,3gp,3g2,mj2") == "MP4 (QuickTime / MPEG-4)"
    assert format_container_name("matroska,webm") == "Matroska / WebM"
    assert format_container_name("wav") == "WAV"
    assert format_container_name(None) is None
    # Unknown raw names pass through unchanged (honesty over prettiness).
    assert format_container_name("some-new-format") == "some-new-format"


def test_report_uses_prettified_container():
    details = make_details()
    details = MediaDetails(
        **{**details.__dict__, "container": "mov,mp4,m4a,3gp,3g2,mj2"}
    )
    report = format_details_report(details)
    assert "MP4 (QuickTime / MPEG-4)" in report
    assert "mov,mp4" not in report
