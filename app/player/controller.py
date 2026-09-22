"""Qt-facing façade over a :class:`~app.player.backend.PlayerBackend`.

This is the single place where the GUI talks to the playback engine
(requirement §6 of the spec). Public methods must be called on the GUI thread.
Engine events arrive on backend threads and are relayed to Qt consumers as
signals — Qt auto-queues cross-thread signal delivery to the receiver's thread,
which satisfies the backend's "emit only, never touch widgets" rule.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from app.core.media_info import MediaDetails
from app.core.models import MediaInfo, PlaybackState, TrackInfo, TrackKind
from app.core.playback import clamp_speed, clamp_volume, next_speed
from app.core.subtitles import SubtitleAppearance
from app.player.backend import BackendListener, PlayerBackend, PlayerError
from app.player.keep_awake import DisplayKeepAwake
from app.player.mpv_backend import MpvBackend
from app.utils.logging import get_logger

logger = get_logger("player.controller")

# libmpv pushes ~16 time-pos updates per second (measured); we re-emit at most
# this often to keep the UI cheap. Large position jumps (seeks) are always
# forwarded immediately so scrubbing feels instant.
_POSITION_EMIT_INTERVAL = 0.1
_POSITION_JUMP_THRESHOLD = 1.0

_LOG_LEVELS = {
    "fatal": logging.ERROR,
    "error": logging.ERROR,
    "warn": logging.WARNING,
}


class PlayerController(QObject):
    """Signal-based player API consumed by the UI layer."""

    stateChanged = Signal(object)  # PlaybackState
    mediaLoaded = Signal(object)  # MediaInfo
    tracksChanged = Signal(list)  # list[TrackInfo]
    positionChanged = Signal(float)  # seconds
    durationChanged = Signal(float)  # seconds
    errorOccurred = Signal(object)  # PlayerError
    volumeChanged = Signal(int)
    mutedChanged = Signal(bool)
    speedChanged = Signal(float)
    subtitleDelayChanged = Signal(float)
    audioDelayChanged = Signal(float)
    bufferingChanged = Signal(object)  # int | None (percent; None = not buffering)
    streamTitleChanged = Signal(str)
    softwareRenderingDetected = Signal()

    def __init__(
        self,
        mpv_options: Mapping[str, Any] | None = None,
        parent: QObject | None = None,
        backend_factory: Callable[[BackendListener], PlayerBackend] | None = None,
        keep_awake: DisplayKeepAwake | None = None,
    ) -> None:
        super().__init__(parent)
        # The engine is injectable for tests (e.g. the position-throttle unit
        # tests drive a fake backend instead of a real libmpv instance).
        self._backend: PlayerBackend = (
            backend_factory(self)
            if backend_factory is not None
            else MpvBackend(listener=self, options=mpv_options)
        )
        self._media: MediaInfo | None = None
        self._last_position_emit = 0.0
        self._last_emitted_position = 0.0
        self._autoplay_on_open = True
        self._buffering_percent: int | None = None
        self._software_renderer_reported = False
        self._stream_title: str | None = None
        # Track selections are per-file: reset to engine defaults whenever a
        # new media finishes loading. Connected to our own queued signal so
        # the (thread-unsafe) backend call happens on the GUI thread.
        self.mediaLoaded.connect(self._apply_per_file_track_policy)
        # Display sleep inhibition: Windows' SetThreadExecutionState is a
        # per-THREAD request, so it must run on a thread that outlives
        # playback — this object's (GUI) thread. Connecting to our own
        # stateChanged signal gives exactly that: engine-thread callbacks
        # emit, Qt auto-queues the slot onto the GUI thread.
        self._keep_awake = keep_awake if keep_awake is not None else DisplayKeepAwake()
        self.stateChanged.connect(self._sync_keep_awake)

    # ---------------------------------------------- BackendListener callbacks
    # Invoked on engine threads: emit signals only — never touch widgets,
    # never call back into the backend.
    def on_state_changed(self, state: PlaybackState) -> None:
        logger.debug("state -> %s", state.name)
        self.stateChanged.emit(state)

    def _sync_keep_awake(self, state: PlaybackState) -> None:
        """GUI-thread slot: hold the display awake exactly while playing."""
        if state is PlaybackState.PLAYING:
            self._keep_awake.acquire()
        else:
            # PAUSED, ENDED, ERROR, IDLE, LOADING: the user is not watching
            # moving pictures — the OS power plan should apply again.
            self._keep_awake.release()

    def on_media_loaded(self, info: MediaInfo) -> None:
        self._media = info
        self.mediaLoaded.emit(info)

    def on_tracks_changed(self, tracks: list[TrackInfo]) -> None:
        self.tracksChanged.emit(tracks)

    def on_position_changed(self, position: float) -> None:
        now = time.monotonic()
        jumped = abs(position - self._last_emitted_position) >= _POSITION_JUMP_THRESHOLD
        if jumped or (now - self._last_position_emit) >= _POSITION_EMIT_INTERVAL:
            self._last_position_emit = now
            self._last_emitted_position = position
            self.positionChanged.emit(position)

    def on_duration_changed(self, duration: float) -> None:
        self.durationChanged.emit(duration)

    def on_error(self, error: PlayerError) -> None:
        logger.error("playback error: %s", error)
        self.errorOccurred.emit(error)

    def on_log(self, level: str, component: str, message: str) -> None:
        logger.log(_LOG_LEVELS.get(level, logging.DEBUG), "mpv[%s] %s", component, message)
        # The engine warns once when it ends up on a software rasterizer
        # (Remote Desktop, missing GPU drivers). Surfacing it to the user
        # once per session lets them act (install drivers / play locally)
        # instead of wondering why video is black while audio plays.
        if not self._software_renderer_reported and "software renderer" in message.lower():
            self._software_renderer_reported = True
            self.softwareRenderingDetected.emit()

    def on_buffering_changed(self, percent: int | None) -> None:
        self._buffering_percent = percent
        self.bufferingChanged.emit(percent)

    def on_stream_title(self, title: str) -> None:
        self._stream_title = title
        self.streamTitleChanged.emit(title)

    def _apply_per_file_track_policy(self, _info: MediaInfo) -> None:
        """GUI-thread companion of ``on_media_loaded`` (queued via signal).

        Without this, a numeric aid/vid/sid from the previous file leaks into
        the next one: the engine resolves an id that no longer exists to
        "track type disabled" (verified against libmpv 0.40 — readback
        ``False``), silently muting e.g. a single-audio file after a
        multi-audio one. Resetting to the engine defaults is also what VLC
        does: selections apply to the current file only.
        """
        self._backend.reset_track_selections()

    # --------------------------------------------------------- public API (GUI)
    def open(self, uri: str) -> None:
        """Open a local path or URL (replaces whatever is playing).

        With ``autoplay_on_open`` disabled the media is loaded paused.
        """
        self._backend.open(uri)
        if not self._autoplay_on_open:
            self._backend.pause()

    @property
    def autoplay_on_open(self) -> bool:
        return self._autoplay_on_open

    @autoplay_on_open.setter
    def autoplay_on_open(self, enabled: bool) -> None:
        self._autoplay_on_open = bool(enabled)

    def play(self) -> None:
        self._backend.play()

    def pause(self) -> None:
        self._backend.pause()

    def toggle_play_pause(self) -> None:
        self._backend.toggle_play_pause()

    def stop(self) -> None:
        self._backend.stop()

    def seek(self, position: float) -> None:
        self._backend.seek(position)

    def seek_relative(self, delta: float) -> None:
        self._backend.seek_relative(delta)

    # -------------------------------------------------------------- playback
    def set_speed(self, speed: float) -> None:
        """Set the playback speed (clamped to the supported range)."""
        value = clamp_speed(speed)
        if value == self.speed:
            return
        self._backend.set_speed(value)
        self.speedChanged.emit(value)

    def step_speed(self, direction: int) -> None:
        """Step to the next/previous speed preset (``+1`` / ``-1``)."""
        self.set_speed(next_speed(self.speed, direction))

    def reset_speed(self) -> None:
        self.set_speed(1.0)

    def step_frame(self, forward: bool = True) -> None:
        """Advance one frame (implies paused playback)."""
        self._backend.step_frame(forward)

    # ---------------------------------------------------------------- tracks
    def tracks(self) -> list[TrackInfo]:
        """Snapshot of the current media's tracks."""
        return self._backend.tracks()

    def subtitle_tracks(self) -> list[TrackInfo]:
        return [track for track in self.tracks() if track.kind is TrackKind.SUBTITLE]

    def audio_tracks(self) -> list[TrackInfo]:
        return [track for track in self.tracks() if track.kind is TrackKind.AUDIO]

    def video_tracks(self) -> list[TrackInfo]:
        return [track for track in self.tracks() if track.kind is TrackKind.VIDEO]

    def media_details(self) -> MediaDetails:
        """Snapshot of the current media's details (for the info dialog)."""
        return self._backend.media_details()

    def select_subtitle_track(self, track_id: int | None) -> None:
        self._backend.select_subtitle_track(track_id)

    def selected_subtitle_track(self) -> int | None:
        return self._backend.selected_subtitle_track()

    def cycle_subtitles(self) -> int | None:
        """Cycle through subtitle tracks: none → first → … → last → none.

        Returns the newly selected track id (``None`` = disabled).
        """
        subtitle_ids = sorted(track.id for track in self.subtitle_tracks())
        if not subtitle_ids:
            return None
        current = self.selected_subtitle_track()
        if current is None:
            nxt: int | None = subtitle_ids[0]
        else:
            try:
                position = subtitle_ids.index(current)
            except ValueError:
                nxt = subtitle_ids[0]
            else:
                nxt = subtitle_ids[position + 1] if position + 1 < len(subtitle_ids) else None
        self.select_subtitle_track(nxt)
        return nxt

    # -------------------------------------------------- audio/video selection
    def select_audio_track(self, track_id: int | None) -> None:
        self._backend.select_audio_track(track_id)

    def selected_audio_track(self) -> int | None:
        return self._backend.selected_audio_track()

    def cycle_audio_tracks(self) -> int | None:
        """Cycle through audio tracks: none → first → … → last → none.

        Returns the newly selected track id (``None`` = disabled).
        """
        audio_ids = sorted(track.id for track in self.audio_tracks())
        if not audio_ids:
            return None
        current = self.selected_audio_track()
        if current is None:
            nxt: int | None = audio_ids[0]
        else:
            try:
                position = audio_ids.index(current)
            except ValueError:
                nxt = audio_ids[0]
            else:
                nxt = audio_ids[position + 1] if position + 1 < len(audio_ids) else None
        self.select_audio_track(nxt)
        return nxt

    def select_video_track(self, track_id: int | None) -> None:
        self._backend.select_video_track(track_id)

    def selected_video_track(self) -> int | None:
        return self._backend.selected_video_track()

    def select_secondary_subtitle_track(self, track_id: int | None) -> None:
        """Show a subtitle track *in addition* to the primary selection."""
        self._backend.select_secondary_subtitle_track(track_id)

    def selected_secondary_subtitle_track(self) -> int | None:
        return self._backend.selected_secondary_subtitle_track()

    def add_subtitle_file(self, path: str, title: str | None = None) -> None:
        """Load an external subtitle file and select it."""
        self._backend.add_subtitle_file(path, title=title)

    def set_subtitle_visibility(self, visible: bool) -> None:
        self._backend.set_subtitle_visibility(visible)

    def toggle_subtitle_visibility(self) -> bool:
        visible = not self._backend.subtitle_visibility
        self._backend.set_subtitle_visibility(visible)
        return visible

    @property
    def subtitle_visibility(self) -> bool:
        return self._backend.subtitle_visibility

    # ----------------------------------------------------------- subtitle sync
    def set_subtitle_delay(self, delay: float) -> None:
        self._backend.set_subtitle_delay(delay)
        self.subtitleDelayChanged.emit(delay)

    def nudge_subtitle_delay(self, delta: float) -> None:
        self.set_subtitle_delay(self.subtitle_delay + delta)

    def reset_subtitle_delay(self) -> None:
        self.set_subtitle_delay(0.0)

    @property
    def subtitle_delay(self) -> float:
        return self._backend.subtitle_delay

    # --------------------------------------------------------------- audio sync
    def set_audio_delay(self, delay: float) -> None:
        self._backend.set_audio_delay(delay)
        self.audioDelayChanged.emit(delay)

    def nudge_audio_delay(self, delta: float) -> None:
        self.set_audio_delay(self.audio_delay + delta)

    def reset_audio_delay(self) -> None:
        self.set_audio_delay(0.0)

    @property
    def audio_delay(self) -> float:
        return self._backend.audio_delay

    # -------------------------------------------------------------- screenshots
    def screenshot(self, directory: Path) -> Path | None:
        """Save a PNG of the current frame into ``directory``.

        Returns the written path, or ``None`` on failure (nothing playing,
        unwritable directory) — never raises. The engine-side audio/video
        sync offset is unaffected; subtitles are included in the image.
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("screenshot directory %s could not be created", directory)
            return None
        stamp = datetime.now().astimezone()
        path = directory / f"glint-{stamp:%Y%m%d-%H%M%S}.png"
        suffix = 1
        while path.exists():
            path = directory / f"glint-{stamp:%Y%m%d-%H%M%S}-{suffix}.png"
            suffix += 1
        if self._backend.screenshot_to(str(path)):
            logger.info("screenshot saved to %s", path)
            return path
        return None

    # ---------------------------------------------------- subtitle appearance
    def set_subtitle_appearance(self, **changes) -> None:
        """Apply partial subtitle appearance changes
        (``font``, ``size`` ``#RRGGBB``/``#AARRGGBB`` ``color``, ``position``)."""
        current = self._backend.subtitle_appearance
        updated = SubtitleAppearance(
            font=changes.get("font", current.font),
            size=changes.get("size", current.size),
            color=changes.get("color", current.color),
            position=changes.get("position", current.position),
        )
        self._backend.set_subtitle_appearance(updated)

    @property
    def subtitle_appearance(self) -> SubtitleAppearance:
        return self._backend.subtitle_appearance

    # ----------------------------------------------------------- engine options
    def audio_devices(self) -> list[tuple[str, str]]:
        """Available audio output devices as (id, description)."""
        return self._backend.audio_devices()

    def set_audio_device(self, device_id: str) -> None:
        self._backend.set_audio_device(device_id)

    @property
    def audio_device(self) -> str:
        return self._backend.audio_device

    def set_hardware_decoding(self, enabled: bool) -> None:
        self._backend.set_hardware_decoding(enabled)

    @property
    def hardware_decoding(self) -> bool:
        return self._backend.hardware_decoding

    def set_deinterlace(self, enabled: bool) -> None:
        self._backend.set_deinterlace(enabled)

    @property
    def deinterlace(self) -> bool:
        return self._backend.deinterlace

    def set_sub_auto_load_external(self, enabled: bool) -> None:
        self._backend.set_sub_auto_load_external(enabled)

    # ----------------------------------------------------------------- audio
    def set_volume(self, volume: int) -> None:
        clamped = clamp_volume(volume)
        if clamped == self.volume:
            return
        self._backend.set_volume(clamped)
        self.volumeChanged.emit(clamped)

    def set_mute(self, muted: bool) -> None:
        if muted == self.muted:
            return
        self._backend.set_mute(muted)
        self.mutedChanged.emit(muted)

    def toggle_mute(self) -> None:
        self.set_mute(not self.muted)

    def create_video_surface(self, parent: QWidget | None = None) -> QWidget:
        return self._backend.create_video_surface(parent)

    def shutdown(self) -> None:
        """Release engine resources. Call after the video surface is gone."""
        self._keep_awake.release()
        self._backend.shutdown()

    # ---------------------------------------------------------------- queries
    @property
    def state(self) -> PlaybackState:
        return self._backend.state

    @property
    def position(self) -> float | None:
        return self._backend.position

    @property
    def duration(self) -> float | None:
        return self._backend.duration

    @property
    def volume(self) -> int:
        return self._backend.volume

    @property
    def muted(self) -> bool:
        return self._backend.muted

    @property
    def speed(self) -> float:
        return self._backend.speed

    @property
    def buffering(self) -> bool:
        """True while a stream/slow source is filling its cache."""
        return self._buffering_percent is not None

    @property
    def buffering_percent(self) -> int | None:
        return self._buffering_percent

    @property
    def stream_title(self) -> str | None:
        """The most recent ICY title announced by a network stream."""
        return self._stream_title

    @property
    def current_media(self) -> MediaInfo | None:
        return self._media
