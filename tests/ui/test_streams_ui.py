"""Phase 9 UI tests: Open URL dialog, stream playback via a local HTTP
server, buffering badge and ICY stream-title reflection.

Requires a display with OpenGL (use xvfb-run on headless Linux).
"""

from __future__ import annotations

import http.server
import os
import socketserver
import threading

import pytest
from PySide6.QtCore import Qt

from app.core.models import PlaybackState
from app.ui.dialogs import OpenUrlDialog, is_supported_stream_url
from tests.ui.conftest import destroy_application, pump

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="requires a display with OpenGL (use xvfb-run on headless Linux)",
)


@pytest.fixture
def app(qtbot, qapp, tmp_path):
    from app.application import Application

    application = Application(qapp, mpv_options={"ao": "null"}, settings_path=tmp_path / "settings.json")
    window = application.window
    window.show()
    window.activateWindow()
    qapp.processEvents()
    yield application
    destroy_application(application, qapp)


@pytest.fixture(scope="module")
def stream_url(tmp_path_factory: pytest.TempPathFactory):
    """A local HTTP server serving a faststart clip (see the Phase 9 player
    tests for why faststart matters: without it the stream cannot be
    demuxed over rangeless HTTP)."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate the stream test media")
    directory = tmp_path_factory.mktemp("stream")
    media = directory / "stream.mp4"
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

    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = _Server(
        ("127.0.0.1", 0),
        lambda *args: http.server.SimpleHTTPRequestHandler(*args, directory=str(directory)),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/stream.mp4"
    server.shutdown()


# ---------------------------------------------------------------- dialog unit
def test_url_validation_rules():
    assert is_supported_stream_url("http://example.com/stream")
    assert is_supported_stream_url("HTTPS://example.com:8443/live")
    assert is_supported_stream_url("rtsp://cam.local/ch0")
    assert not is_supported_stream_url("file:///etc/passwd")
    assert not is_supported_stream_url("javascript:alert(1)")
    assert not is_supported_stream_url("http://")  # no host
    assert not is_supported_stream_url("not a url")
    assert not is_supported_stream_url("youtube.com/watch?v=x")  # no scheme


def test_open_url_dialog_flow(qtbot, qapp):
    dialog = OpenUrlDialog()
    qtbot.addWidget(dialog)
    from PySide6.QtWidgets import QDialogButtonBox

    open_button = dialog._buttons.button(QDialogButtonBox.StandardButton.Open)
    assert not open_button.isEnabled()

    dialog._edit.setText("garbage")
    assert not open_button.isEnabled()
    assert dialog._validation.isVisibleTo(dialog)

    dialog._edit.setText("http://example.com/live")
    qapp.processEvents()
    assert open_button.isEnabled()
    assert not dialog._validation.isVisibleTo(dialog)

    dialog._on_accept()
    assert dialog.url == "http://example.com/live"


def test_open_url_dialog_cancel(qtbot):
    dialog = OpenUrlDialog()
    qtbot.addWidget(dialog)
    dialog._edit.setText("http://example.com/live")
    dialog.reject()
    assert dialog.url is None


# ------------------------------------------------------------ integration
def test_open_url_dialog_accepts_and_plays(app, qapp, qtbot, stream_url, monkeypatch):
    """Drive the dialog end-to-end against a local HTTP stream."""
    monkeypatch.setattr(
        "app.ui.main_window.OpenUrlDialog.exec",
        lambda self: self._edit.setText(stream_url) or self._on_accept() or 1,
    )
    app.window._open_url()
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    assert app.queue.playlist.current_index == 0
    assert app.queue.playlist.items()[0].uri == stream_url
    # The URL lands in recents like any played media (async: mediaLoaded
    # drives the recents update, so pump for it).
    assert pump(qapp, lambda: app.window._recents.entries()[:1] == (stream_url,))


def test_open_url_shortcut_ctrl_u(app, qapp, qtbot, stream_url, monkeypatch):
    monkeypatch.setattr(
        "app.ui.main_window.OpenUrlDialog.exec",
        lambda self: self._edit.setText(stream_url) or self._on_accept() or 1,
    )
    qtbot.keyClick(app.window, Qt.Key.Key_U, Qt.KeyboardModifier.ControlModifier)
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)


def test_buffering_badge_follows_signal(app, qapp):
    badge = app.window._video_area._buffering_badge
    assert not badge.isVisibleTo(app.window._video_area)
    app.window._on_buffering(45)
    assert badge.isVisibleTo(app.window._video_area)
    assert "45%" in badge.text()
    app.window._on_buffering(None)
    assert not badge.isVisibleTo(app.window._video_area)


def test_stream_title_updates_window_and_status(app, qapp):
    app.window._on_stream_title("Some Live Show")
    assert app.window.windowTitle() == "Some Live Show — Glint"
    assert "Some Live Show" in app.window.statusBar().currentMessage()
