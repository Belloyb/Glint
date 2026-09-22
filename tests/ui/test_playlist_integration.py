"""Real-engine integration tests for playlist playback (auto-advance etc.).

Runs against actual libmpv under a display; audio is nulled. Media are tiny
synthetic files, so each case finishes in a few seconds.
"""

from __future__ import annotations

import os
import shutil

import pytest

from app.core.models import PlaybackState
from app.core.playlist import RepeatMode
from tests.ui.conftest import destroy_application, pump

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="requires a display with OpenGL (use xvfb-run on headless Linux)",
)


@pytest.fixture
def app(qtbot, qapp, tmp_path):
    from app.application import Application

    application = Application(qapp, mpv_options={"ao": "null"}, queue_seed=42, settings_path=tmp_path / "settings.json")
    window = application.window
    window.show()
    window.activateWindow()
    qapp.processEvents()
    yield application
    destroy_application(application, qapp)


def _make_wavs(tmp_path, count: int, seconds: float = 1.0):
    from tests.conftest import make_wav

    return [str(make_wav(tmp_path / f"tone{i}.wav", seconds=seconds)) for i in range(count)]


def test_auto_advance_to_next_track(app, qapp, tmp_path):
    uris = _make_wavs(tmp_path, 2)
    app.queue.add(uris)
    app.queue.play_index(0)

    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    # First file is 1 s; the second must start on its own afterwards.
    assert pump(
        qapp,
        lambda: app.queue.playlist.current_index == 1
        and app.controller.state is PlaybackState.PLAYING,
        timeout=15.0,
    ), f"auto-advance failed (index={app.queue.playlist.current_index}, state={app.controller.state})"


def test_repeat_one_replays_same_track(app, qapp, tmp_path):
    uris = _make_wavs(tmp_path, 2)
    app.queue.add(uris)
    app.queue.set_repeat(RepeatMode.ONE)
    app.queue.play_index(0)

    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    saw_replay = pump(
        qapp,
        lambda: app.controller.state is PlaybackState.LOADING,
        timeout=15.0,
    )
    assert saw_replay, "repeat-one never restarted the track"
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    assert app.queue.playlist.current_index == 0


def test_error_skips_to_next_playable_file(app, qapp, tmp_path, corrupt_file):
    good = _make_wavs(tmp_path, 1)[0]
    app.queue.add([str(corrupt_file), good])
    app.queue.play_index(0)

    assert pump(
        qapp,
        lambda: app.queue.playlist.current_index == 1
        and app.controller.state is PlaybackState.PLAYING,
        timeout=15.0,
    ), f"error-skip failed (index={app.queue.playlist.current_index}, state={app.controller.state})"


def test_next_and_previous_navigation(app, qapp, tmp_path):
    uris = _make_wavs(tmp_path, 3, seconds=5.0)  # long enough to not end mid-test
    app.queue.add(uris)
    app.queue.play_index(0)
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)

    app.queue.next(auto=False)
    assert pump(qapp, lambda: app.queue.playlist.current_index == 1)
    app.queue.next(auto=False)
    assert pump(qapp, lambda: app.queue.playlist.current_index == 2)
    app.queue.previous()
    assert pump(qapp, lambda: app.queue.playlist.current_index == 1)
    # Pump: the index flips as soon as `open` is issued; PLAYING follows
    # asynchronously (asserting it directly races the engine under load).
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)


def test_next_shortcut_and_buttons(app, qtbot, qapp, tmp_path):
    from PySide6.QtCore import Qt

    uris = _make_wavs(tmp_path, 2, seconds=5.0)
    app.queue.add(uris)
    app.queue.play_index(0)
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)

    qtbot.keyClick(app.window, Qt.Key.Key_N)
    assert pump(qapp, lambda: app.queue.playlist.current_index == 1)

    app.window._controls.btn_prev.click()
    assert pump(qapp, lambda: app.queue.playlist.current_index == 0)


def test_playlist_panel_footer_and_marker(app, qapp, tmp_path):
    uris = _make_wavs(tmp_path, 2)
    app.queue.add(uris)
    app.queue.play_index(0)
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)

    footer = app.window._playlist_panel._footer_label.text()
    assert footer.startswith("2 items")
    # Duration is filled in once the engine reports it.
    assert pump(qapp, lambda: "·" in app.window._playlist_panel._footer_label.text())
    assert app.window._playlist_panel._view.currentIndex().row() == 0


def test_dropped_folder_scans_and_plays(app, qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QUrl

    if not shutil.which("ffmpeg"):  # generate a real media file for scanning
        pytest.skip("ffmpeg not available")

    media_dir = tmp_path / "library"
    media_dir.mkdir()
    subprocess_files = media_dir / "clip.mp4"
    import subprocess

    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "mpeg4", "-q:v", "7", "-c:a", "aac", "-shortest",
            str(subprocess_files),
        ],
        check=True,
        timeout=60,
    )

    # Synthesising a QDropEvent in PySide6 is unreliable (mimeData() may
    # crash); the behaviour lives in handle_dropped_urls, tested directly.
    app.window.handle_dropped_urls([QUrl.fromLocalFile(str(media_dir))])

    assert pump(
        qapp,
        lambda: len(app.queue.playlist) == 1 and app.controller.state is PlaybackState.PLAYING,
        timeout=15.0,
    ), "dropped folder did not scan + play"
