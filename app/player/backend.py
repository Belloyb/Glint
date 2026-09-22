"""Engine-agnostic player backend contract.

The backend layer wraps a multimedia engine (libmpv today; libVLC is the
designated fallback should the licensing path ever demand it) and exposes a
small synchronous API plus a listener interface for engine events.

Threading contract (important):

* Backend methods are called on the GUI thread.
* Listener callbacks are invoked on one of the engine's internal threads.
  Implementations must treat them as "emit a thread-safe notification and
  return" — e.g. emitting a queued Qt signal. Calling back into the backend
  from inside a listener callback can deadlock the engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Protocol

from app.core.media_info import MediaDetails
from app.core.models import MediaInfo, PlaybackState, TrackInfo
from app.core.subtitles import SubtitleAppearance

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class PlayerErrorCode(Enum):
    """Machine-readable reason for a playback failure."""

    FILE_NOT_FOUND = auto()
    PERMISSION_DENIED = auto()
    UNSUPPORTED_FORMAT = auto()  # unrecognised container / unusable track layout
    DECODER_FAILED = auto()
    AUDIO_OUTPUT_FAILED = auto()
    NETWORK_FAILED = auto()
    TIMEOUT = auto()
    ENGINE_ERROR = auto()  # engine misbehaved in an unexpected way
    UNKNOWN = auto()


_DEFAULT_USER_MESSAGES: dict[PlayerErrorCode, str] = {
    PlayerErrorCode.FILE_NOT_FOUND: "The file could not be found. It may have been moved, renamed or deleted.",
    PlayerErrorCode.PERMISSION_DENIED: "You do not have permission to read this file.",
    PlayerErrorCode.UNSUPPORTED_FORMAT: "This file's format is not supported, or the file is damaged.",
    PlayerErrorCode.DECODER_FAILED: "The media could not be decoded (missing or broken codec support).",
    PlayerErrorCode.AUDIO_OUTPUT_FAILED: "Audio playback failed. Check your audio output device.",
    PlayerErrorCode.NETWORK_FAILED: "The stream could not be read (network error).",
    PlayerErrorCode.TIMEOUT: "The operation timed out.",
    PlayerErrorCode.ENGINE_ERROR: "The playback engine reported an internal error.",
    PlayerErrorCode.UNKNOWN: "Playback failed for an unknown reason.",
}


def user_message(code: PlayerErrorCode) -> str:
    """Return the default user-facing message for an error code."""
    return _DEFAULT_USER_MESSAGES.get(code, _DEFAULT_USER_MESSAGES[PlayerErrorCode.UNKNOWN])


@dataclass(frozen=True)
class PlayerError:
    """A playback failure, as reported to the UI layer.

    ``message`` is safe to show to a user; ``detail`` carries engine-specific
    text and is only written to the log.
    """

    code: PlayerErrorCode
    message: str
    detail: str = ""

    def __str__(self) -> str:
        if self.detail:
            return f"{self.code.name}: {self.message} ({self.detail})"
        return f"{self.code.name}: {self.message}"


class BackendListener(Protocol):
    """Receives engine events. See the module docstring for threading rules."""

    def on_state_changed(self, state: PlaybackState) -> None: ...
    def on_media_loaded(self, info: MediaInfo) -> None: ...
    def on_tracks_changed(self, tracks: list[TrackInfo]) -> None: ...
    def on_position_changed(self, position: float) -> None: ...
    def on_duration_changed(self, duration: float) -> None: ...
    def on_error(self, error: PlayerError) -> None: ...
    def on_log(self, level: str, component: str, message: str) -> None: ...
    def on_buffering_changed(self, percent: int | None) -> None:
        """Buffering progress for streams/slow sources: ``None`` = not
        buffering, ``0..99`` = buffering at that fill percentage."""
    def on_stream_title(self, title: str) -> None:
        """A network stream announced a new title (ICY/ICY metadata)."""


class PlayerBackend(ABC):
    """Abstract playback engine.

    All methods are safe to call from the GUI thread only. Reads are exposed
    as properties; every mutation that the user can trigger has a ``set_*``
    method.
    """

    # ------------------------------------------------------------- lifecycle
    @abstractmethod
    def create_video_surface(self, parent: QWidget | None = None) -> QWidget:
        """Create the widget the engine renders video into."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release the engine. Must be called after the video surface died."""

    # ------------------------------------------------------------- transport
    @abstractmethod
    def open(self, uri: str) -> None: ...
    @abstractmethod
    def play(self) -> None: ...
    @abstractmethod
    def pause(self) -> None: ...
    @abstractmethod
    def toggle_play_pause(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def seek(self, position: float, precise: bool = True) -> None: ...
    @abstractmethod
    def seek_relative(self, delta: float, precise: bool = False) -> None: ...

    # -------------------------------------------------------------- playback
    @abstractmethod
    def set_speed(self, speed: float) -> None: ...
    @property
    @abstractmethod
    def speed(self) -> float: ...
    @abstractmethod
    def step_frame(self, forward: bool = True) -> None: ...

    # ---------------------------------------------------------------- tracks
    @abstractmethod
    def tracks(self) -> list[TrackInfo]:
        """Snapshot of the current media's tracks (audio/video/subtitle)."""

    @abstractmethod
    def media_details(self) -> MediaDetails:
        """Snapshot of the current media's details for the info dialog."""

    @abstractmethod
    def select_subtitle_track(self, track_id: int | None) -> None:
        """Select a subtitle track by id, or disable subtitles with ``None``."""

    @abstractmethod
    def selected_subtitle_track(self) -> int | None:
        """The selected subtitle track id, or ``None`` when disabled."""

    @abstractmethod
    def set_subtitle_visibility(self, visible: bool) -> None: ...
    @property
    @abstractmethod
    def subtitle_visibility(self) -> bool: ...

    @abstractmethod
    def add_subtitle_file(self, path: str, title: str | None = None) -> None:
        """Load an external subtitle file and select it."""

    @abstractmethod
    def set_subtitle_delay(self, delay: float) -> None: ...
    @property
    @abstractmethod
    def subtitle_delay(self) -> float: ...

    @abstractmethod
    def set_subtitle_appearance(self, appearance: SubtitleAppearance) -> None:
        """Apply subtitle font/size/color/position (partial updates allowed)."""

    @property
    @abstractmethod
    def subtitle_appearance(self) -> SubtitleAppearance:
        """Current subtitle rendering options."""

    # ------------------------------------------- audio/video track selection
    # Track ids are the engine's per-kind ids (audio, video and subtitle ids
    # are independent namespaces — same semantics as the subtitle endpoints
    # above). ``None`` disables the track type.
    # Engine quirk (libmpv 0.40, verified): selecting an id that does not
    # exist in the current file *disables* the track type instead of raising
    # (readback is False). Menus build ids from the engine's own track list,
    # so invalid ids cannot originate from the UI.
    @abstractmethod
    def select_audio_track(self, track_id: int | None) -> None:
        """Select an audio track by id, or disable audio with ``None``."""

    @abstractmethod
    def selected_audio_track(self) -> int | None:
        """The selected audio track id, or ``None`` when disabled."""

    @abstractmethod
    def select_video_track(self, track_id: int | None) -> None:
        """Select a video track by id, or disable video with ``None``."""

    @abstractmethod
    def selected_video_track(self) -> int | None:
        """The selected video track id, or ``None`` when disabled."""

    @abstractmethod
    def select_secondary_subtitle_track(self, track_id: int | None) -> None:
        """Select a subtitle track to display *in addition* (secondary)."""

    @abstractmethod
    def selected_secondary_subtitle_track(self) -> int | None:
        """The secondary subtitle track id, or ``None`` when disabled."""

    @abstractmethod
    def reset_track_selections(self) -> None:
        """Return to the engine's default track selection (all kinds).

        Used for the per-file selection policy: the controller calls this
        whenever a new media finishes loading, so selections never leak from
        one file into the next (a stale numeric id would silently disable
        tracks on files that lack that id).
        """

    # ----------------------------------------------------------------- audio
    @abstractmethod
    def set_audio_delay(self, delay: float) -> None:
        """Shift audio relative to video (positive = audio plays later)."""

    @property
    @abstractmethod
    def audio_delay(self) -> float: ...

    # ------------------------------------------------------------ screenshots
    @abstractmethod
    def screenshot_to(self, path: str) -> bool:
        """Write a screenshot of the current frame to ``path``.

        Returns ``False`` (never raises) when no frame is available or the
        file cannot be written.
        """


    # ----------------------------------------------------------- engine options
    # (settings endpoints; all runtime-applyable where the engine allows)
    @abstractmethod
    def audio_devices(self) -> list[tuple[str, str]]:
        """Available audio output devices as (id, description)."""

    @abstractmethod
    def set_audio_device(self, device_id: str) -> None: ...
    @property
    @abstractmethod
    def audio_device(self) -> str: ...

    @abstractmethod
    def set_hardware_decoding(self, enabled: bool) -> None: ...
    @property
    @abstractmethod
    def hardware_decoding(self) -> bool: ...

    @abstractmethod
    def set_deinterlace(self, enabled: bool) -> None: ...
    @property
    @abstractmethod
    def deinterlace(self) -> bool: ...

    @abstractmethod
    def set_sub_auto_load_external(self, enabled: bool) -> None:
        """Toggle engine auto-loading of sidecar subtitle files."""

    # ----------------------------------------------------------------- audio
    @abstractmethod
    def set_volume(self, volume: int) -> None: ...
    @property
    @abstractmethod
    def volume(self) -> int: ...
    @abstractmethod
    def set_mute(self, muted: bool) -> None: ...
    @property
    @abstractmethod
    def muted(self) -> bool: ...

    # --------------------------------------------------------------- queries
    @property
    @abstractmethod
    def state(self) -> PlaybackState: ...
    @property
    @abstractmethod
    def position(self) -> float | None: ...
    @property
    @abstractmethod
    def duration(self) -> float | None: ...
