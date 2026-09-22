"""Phase 9 backend contract tests: network streams.

All against a local HTTP server (no external network): normal playback,
error mapping (refused connection, HTTP 404), buffering signal plumbing and
ICY stream titles via a minimal icecast emulation.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
import time
from typing import ClassVar

import pytest

from app.core.models import PlaybackState
from app.player.backend import PlayerErrorCode
from app.player.mpv_backend import _classify_failure

MP3_SECONDS = 30


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


def _serve(handler: type[http.server.BaseHTTPRequestHandler], port: int) -> _Server:
    server = _Server(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class _IcyHandler(_QuietHandler):
    """Minimal icecast emulation: an MP3 stream with interleaved ICY metadata
    blocks alternating between two titles."""

    METADATA: ClassVar[list[bytes]] = [b"StreamTitle='First Title';", b"StreamTitle='Second Title';"]
    METATAINT = 8192

    def do_GET(self) -> None:
        mp3 = self.server.stream_data  # type: ignore[attr-defined]
        self.send_response(200, "ICY")
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("icy-name", "Glint Test Radio")
        self.send_header("icy-metaint", str(self.METATAINT))
        self.end_headers()
        served, block_index = 0, 0
        while served < len(mp3):
            block = mp3[served : served + self.METATAINT]
            meta = self.METADATA[block_index % len(self.METADATA)]
            block_index += 1
            padded = meta + b"\x00" * (16 * ((len(meta) + 15) // 16) - len(meta))
            try:
                self.wfile.write(block)
                self.wfile.write(bytes([len(padded) // 16]) + padded)
            except OSError:
                return  # client hung up
            served += self.METATAINT


class _MissingHandler(_QuietHandler):
    """Always 404."""

    def do_GET(self) -> None:
        self.send_error(404)


@pytest.fixture(scope="module")
def http_media_server(tmp_path_factory: pytest.TempPathFactory):
    """A plain HTTP server serving a *faststart* MP4.

    Faststart matters: with the moov atom at the end and no HTTP Range
    support the stream is undemuxable ("Cannot seek backward in linear
    streams" — verified against libmpv 0.40), which is a real engine
    behaviour, just not what this fixture is for.
    """
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate the HTTP test media")
    directory = tmp_path_factory.mktemp("http_media")
    media = directory / "clip.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest",
            "-movflags", "+faststart", str(media),
        ],
        check=True,
        timeout=60,
    )
    server = _serve(
        lambda *args: http.server.SimpleHTTPRequestHandler(*args, directory=str(directory)),
        0,  # OS-assigned port
    )
    yield f"http://127.0.0.1:{server.server_address[1]}/clip.mp4"
    server.shutdown()


@pytest.fixture(scope="module")
def icy_server(tmp_path_factory: pytest.TempPathFactory):
    """The mini-icecast (requires an MP3 encoder in ffmpeg)."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate the ICY test stream")
    mp3 = tmp_path_factory.mktemp("icy") / "tone.mp3"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={MP3_SECONDS}",
            "-c:a", "libmp3lame", "-b:a", "64k", str(mp3),
        ],
        check=True,
        timeout=60,
    )
    server = _serve(_IcyHandler, 0)
    server.stream_data = mp3.read_bytes()  # type: ignore[attr-defined]
    yield f"http://127.0.0.1:{server.server_address[1]}/stream"
    server.shutdown()


@pytest.fixture(scope="module")
def missing_server():
    server = _serve(_MissingHandler, 0)
    yield f"http://127.0.0.1:{server.server_address[1]}/missing.mp4"
    server.shutdown()


def _open_and_wait(harness, uri: str) -> None:
    harness.backend.open(uri)
    state = harness.wait_for("state", predicate=lambda s: s is PlaybackState.PLAYING)
    assert state is not None, f"stream never started playing: {uri}"
    # Over HTTP the track list lands shortly after file-loaded/PLAYING.
    tracks = harness.wait_for("tracks", predicate=lambda t: len(t) >= 1)
    assert tracks is not None, f"no tracks reported for stream: {uri}"


def test_http_stream_plays_with_tracks_and_duration(harness, http_media_server):
    _open_and_wait(harness, http_media_server)
    tracks = harness.backend.tracks()
    assert tracks, "stream has no tracks"
    assert any(t.kind.value == "audio" for t in tracks)
    assert harness.backend.duration is not None
    assert harness.backend.duration > 1.0


def test_http_stream_details_have_uri(harness, http_media_server):
    _open_and_wait(harness, http_media_server)
    assert harness.wait_for("duration", predicate=lambda d: d is not None and d > 1.0)
    details = harness.backend.media_details()
    assert details.uri == http_media_server
    assert details.container  # ffmpeg reports the format name


def test_connection_refused_maps_to_network_failed(harness):
    # Port 9 (discard protocol) is closed in the sandbox: instant refusal.
    harness.backend.open("http://127.0.0.1:9/none.mp4")
    error = harness.wait_for("error")
    assert error is not None, "no error reported for a refused connection"
    assert error.code is PlayerErrorCode.NETWORK_FAILED, error
    assert "refused" in error.detail.lower()


