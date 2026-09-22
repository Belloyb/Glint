"""Shared, Qt-free data models.

These types cross layer boundaries (backend → controller → UI) and therefore
must not depend on Qt or on any concrete playback engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from app.core.languages import language_display_name


class PlaybackState(Enum):
    """High-level playback state machine (engine-agnostic).

    Transitions are driven by the backend layer::

        IDLE -> LOADING -> PLAYING <-> PAUSED
                        -> ERROR            (open/playback failed)
        PLAYING/PAUSED -> STOPPED           (user stop)
        PLAYING        -> ENDED             (end of media)
        any            -> IDLE              (shutdown / future reset)
    """

    IDLE = auto()
    LOADING = auto()
    PLAYING = auto()
    PAUSED = auto()
    STOPPED = auto()
    ENDED = auto()
    ERROR = auto()


class TrackKind(Enum):
    """Kind of a media track (engine-agnostic)."""

    AUDIO = "audio"
    VIDEO = "video"
    SUBTITLE = "subtitle"


@dataclass(frozen=True)
class TrackInfo:
    """One track of the current media, as reported by the engine.

    ``id`` is the engine's track id *within its kind* (audio/video/subtitle
    ids are independent namespaces); selecting a track uses this id.

    The ``demux_*``-style fields are demuxer-level details (only present
    where meaningful: e.g. ``framerate`` only for video tracks,
    ``sample_rate``/``channels`` only for audio tracks).
    """

    id: int
    kind: TrackKind
    title: str | None = None
    language: str | None = None
    codec: str | None = None
    codec_desc: str | None = None
    is_default: bool = False
    is_forced: bool = False
    is_external: bool = False
    is_selected: bool = False
    # Demuxer details (optional):
    width: int | None = None
    height: int | None = None
    framerate: float | None = None  # fps
    sample_rate: int | None = None  # Hz
    channels: int | None = None  # channel count
    channel_layout: str | None = None  # e.g. "stereo", "mono", "5.1"
    bitrate: int | None = None  # bits per second

    @property
    def dimensions(self) -> str | None:
        """``"320×180"`` for video tracks with known dimensions."""
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return None

    @property
    def display_name(self) -> str:
        """Human-friendly label for menus, e.g. ``French (SRT, external)``."""
        name = self.title or language_display_name(self.language)
        if not name:
            name = {TrackKind.AUDIO: "Audio", TrackKind.VIDEO: "Video", TrackKind.SUBTITLE: "Subtitle"}[self.kind]
            if self.id:
                name = f"{name} {self.id}"
        extras: list[str] = []
        if self.codec:
            extras.append(self.codec.upper())
        if self.is_external:
            extras.append("external")
        if self.is_forced:
            extras.append("forced")
        return f"{name} ({', '.join(extras)})" if extras else name


@dataclass(frozen=True)
class MediaInfo:
    """What the UI needs to know about the currently loaded media.

    ``duration`` may be ``None`` briefly after load (the engine reports it
    asynchronously) and for open-ended streams.
    """

    uri: str
    title: str
    duration: float | None = None
