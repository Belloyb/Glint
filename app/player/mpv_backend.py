"""libmpv implementation of :class:`app.player.backend.PlayerBackend`.

Design notes
------------
* All engine events are converted to listener calls; the listener (the
  :class:`app.player.controller.PlayerController`) only relays them as Qt
  signals. Nothing in this module touches Qt.
* Engine callbacks run on python-mpv's event thread. They must never call
  back into libmpv (deadlock risk) and must never raise — every handler is
  exception-guarded.
* User-initiated intent (``_pause_requested``, ``_stop_requested``,
  ``_opening``) is tracked on the GUI side so that engine events can be
  interpreted correctly (e.g. distinguishing "stopped by user" from "replaced
  by a new loadfile" from "reached end of file").
* External subtitles: ``sub-auto=fuzzy`` lets the engine auto-load subtitle
  files whose name contains the video's stem (verified against libmpv 0.40);
  loaded files appear in ``track-list`` as external tracks.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.media_info import MediaDetails
from app.core.models import MediaInfo, PlaybackState, TrackInfo, TrackKind
from app.core.playback import VOLUME_MAX, VOLUME_UNITY, clamp_speed, clamp_volume
from app.core.playlist import title_for_uri
from app.core.subtitles import (
    SubtitleAppearance,
    clamp_position,
    clamp_size,
    is_valid_color,
)
from app.player.backend import (
    PlayerBackend,
    PlayerError,
    PlayerErrorCode,
    user_message,
)
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.player.backend import BackendListener

logger = get_logger("player.mpv")


def _ensure_libmpv_loadable() -> None:
    """Make libmpv findable on Windows *before* python-mpv is imported.

    python-mpv verifies at **import time** that one of ``mpv-1.dll`` /
    ``mpv-2.dll`` / ``libmpv-2.dll`` is reachable via ``%PATH%`` and raises
    ``OSError`` otherwise. The documented Windows install ("drop
    ``libmpv-2.dll`` into the project root") therefore only works if the
    root is prepended to ``%PATH%`` before that import. Best effort, never
    raises; a no-op on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    names = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")
    for name in names:
        try:
            ctypes.CDLL(name)
            return  # already resolvable via PATH / loader directories
        except OSError:
            continue

    from app.utils.paths import project_root

    directories: list[Path] = []
    if getattr(sys, "frozen", False):
        # PyInstaller 6 onedir places bundled binaries in _internal (=
        # sys._MEIPASS at runtime); the exe directory covers manual
        # "portable" placement next to the executable.
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            directories.append(Path(bundle))
        directories.append(Path(sys.executable).resolve().parent)
    directories.append(project_root())
    for directory in directories:
        for name in names:
            dll = directory / name
            if not dll.is_file():
                continue
            try:
                os.add_dll_directory(str(directory))
                os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
                try:
                    ctypes.CDLL(str(dll))
                except OSError:
                    # Legacy search order (also consults %PATH%): resolves
                    # dependencies the secure load mode misses.
                    ctypes.CDLL(str(dll), winmode=0)
                return
            except OSError:
                logger.warning("found %s but could not load it", dll)


# Must execute before `import mpv` (see _ensure_libmpv_loadable).
_ensure_libmpv_loadable()

import mpv  # deliberately after the %PATH% fix-up above

# Grace period before reporting an unclassified open failure: mpv's causal
# log line may still be queued behind the end-file event (see
# _report_open_error_deferred).
_ERROR_REPORT_GRACE_SECONDS = 0.15

# Volume bounds live in app.core.playback (VOLUME_UNITY/VOLUME_MAX) so the
# UI, settings and this backend agree on the 0..200 amplified range.

#: engine track type string -> our TrackKind
_TRACK_KINDS = {
    "audio": TrackKind.AUDIO,
    "video": TrackKind.VIDEO,
    "sub": TrackKind.SUBTITLE,
}




def _base_options() -> dict[str, Any]:
    """Engine options for a deterministic, safe, app-owned player.

    ``config``/``load_scripts``/``ytdl`` are disabled so a user's ``mpv.conf``
    or third-party scripts can never change our player's behaviour
    (untrusted-input policy, Phase 1 doc §10).
    """
    return {
        "vo": "libmpv",  # we render via the render API
        "hwdec": "auto-safe",  # hardware decode when reliable, silent fallback
        "idle": "yes",  # keep the core alive between files
        "keep_open": "no",  # after EOF go idle; our UI shows the idle state
        "config": "no",  # never read a user's mpv.conf (determinism)
        "load_scripts": "no",  # no bundled lua scripts
        "ytdl": "no",  # no yt-dlp hook (explicit opt-in later, Phase 9)
        "input_default_bindings": "no",
        "input_vo_keyboard": "no",
        "osc": "no",
        "audio_display": "no",  # no fabricated video track for cover art
        "network_timeout": 30,
        # Auto-load external subtitles whose filename contains the video
        # stem (e.g. "movie.en.srt" next to "movie.mkv").
        "sub_auto": "fuzzy",
        # Allow the `volume` property above 100 (software amplification,
        # VLC-style "200% volume"). Without this mpv caps amplification at
        # its own default of 130.
        "volume-max": VOLUME_MAX,
    }


def _classify_failure(detail: str) -> PlayerErrorCode:
    """Map engine error text onto a user-meaningful error code."""
    text = (detail or "").lower()
    if "no such file" in text or "not found" in text or "no such device" in text:
        return PlayerErrorCode.FILE_NOT_FOUND
    if "permission" in text or ("access" in text and "denied" in text):
        return PlayerErrorCode.PERMISSION_DENIED
    if "unrecognized" in text and "format" in text:
        return PlayerErrorCode.UNSUPPORTED_FORMAT
    if "failed to recognize" in text or "format" in text:
        return PlayerErrorCode.UNSUPPORTED_FORMAT
    # Truncated media or a layout no stream demuxer can open (verified:
    # a non-faststart MP4 over plain HTTP — "Cannot seek backward in linear
    # streams", then "partial file" / "no audio or video data played").
    if "partial file" in text or "no audio or video data" in text:
        return PlayerErrorCode.UNSUPPORTED_FORMAT
    if "decoder" in text or "codec" in text or "decode" in text:
        return PlayerErrorCode.DECODER_FAILED
    if "audio" in text and ("output" in text or "device" in text):
        return PlayerErrorCode.AUDIO_OUTPUT_FAILED
    # Timeouts are a specific kind of network failure (verified strings from
    # libmpv 0.40 logs: "Connection timed out", "timeout").
    if "timed out" in text or "timeout" in text:
        return PlayerErrorCode.TIMEOUT
    if "network" in text or "connection" in text or "refused" in text or "unreachable" in text:
        return PlayerErrorCode.NETWORK_FAILED
    return PlayerErrorCode.UNKNOWN


def _decode(value: Any) -> str:
    """mpv delivers strings as bytes; normalise to text defensively."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if value is None:
        return ""
    return str(value)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _track_id_or_none(value: Any) -> int | None:
    """Normalise an aid/vid/sid readback: int id, or ``None`` when disabled.

    The engine reports a disabled track type as ``False``; ids are per-kind
    positive integers.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_track_list(value: Any) -> list[TrackInfo]:
    """Convert the engine's ``track-list`` node into TrackInfo objects.

    Never raises: malformed entries are skipped.
    """
    tracks: list[TrackInfo] = []
    if not isinstance(value, list):
        return tracks
    for entry in value:
        if not isinstance(entry, dict):
            continue
        kind = _TRACK_KINDS.get(_decode(entry.get("type")))
        track_id = entry.get("id")
        if kind is None or not isinstance(track_id, int):
            continue
        language = entry.get("lang")
        title = entry.get("title")
        codec = entry.get("codec")
        tracks.append(
            TrackInfo(
                id=track_id,
                kind=kind,
                title=_decode(title) or None,
                language=_decode(language) or None,
                codec=_decode(codec) or None,
                codec_desc=_decode(entry.get("codec-desc")) or None,
                is_default=bool(entry.get("default", False)),
                is_forced=bool(entry.get("forced", False)),
                is_external=bool(entry.get("external", False)),
                is_selected=bool(entry.get("selected", False)),
                width=_optional_int(entry.get("demux-w")),
                height=_optional_int(entry.get("demux-h")),
                framerate=_optional_float(entry.get("demux-fps")),
                sample_rate=_optional_int(entry.get("demux-samplerate")),
                channels=_optional_int(entry.get("demux-channel-count")),
                channel_layout=_decode(entry.get("demux-channels")) or None,
                bitrate=_optional_int(entry.get("demux-bitrate")),
            )
        )
    return tracks


class MpvBackend(PlayerBackend):
    """PlayerBackend implementation on top of libmpv (via python-mpv)."""

    def __init__(
        self,
        listener: BackendListener,
        options: Mapping[str, Any] | None = None,
    ) -> None:
        self._listener = listener
        self._state = PlaybackState.IDLE
        self._current_uri: str | None = None
        self._known_duration: float | None = None
        self._opening = False
        self._stop_requested = False
        self._pause_requested = False
        self._shutting_down = False
        self._recent_error_logs: deque[str] = deque(maxlen=10)
        self._lock = threading.RLock()
        # Stream observation state (Phase 9): cache/buffering + icy titles.
        self._cache_percent: int | None = None
        self._cache_paused = False
        self._last_buffering: int | None = None
        self._stream_title: str | None = None
        self._error_report_timer: threading.Timer | None = None

        merged = _base_options()
        if options:
            merged.update(options)

        self._mpv = mpv.MPV(
            loglevel="warn",
            log_handler=self._on_mpv_log,
            **merged,
        )
        self._install_callbacks()
        logger.info("libmpv backend initialised (%s)", self._engine_version())

    # ----------------------------------------------------------------- setup
    def _engine_version(self) -> str:
        try:
            return _decode(self._mpv.mpv_version)
        except Exception:  # noqa: BLE001 — best-effort version probe, safe fallback
            return "unknown"

    def _install_callbacks(self) -> None:
        self._mpv.event_callback("file-loaded")(self._on_file_loaded)
        self._mpv.event_callback("end-file")(self._on_end_file)
        self._mpv.observe_property("pause", self._on_pause_changed)
        self._mpv.observe_property("time-pos", self._on_time_pos)
        self._mpv.observe_property("duration", self._on_duration)
        self._mpv.observe_property("track-list", self._on_track_list)
        self._mpv.observe_property("cache-buffering-state", self._on_cache_state)
        self._mpv.observe_property("paused-for-cache", self._on_paused_for_cache)
        self._mpv.observe_property("metadata", self._on_metadata)

    # ------------------------------------------- engine event handlers (mpv thread)
    # These run on python-mpv's event thread: no libmpv calls, no raises.
    def _on_file_loaded(self, event: Any) -> None:
        try:
            with self._lock:
                self._opening = False
                new_state = PlaybackState.PAUSED if self._pause_requested else PlaybackState.PLAYING
                changed = self._set_state_locked(new_state)
                info = MediaInfo(
                    uri=self._current_uri or "",
                    title=title_for_uri(self._current_uri or ""),
                    duration=self._known_duration,
                )
            if changed:
                self._listener.on_state_changed(new_state)
            self._listener.on_media_loaded(info)
        except Exception:
            logger.exception("error in file-loaded handler")

    def _report_open_error_deferred(self, error: PlayerError) -> None:
        """Report an unclassified open failure after a short grace period.

        mpv's end-file event carries only a generic "loading failed"; the
        causal line (e.g. "HTTP error 404 File not found") arrives as a log
        event whose position in the event pipe relative to end-file is not
        guaranteed. Waiting ~150 ms lets it land; if nothing better appears
        the original UNKNOWN error is reported unchanged. The timer is
        cancelled by open()/shutdown() so a new attempt never reports a
        stale error.
        """
        def report() -> None:
            with self._lock:
                if self._shutting_down or self._current_uri is None:
                    return
                best = error
                try:
                    lines = list(self._recent_error_logs)
                except RuntimeError:
                    lines = []
                for line in reversed(lines):
                    candidate = _classify_failure(line)
                    if candidate is not PlayerErrorCode.UNKNOWN:
                        best = PlayerError(
                            code=candidate,
                            message=user_message(candidate),
                            detail=f"{error.detail} — {line}",
                        )
                        break
            self._listener.on_error(best)

        with self._lock:
            if self._error_report_timer is not None:
                self._error_report_timer.cancel()
            timer = threading.Timer(_ERROR_REPORT_GRACE_SECONDS, report)
            timer.daemon = True
            self._error_report_timer = timer
        timer.start()

    def _on_end_file(self, event: Any) -> None:
        error_needs_grace = False
        try:
            payload = event.as_dict()
            reason = _decode(payload.get("reason", "unknown")) or "unknown"
            file_error = _decode(payload.get("file_error"))

            with self._lock:
                opening = self._opening
                stop_requested = self._stop_requested
                self._stop_requested = False
                if self._shutting_down:
                    return
                if opening and reason == "stop":
                    # The previous file was replaced by our own loadfile();
                    # LOADING is already the correct state — nothing to report.
                    return
                if opening:
                    # The file we tried to open failed (or ended) before it
                    # could finish loading; file-loaded never fired.
                    self._opening = False
                if stop_requested:
                    new_state, error = PlaybackState.STOPPED, None
                elif reason == "eof":
                    new_state, error = PlaybackState.ENDED, None
                elif reason == "error":
                    detail = file_error or reason
                    code = _classify_failure(detail)
                    if code is PlayerErrorCode.UNKNOWN:
                        # libmpv only reports a generic "loading failed" here
                        # (verified 0.40); the real cause — e.g. "Connection
                        # refused" or "HTTP error 404 File not found" — is in
                        # the engine's error log lines, which are cleared on
                        # every open() so they describe *this* attempt only.
                        try:
                            lines = list(self._recent_error_logs)
                        except RuntimeError:  # deque mutated during snapshot
                            lines = []
                        for line in reversed(lines):
                            candidate = _classify_failure(line)
                            if candidate is not PlayerErrorCode.UNKNOWN:
                                code = candidate
                                detail = f"{detail} — {line}"
                                break
                    error = PlayerError(code=code, message=user_message(code), detail=detail)
                    if code is PlayerErrorCode.UNKNOWN:
                        error_needs_grace = True
                    new_state = PlaybackState.ERROR
                else:  # 'quit', 'redirect', or anything unexpected
                    new_state, error = PlaybackState.STOPPED, None
                changed = self._set_state_locked(new_state)

            if changed:
                self._listener.on_state_changed(new_state)
            if error is not None:
                if error_needs_grace:
                    self._report_open_error_deferred(error)
                else:
                    self._listener.on_error(error)
        except Exception:
            logger.exception("error in end-file handler")

    def _on_pause_changed(self, _name: str, value: Any) -> None:
        try:
            with self._lock:
                if self._state not in (PlaybackState.PLAYING, PlaybackState.PAUSED):
                    return
                if value is False and self._pause_requested:
                    # mpv briefly unpauses internally while performing a
                    # frame-back-step seek and then re-pauses itself; our
                    # intent is still paused, so ignore the transient.
                    return
                new_state = PlaybackState.PAUSED if value else PlaybackState.PLAYING
                changed = self._set_state_locked(new_state)
            if changed:
                self._listener.on_state_changed(new_state)
        except Exception:
            logger.exception("error in pause observer")

    def _on_time_pos(self, _name: str, value: Any) -> None:
        if value is None:
            return
        try:
            self._listener.on_position_changed(float(value))
        except Exception:
            logger.exception("error in time-pos observer")

    def _on_duration(self, _name: str, value: Any) -> None:
        try:
            if value is None:
                return
            duration = float(value)
            with self._lock:
                self._known_duration = duration
            self._listener.on_duration_changed(duration)
        except Exception:
            logger.exception("error in duration observer")

    def _on_track_list(self, _name: str, value: Any) -> None:
        try:
            self._listener.on_tracks_changed(_parse_track_list(value))
        except Exception:
            logger.exception("error in track-list observer")

    def _on_cache_state(self, _name: str, value: Any) -> None:
        """cache-buffering-state: None (no cache activity) or 0..100."""
        try:
            percent = None if value is None else int(value)
            if percent is not None:
                percent = max(0, min(100, percent))
            self._cache_percent = percent
            self._emit_buffering()
        except Exception:
            logger.exception("error in cache-state observer")

    def _on_paused_for_cache(self, _name: str, value: Any) -> None:
        """paused-for-cache: playback stalled because the cache ran empty."""
        try:
            self._cache_paused = bool(value)
            self._emit_buffering()
        except Exception:
            logger.exception("error in paused-for-cache observer")

    def _emit_buffering(self) -> None:
        """Derive 'is buffering + percent' and notify on change only.

        The engine reports two independent facts (fill percentage and
        playback-stalled); the UI gets one consolidated signal:
        ``None`` = not buffering, ``0..99`` = buffering (100 never emitted
        — a full cache means not buffering).
        """
        active = self._cache_paused or (
            self._cache_percent is not None and self._cache_percent < 100
        )
        percent: int | None
        if not active:
            percent = None
        elif self._cache_percent is not None and self._cache_percent < 100:
            percent = self._cache_percent
        else:
            percent = 0  # stalled with unknown fill level
        if percent != self._last_buffering:
            self._last_buffering = percent
            self._listener.on_buffering_changed(percent)

    def _on_metadata(self, _name: str, value: Any) -> None:
        """metadata: report ICY stream titles (Shoutcast/Icecast) as they
        change. Local files fire this once at load without an icy-title —
        no notification then."""
        try:
            if not isinstance(value, dict):
                return
            raw = value.get("icy-title")
            title = _decode(raw).strip() if raw else ""
            if title and title != self._stream_title:
                self._stream_title = title
                logger.debug("stream title: %s", title)
                self._listener.on_stream_title(title)
        except Exception:
            logger.exception("error in metadata observer")

    def _on_mpv_log(self, loglevel: Any, prefix: Any, message: Any) -> None:
        # Runs on an engine-internal path; keep it cheap and exception-safe.
        # The log handler must never log its own failure (infinite recursion),
        # so failures are deliberately swallowed.
        try:
            level = _decode(loglevel)
            component = _decode(prefix)
            text = _decode(message).strip()
            # warn is included: ffmpeg reports e.g. "HTTP error 404 File not
            # found" at warn level — the end-file handler needs it to explain
            # failed stream opens.
            if level in ("error", "fatal", "warn"):
                self._recent_error_logs.append(text)
            self._listener.on_log(level, component, text)
        except Exception:  # noqa: BLE001, S110 — deliberate (see comment above)
            pass

    # ------------------------------------------------------- state handling
    def _set_state_locked(self, new_state: PlaybackState) -> bool:
        """Update the state; returns ``True`` if it actually changed."""
        if new_state == self._state:
            return False
        logger.debug("state %s -> %s", self._state.name, new_state.name)
        self._state = new_state
        return True

    # -------------------------------------------------------------- transport
    def open(self, uri: str) -> None:
        if not isinstance(uri, str) or not uri.strip():
            raise ValueError("uri must be a non-empty string")

        # Fast local pre-flight: fail before waking the engine where we can.
        if "://" not in uri:
            path = Path(uri)
            if not path.exists():
                self._report_open_error(PlayerErrorCode.FILE_NOT_FOUND, uri, "path does not exist")
                return
            if not path.is_file():
                self._report_open_error(PlayerErrorCode.UNSUPPORTED_FORMAT, uri, "path is not a regular file")
                return
            if not os.access(path, os.R_OK):
                self._report_open_error(PlayerErrorCode.PERMISSION_DENIED, uri, "os.access(R_OK) is False")
                return

        with self._lock:
            self._current_uri = uri
            self._opening = True
            self._pause_requested = False
            self._known_duration = None
            self._recent_error_logs.clear()
            if self._error_report_timer is not None:
                self._error_report_timer.cancel()
                self._error_report_timer = None
            changed = self._set_state_locked(PlaybackState.LOADING)
        if changed:
            self._listener.on_state_changed(PlaybackState.LOADING)

        logger.info("opening %s", uri)
        try:
            self._mpv.command("loadfile", uri)
        except Exception as exc:
            logger.exception("loadfile failed")
            with self._lock:
                self._opening = False
                changed = self._set_state_locked(PlaybackState.ERROR)
            if changed:
                self._listener.on_state_changed(PlaybackState.ERROR)
            code = PlayerErrorCode.ENGINE_ERROR
            self._listener.on_error(PlayerError(code, user_message(code), str(exc)))

    def _report_open_error(self, code: PlayerErrorCode, uri: str, detail: str) -> None:
        logger.warning("refusing to open %r: %s", uri, detail)
        with self._lock:
            changed = self._set_state_locked(PlaybackState.ERROR)
        if changed:
            self._listener.on_state_changed(PlaybackState.ERROR)
        self._listener.on_error(PlayerError(code, user_message(code), detail))

    def play(self) -> None:
        with self._lock:
            state = self._state
            uri = self._current_uri
        if state == PlaybackState.PAUSED:
            self._pause_requested = False
            self._mpv.pause = False
        elif state in (PlaybackState.IDLE, PlaybackState.STOPPED, PlaybackState.ENDED, PlaybackState.ERROR) and uri:
            self.open(uri)

    def pause(self) -> None:
        with self._lock:
            state = self._state
        if state in (PlaybackState.PLAYING, PlaybackState.LOADING):
            self._pause_requested = True
            self._mpv.pause = True

    def toggle_play_pause(self) -> None:
        with self._lock:
            state = self._state
        if state == PlaybackState.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        with self._lock:
            state = self._state
            if state in (PlaybackState.IDLE, PlaybackState.STOPPED):
                return
            self._stop_requested = True
            self._pause_requested = False
            changed = self._set_state_locked(PlaybackState.STOPPED)
        if state in (PlaybackState.PLAYING, PlaybackState.PAUSED, PlaybackState.LOADING):
            try:
                self._mpv.command("stop")
            except Exception:
                logger.exception("stop command failed")
        if changed:
            self._listener.on_state_changed(PlaybackState.STOPPED)

    def seek(self, position: float, precise: bool = True) -> None:
        with self._lock:
            state = self._state
            duration = self._known_duration
        if state not in (PlaybackState.PLAYING, PlaybackState.PAUSED):
            logger.debug("seek to %.2fs ignored in state %s", position, state.name)
            return
        target = max(0.0, float(position))
        if duration:
            target = min(target, duration)
        flags = "absolute+exact" if precise else "absolute"
        try:
            self._mpv.command("seek", target, flags)
        except Exception:
            logger.exception("seek to %.2fs failed", target)

    def seek_relative(self, delta: float, precise: bool = False) -> None:
        with self._lock:
            state = self._state
        if state not in (PlaybackState.PLAYING, PlaybackState.PAUSED):
            return
        flags = "relative+exact" if precise else "relative"
        try:
            self._mpv.command("seek", float(delta), flags)
        except Exception:
            logger.exception("relative seek %.2fs failed", delta)

    # -------------------------------------------------------------- playback
    def set_speed(self, speed: float) -> None:
        self._mpv.speed = clamp_speed(speed)

    @property
    def speed(self) -> float:
        try:
            return float(self._mpv.speed)
        except (TypeError, ValueError):
            return 1.0

    def step_frame(self, forward: bool = True) -> None:
        """Advance one frame (backwards when ``forward`` is False).

        Frame stepping implies paused playback; if media is playing it is
        paused first so our intent flags and the engine stay in agreement.
        """
        with self._lock:
            state = self._state
        if state not in (PlaybackState.PLAYING, PlaybackState.PAUSED):
            logger.debug("frame step ignored in state %s", state.name)
            return
        if state == PlaybackState.PLAYING:
            self.pause()
        try:
            self._mpv.command("frame-step" if forward else "frame-back-step")
        except Exception:
            logger.exception("frame step failed")

    # ---------------------------------------------------------------- tracks
    def tracks(self) -> list[TrackInfo]:
        return _parse_track_list(self._mpv.track_list)

    def media_details(self) -> MediaDetails:
        """Snapshot of the current media's details (best-effort, never raises)."""

        def read(name: str) -> Any:
            try:
                return getattr(self._mpv, name)
            except Exception:  # noqa: BLE001 — property may be unavailable
                return None

        uri = self._current_uri or ""
        path = _decode(read("path")) or None
        size = _optional_int(read("file_size"))
        container = _decode(read("file_format")) or None
        duration = _optional_float(read("duration"))

        video_params = read("video_params")
        pixel_format = None
        display_aspect = None
        if isinstance(video_params, dict):
            pixel_format = _decode(video_params.get("pixelformat")) or None
            display_aspect = _decode(video_params.get("aspect-name")) or None

        if not path and uri and "://" not in uri:
            path = uri

        return MediaDetails(
            uri=uri,
            title=title_for_uri(uri) if uri else "",
            file_path=path,
            file_size=size,
            container=container,
            duration=duration,
            pixel_format=pixel_format,
            display_aspect=display_aspect,
            tracks=tuple(_parse_track_list(read("track_list"))),
        )

    def select_subtitle_track(self, track_id: int | None) -> None:
        # Verified against libmpv 0.40: sid accepts an int, and False disables.
        self._mpv.sid = int(track_id) if track_id is not None else False

    def selected_subtitle_track(self) -> int | None:
        return _track_id_or_none(self._mpv.sid)

    def set_subtitle_visibility(self, visible: bool) -> None:
        self._mpv.sub_visibility = bool(visible)

    @property
    def subtitle_visibility(self) -> bool:
        return bool(self._mpv.sub_visibility)

    def add_subtitle_file(self, path: str, title: str | None = None) -> None:
        """Load an external subtitle file and select it."""
        local = Path(path)
        if not local.exists():
            self._report_open_error(PlayerErrorCode.FILE_NOT_FOUND, path, "subtitle file does not exist")
            return
        if not local.is_file():
            self._report_open_error(PlayerErrorCode.UNSUPPORTED_FORMAT, path, "subtitle path is not a file")
            return
        args = ["sub-add", str(local), "select"]
        if title:
            args.append(title)
        try:
            self._mpv.command(*args)
            logger.info("added subtitle file %s", path)
        except Exception as exc:
            logger.exception("sub-add failed for %s", path)
            code = PlayerErrorCode.UNSUPPORTED_FORMAT
            self._listener.on_error(
                PlayerError(
                    code,
                    "The subtitle file could not be loaded. It may use an unsupported format.",
                    str(exc),
                )
            )

    def set_subtitle_delay(self, delay: float) -> None:
        self._mpv.sub_delay = float(delay)

    @property
    def subtitle_delay(self) -> float:
        try:
            return float(self._mpv.sub_delay or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def set_subtitle_appearance(self, appearance: SubtitleAppearance) -> None:
        """Apply subtitle rendering options (the dataclass is a full snapshot;
        callers build it from the current value for partial updates)."""
        self._mpv.sub_font = appearance.font
        self._mpv.sub_font_size = clamp_size(appearance.size)
        if is_valid_color(appearance.color):
            self._mpv.sub_color = appearance.color
        else:
            logger.warning("ignoring invalid subtitle color %r", appearance.color)
        self._mpv.sub_pos = clamp_position(appearance.position)

    @property
    def subtitle_appearance(self) -> SubtitleAppearance:
        try:
            color = _decode(self._mpv.sub_color) or "#FFFFFFFF"
        except Exception:  # noqa: BLE001 — property read must not raise
            color = "#FFFFFFFF"
        try:
            font = _decode(self._mpv.sub_font) or "sans-serif"
            size = clamp_size(float(self._mpv.sub_font_size))
            position = clamp_position(float(self._mpv.sub_pos))
        except Exception:  # noqa: BLE001 — property read must not raise
            font, size, position = "sans-serif", 38.0, 100.0
        return SubtitleAppearance(font=font, size=size, color=color, position=position)

    # ------------------------------------------------- audio/video track select
    def select_audio_track(self, track_id: int | None) -> None:
        # Verified against libmpv 0.40: aid accepts an int, False disables;
        # an id missing from the file disables audio (readback False).
        self._mpv.aid = int(track_id) if track_id is not None else False

    def selected_audio_track(self) -> int | None:
        return _track_id_or_none(self._mpv.aid)

    def select_video_track(self, track_id: int | None) -> None:
        self._mpv.vid = int(track_id) if track_id is not None else False

    def selected_video_track(self) -> int | None:
        return _track_id_or_none(self._mpv.vid)

    def select_secondary_subtitle_track(self, track_id: int | None) -> None:
        # secondary-sid selects a track shown *in addition* to the primary
        # subtitle; False clears it (verified round-trip on libmpv 0.40).
        self._mpv.secondary_sid = int(track_id) if track_id is not None else False

    def selected_secondary_subtitle_track(self) -> int | None:
        return _track_id_or_none(self._mpv.secondary_sid)

    def reset_track_selections(self) -> None:
        """Back to engine defaults: auto-select primary tracks, no secondary.

        ``auto`` lets the engine pick (embedded default flag, or the first
        auto-loaded sidecar for subtitles); the secondary subtitle is a
        per-file choice and always starts cleared.
        """
        self._mpv.aid = "auto"
        self._mpv.vid = "auto"
        self._mpv.sid = "auto"
        self._mpv.secondary_sid = False

    # --------------------------------------------------------------- audio sync
    def set_audio_delay(self, delay: float) -> None:
        self._mpv.audio_delay = float(delay)

    @property
    def audio_delay(self) -> float:
        try:
            return float(self._mpv.audio_delay or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # -------------------------------------------------------------- screenshots
    def screenshot_to(self, path: str) -> bool:
        """Write the current frame (with subtitles) to ``path`` as PNG.

        Works for both the render-API video output and vo=null; it fails
        cleanly (returns ``False``) when nothing is playing or the target
        directory is not writable.
        """
        try:
            self._mpv.command("screenshot-to-file", path, "subtitles")
            return True
        except Exception:  # a failed screenshot must not raise into the UI
            logger.exception("screenshot to %r failed", path)
            return False

    # ----------------------------------------------------------- engine options
    def audio_devices(self) -> list[tuple[str, str]]:
        try:
            devices = self._mpv.audio_device_list
        except Exception:
            logger.exception("could not enumerate audio devices")
            return [("auto", "Autoselect device")]
        result: list[tuple[str, str]] = []
        for device in devices or []:
            if isinstance(device, dict) and device.get("name"):
                result.append(
                    (_decode(device.get("name")), _decode(device.get("description")) or "Unknown")
                )
        return result or [("auto", "Autoselect device")]

    def set_audio_device(self, device_id: str) -> None:
        try:
            self._mpv.audio_device = str(device_id)
        except Exception:
            logger.exception("could not set audio device %r", device_id)

    @property
    def audio_device(self) -> str:
        try:
            return _decode(self._mpv.audio_device) or "auto"
        except Exception:  # noqa: BLE001 — property read must not raise
            return "auto"

    def set_hardware_decoding(self, enabled: bool) -> None:
        try:
            self._mpv.hwdec = "auto-safe" if enabled else "no"
        except Exception:
            logger.exception("could not set hardware decoding")

    @property
    def hardware_decoding(self) -> bool:
        try:
            value = self._mpv.hwdec
        except Exception:  # noqa: BLE001 — property read must not raise
            return True
        if isinstance(value, list):  # engine readback form: ["auto-safe"]
            value = value[0] if value else "no"
        if isinstance(value, str):
            return value.lower() not in ("no", "false", "")
        return bool(value)

    def set_deinterlace(self, enabled: bool) -> None:
        try:
            self._mpv.deinterlace = bool(enabled)
        except Exception:
            logger.exception("could not set deinterlace")

    @property
    def deinterlace(self) -> bool:
        try:
            return bool(self._mpv.deinterlace)
        except Exception:  # noqa: BLE001 — property read must not raise
            return False

    def set_sub_auto_load_external(self, enabled: bool) -> None:
        try:
            self._mpv.sub_auto = "fuzzy" if enabled else "no"
        except Exception:
            logger.exception("could not set external subtitle auto-loading")

    # ----------------------------------------------------------------- audio
    def set_volume(self, volume: int) -> None:
        self._mpv.volume = float(clamp_volume(volume))

    @property
    def volume(self) -> int:
        try:
            return round(float(self._mpv.volume))
        except (TypeError, ValueError):
            return VOLUME_UNITY

    def set_mute(self, muted: bool) -> None:
        self._mpv.mute = bool(muted)

    @property
    def muted(self) -> bool:
        return bool(self._mpv.mute)

    # --------------------------------------------------------------- queries
    @property
    def state(self) -> PlaybackState:
        return self._state

    @property
    def position(self) -> float | None:
        value = self._mpv.time_pos
        return float(value) if value is not None else None

    @property
    def duration(self) -> float | None:
        value = self._mpv.duration
        return float(value) if value is not None else None

    # ------------------------------------------------------------- lifecycle
    def create_video_surface(self, parent: Any = None) -> Any:
        # Imported lazily so headless environments (contract tests, CI) never
        # pull Qt/OpenGL into the process.
        from app.player.mpv_surface import MpvVideoSurface

        return MpvVideoSurface(self._mpv, parent=parent)

    def shutdown(self) -> None:
        with self._lock:
            if self._error_report_timer is not None:
                self._error_report_timer.cancel()
                self._error_report_timer = None
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
        logger.info("shutting down libmpv backend")
        try:
            self._mpv.terminate()
        except Exception:
            logger.exception("error while terminating libmpv")
