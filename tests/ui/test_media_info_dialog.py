"""UI integration tests for the media information dialog."""

from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

from app.core.media_info import format_details_report
from app.core.models import PlaybackState
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
    info = getattr(window, "_info_dialog", None)
    if info is not None:
        info.close()
    destroy_application(application, qapp)


def _open_and_settle(app, qapp, media) -> None:
    app.controller.open(str(media))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    assert pump(qapp, lambda: len(app.controller.media_details().tracks) >= 2)


def test_dialog_opens_with_populated_sections(app, qapp, qtbot, subtitle_mkv):
    _open_and_settle(app, qapp, subtitle_mkv)
    app.window._show_media_info()
    dialog = app.window._info_dialog
    assert dialog.isVisible()

    from PySide6.QtWidgets import QLabel

    texts = [l.text() for l in dialog._scroll.findChildren(QLabel)]
    assert any(t == "General" for t in texts)
    assert any(t == "Video" for t in texts)
    assert any(t == "Audio" for t in texts)
    assert any(t == "Subtitles" for t in texts)
    assert "320×180" in texts           # resolution row
    assert "12.00 fps" in texts         # framerate row
    assert any("mkv" == t for t in texts)
    assert any(t.startswith("44.1 kHz") for t in texts)


def test_copy_to_clipboard_puts_report(app, qapp, subtitle_mkv):
    _open_and_settle(app, qapp, subtitle_mkv)
    app.window._show_media_info()
    dialog = app.window._info_dialog

    QApplication.clipboard().setText("")
    dialog._copy_button.click()
    text = QApplication.clipboard().text()
    assert str(subtitle_mkv) in text
    assert "mpeg4" in text
    assert "320×180" in text


def test_dialog_refreshes_when_new_media_loads(app, qapp, subtitle_mkv, sample_wav):
    _open_and_settle(app, qapp, subtitle_mkv)
    app.window._show_media_info()
    dialog = app.window._info_dialog
    assert dialog._report and "mkv" in dialog._report

    app.controller.open(str(sample_wav))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    assert pump(qapp, lambda: "wav" in dialog._report), "dialog did not refresh on new media"
    assert "pcm_s16le" in dialog._report


def test_dialog_shows_placeholder_when_idle(app, qapp, qtbot):
    app.window._show_media_info()
    dialog = app.window._info_dialog
    assert dialog.isVisible()
    assert "No media loaded." in dialog._report


def test_report_matches_controller_snapshot(app, qapp, subtitle_mkv):
    _open_and_settle(app, qapp, subtitle_mkv)
    report = format_details_report(app.controller.media_details())
    assert str(subtitle_mkv) in report
    assert "1920" not in report  # fixture is 320×180 — guard against mixups
