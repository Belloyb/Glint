"""Media details model and report builder (Qt-free).

A :class:`MediaDetails` is a snapshot of "everything worth showing about the
current media", gathered from the playback engine on demand (the info dialog
never needs background probing). Per-track data lives in
:class:`app.core.models.TrackInfo` (demuxer-level details included); this
module adds the general section, selection helpers, an overall-bitrate
estimate and a plain-text report used for the clipboard and the log.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.models import TrackInfo, TrackKind
from app.utils.format import format_bitrate, format_size, format_time


@dataclass(frozen=True)
class MediaDetails:
    """Snapshot of the current media's information."""

    uri: str = ""
    title: str = ""
    file_path: str | None = None
    file_size: int | None = None  # bytes
    container: str | None = None
    duration: float | None = None
    # Selected-video extras from the engine's output parameters:
    pixel_format: str | None = None
    display_aspect: str | None = None  # e.g. "16:9"
    tracks: tuple[TrackInfo, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (self.file_path or self.container or self.tracks)


def tracks_of_kind(details: MediaDetails, kind: TrackKind) -> list[TrackInfo]:
    return [track for track in details.tracks if track.kind is kind]


def selected_or_first(tracks: list[TrackInfo]) -> TrackInfo | None:
    """The selected track, else the first (for summary rows)."""
    for track in tracks:
        if track.is_selected:
            return track
    return tracks[0] if tracks else None


def estimate_overall_bitrate(details: MediaDetails) -> int | None:
    """Overall bitrate in bits/s from file size and duration, if both known."""
    if details.file_size and details.duration and details.duration > 0:
        return round(details.file_size * 8 / details.duration)
    return None


#: Raw FFmpeg/libmpv container names (comma-joined probe lists) mapped to
#: friendly names for display. Raw values are kept in :class:`MediaDetails`
#: (they are engine facts); prettifying happens at presentation time.
_CONTAINER_NAMES: dict[str, str] = {
    "mov,mp4,m4a,3gp,3g2,mj2": "MP4 (QuickTime / MPEG-4)",
    "matroska,webm": "Matroska / WebM",
    "mpegts": "MPEG-TS",
    "mpeg": "MPEG program stream",
    "mpegvideo": "MPEG video",
    "avi": "AVI",
    "asf": "ASF / WMV",
    "wav": "WAV",
    "mp3": "MP3",
    "flac": "FLAC",
    "ogg": "Ogg",
    "opus": "Ogg Opus",
    "aac": "AAC (ADTS)",
    "wv": "WavPack",
    "ape": "Monkey's Audio",
    "aiff": "AIFF",
    "mf": "Media file (single media)",
}


def format_container_name(raw: str | None) -> str | None:
    """Friendly container name for a raw engine string.

    Unknown values are returned unchanged (honesty over prettiness: the raw
    FFmpeg list is still informative).
    """
    if not raw:
        return None
    return _CONTAINER_NAMES.get(raw, raw)


def format_details_report(details: MediaDetails) -> str:
    """Render details as plain text (clipboard / log friendly)."""
    lines: list[str] = ["Media Information", ""]

    if details.is_empty:
        lines.append("No media loaded.")
        return "\n".join(lines)

    lines += [
        "General",
        f"  Title:       {details.title or '—'}",
        f"  File:        {details.file_path or details.uri}",
        f"  Size:        {format_size(details.file_size) if details.file_size else '—'}",
        f"  Container:   {format_container_name(details.container) or '—'}",
        f"  Duration:    {format_time(details.duration)}"
        + (f" ({details.duration:.1f} s)" if details.duration else ""),
    ]
    bitrate = estimate_overall_bitrate(details)
    lines.append(
        f"  Bitrate:     {format_bitrate(bitrate)} (estimated)" if bitrate else "  Bitrate:     —"
    )

    video_tracks = tracks_of_kind(details, TrackKind.VIDEO)
    if video_tracks:
        lines += ["", "Video"]
        for track in video_tracks:
            prefix = "  • " if len(video_tracks) == 1 else f"  Track {track.id}: "
            rows = [
                ("Codec", f"{track.codec or '—'}" + (f" ({track.codec_desc})" if track.codec_desc else "")),
                ("Resolution", track.dimensions or "—"),
                ("Framerate", f"{track.framerate:.2f} fps" if track.framerate else "—"),
                ("Bitrate", format_bitrate(track.bitrate) if track.bitrate else "—"),
            ]
            if track.is_selected:
                if details.pixel_format:
                    rows.append(("Pixel format", details.pixel_format))
                if details.display_aspect:
                    rows.append(("Aspect", details.display_aspect))
            lines.append(f"{prefix}{rows[0][0]}: {rows[0][1]}")
            lines += [f"      {key + ':':<13}{value}" for key, value in rows[1:]]

    audio_tracks = tracks_of_kind(details, TrackKind.AUDIO)
    if audio_tracks:
        lines += ["", "Audio"]
        for track in audio_tracks:
            prefix = "  • " if len(audio_tracks) == 1 else f"  Track {track.id}: "
            rows = [
                (
                    "Codec",
                    f"{track.codec or '—'}" + (f" ({track.codec_desc})" if track.codec_desc else ""),
                ),
                ("Sample rate", f"{track.sample_rate / 1000:g} kHz" if track.sample_rate else "—"),
                (
                    "Channels",
                    f"{track.channels} ({track.channel_layout})" if track.channels and track.channel_layout else (str(track.channels) if track.channels else "—"),
                ),
                ("Bitrate", format_bitrate(track.bitrate) if track.bitrate else "—"),
            ]
            if track.language:
                rows.append(("Language", track.language))
            lines.append(f"{prefix}{rows[0][0]}: {rows[0][1]}")
            lines += [f"      {key + ':':<13}{value}" for key, value in rows[1:]]

    subtitle_tracks = tracks_of_kind(details, TrackKind.SUBTITLE)
    if subtitle_tracks:
        lines += ["", "Subtitles"]
        for track in subtitle_tracks:
            name = track.title or (track.language.upper() if track.language else f"Track {track.id}")
            source = "external" if track.is_external else "embedded"
            codec = track.codec or "—"
            lines.append(f"  • {name}: {codec} ({source})")
    else:
        lines += ["", "Subtitles", "  • none"]

    return "\n".join(lines)