def test_http_404_maps_to_file_not_found(harness, missing_server):
    harness.backend.open(missing_server)
    error = harness.wait_for("error")
    assert error is not None, "no error reported for HTTP 404"
    assert error.code is PlayerErrorCode.FILE_NOT_FOUND, error


def test_icy_stream_title_updates(harness, icy_server):
    _open_and_wait(harness, icy_server)
    first = harness.wait_for("stream_title", predicate=lambda t: t == "First Title", timeout=15)
    assert first == "First Title"
    second = harness.wait_for("stream_title", predicate=lambda t: t == "Second Title", timeout=15)
    assert second == "Second Title"


class _StallHandler(_QuietHandler):
    """Serves the first bytes at full speed, then stalls mid-stream — forcing
    the player's cache to run empty (real buffering, not simulated)."""

    FAST_BYTES = 131072
    STALL_SECONDS = 4.0

    def do_GET(self) -> None:  # http.server API name
        data = self.server.stream_data  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data[: self.FAST_BYTES])
            time.sleep(self.STALL_SECONDS)
            self.wfile.write(data[self.FAST_BYTES :])
        except OSError:
            return  # client hung up


@pytest.fixture(scope="module")
def stalling_server(tmp_path_factory: pytest.TempPathFactory):
    """Serves a faststart mp4 (moov atom first) that stalls mid-stream."""
    import shutil as _shutil
    import subprocess as _subprocess

    ffmpeg = _shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate the stalling test stream")
    directory = tmp_path_factory.mktemp("stall")
    path = directory / "stall.mp4"
    _subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-b:a", "32k",
            "-movflags", "+faststart", str(path),
        ],
        check=True,
        timeout=60,
    )
    server = _serve(_StallHandler, 0)
    server.stream_data = path.read_bytes()  # type: ignore[attr-defined]
    yield f"http://127.0.0.1:{server.server_address[1]}/stall.mp4"
    server.shutdown()


def test_buffering_signal_fires_when_stream_stalls(harness, stalling_server):
    """A genuine mid-stream stall must surface as a buffering notification
    (percent < 100), and resume (None) once data flows again."""
    _open_and_wait(harness, stalling_server)
    stalled = harness.wait_for("buffering", predicate=lambda p: p is not None, timeout=20)
    assert stalled is not None, "no buffering notification during a real stream stall"
    resumed = harness.wait_for("buffering", predicate=lambda p: p is None, timeout=20)
    assert resumed is None, "buffering never cleared after the stall"


def test_buffering_derivation_unit():
    """The consolidation logic: percent = cache fill (or 0 when stalled with
    unknown fill); None = not buffering; notifications only on change."""
    from app.player.mpv_backend import MpvBackend

    class _Recorder:
        def __init__(self) -> None:
            self.seen: list[object] = []

        def on_buffering_changed(self, percent: int | None) -> None:
            self.seen.append(percent)

        # unused listener members
        def on_state_changed(self, s): ...
        def on_media_loaded(self, i): ...
        def on_tracks_changed(self, t): ...
        def on_position_changed(self, p): ...
        def on_duration_changed(self, d): ...
        def on_error(self, e): ...
        def on_log(self, l, c, m): ...
        def on_stream_title(self, t): ...

    recorder = _Recorder()
    backend = MpvBackend.__new__(MpvBackend)  # no engine: methods only touch fields
    backend._listener = recorder
    backend._cache_percent = None
    backend._cache_paused = False
    backend._last_buffering = None

    backend._on_cache_state("cache-buffering-state", 40)  # fill 40% → buffering(40)
    backend._on_paused_for_cache("paused-for-cache", True)  # stall, fill still 40 → no change
    backend._on_cache_state("cache-buffering-state", 100)  # full, but still stalled → 0 (unknown)
    backend._on_paused_for_cache("paused-for-cache", False)  # flowing again, full → not buffering
    backend._on_paused_for_cache("paused-for-cache", True)  # stall again → 0
    assert recorder.seen == [40, 0, None, 0]


def test_classify_failure_network_and_timeout():
    """Unit-level: engine log strings map to the right error codes."""
    assert _classify_failure("tcp: Connection to tcp://x failed: Connection refused") is (
        PlayerErrorCode.NETWORK_FAILED
    )
    assert _classify_failure("Connection timed out") is PlayerErrorCode.TIMEOUT
    assert _classify_failure("http: HTTP error 404 File not found") is PlayerErrorCode.FILE_NOT_FOUND
    assert _classify_failure("loading failed") is PlayerErrorCode.UNKNOWN
    # Unstreamable/truncated media (verified strings, libmpv 0.40):
    assert _classify_failure("no audio or video data played") is PlayerErrorCode.UNSUPPORTED_FORMAT
    assert _classify_failure("stream 1, offset 0x2c: partial file") is (
        PlayerErrorCode.UNSUPPORTED_FORMAT
    )
