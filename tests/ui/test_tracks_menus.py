"""Phase 8 UI integration tests: Audio/Video menus, track cycling, per-file
selection policy, secondary subtitles, audio sync and screenshots.

Requires a display with OpenGL (use xvfb-run on headless Linux).
"""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.core.models import PlaybackState
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


def _open_and_wait(app, qapp: QApplication, media) -> None:
    app.controller.open(str(media))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    assert pump(qapp, lambda: len(app.controller.audio_tracks()) >= 2)


def _menu_action(menu, text: str):
    for action in menu.actions():
        if action.text().split("\t")[0] == text:
            return action
    raise AssertionError(f"no action {text!r} in {[a.text() for a in menu.actions()]}")


def test_audio_menu_lists_and_selects_tracks(app, qapp, qtbot, multi_track_mkv):
    _open_and_wait(app, qapp, multi_track_mkv)
    menu = app.window._audio_menu
    app.window._populate_audio_menu(menu)

    texts = [a.text() for a in menu.actions()]
    assert "Disabled" in texts
    # Language codes are displayed as names since Phase 12.
    assert sum("French" in t for t in texts) == 1
    assert sum("English" in t for t in texts) == 1

    _menu_action(menu, "French (AAC)").trigger()
    assert pump(qapp, lambda: app.controller.selected_audio_track() == 2)
    app.window._populate_audio_menu(menu)
    assert _menu_action(menu, "French (AAC)").isChecked()

    _menu_action(menu, "Disabled").trigger()
    assert pump(qapp, lambda: app.controller.selected_audio_track() is None)


def test_video_menu_lists_and_selects_tracks(app, qapp, qtbot, multi_track_mkv):
    _open_and_wait(app, qapp, multi_track_mkv)
    menu = app.window._video_menu
    app.window._populate_video_menu(menu)

    texts = [a.text() for a in menu.actions()]
    assert any("Main video" in t for t in texts)
    assert any("Bonus video" in t and "160×90" in t for t in texts)

    _menu_action(menu, "Bonus video (MPEG4) — 160×90").trigger()
    assert pump(qapp, lambda: app.controller.selected_video_track() == 2)


def test_cycle_audio_shortcut_b(app, qapp, qtbot, multi_track_mkv):
    _open_and_wait(app, qapp, multi_track_mkv)
    assert app.controller.selected_audio_track() == 1

    qtbot.keyClick(app.window, Qt.Key.Key_B)
    assert pump(qapp, lambda: app.controller.selected_audio_track() == 2)
    assert "Audio: Track 2" in app.window.statusBar().currentMessage()

    qtbot.keyClick(app.window, Qt.Key.Key_B)
    assert pump(qapp, lambda: app.controller.selected_audio_track() is None)

    qtbot.keyClick(app.window, Qt.Key.Key_B)
    assert pump(qapp, lambda: app.controller.selected_audio_track() == 1)


def test_track_selection_resets_per_file(app, qapp, qtbot, multi_track_mkv):
    """Selections are per-file: a fresh load starts from engine defaults."""
    _open_and_wait(app, qapp, multi_track_mkv)
    app.controller.select_audio_track(2)
    app.controller.select_video_track(2)
    assert pump(qapp, lambda: app.controller.selected_audio_track() == 2)

    # Re-open (same file): the controller's per-file policy must reset.
    app.controller.open(str(multi_track_mkv))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    assert pump(qapp, lambda: app.controller.selected_audio_track() == 1)
    assert pump(qapp, lambda: app.controller.selected_video_track() == 1)


def test_secondary_subtitle_menu(app, qapp, qtbot, multi_track_mkv):
    _open_and_wait(app, qapp, multi_track_mkv)
    menu = app.window._subtitles_menu
    app.window._populate_subtitles_menu(menu)

    secondary = None
    for action in menu.actions():
        if action.text() == "Secondary Track":
            secondary = action.menu()
            break
    assert secondary is not None

    track_actions = [a for a in secondary.actions() if a.text().split("\t")[0] != "None"]
    assert track_actions, "secondary menu should list the embedded subtitle track"
    track_actions[0].trigger()
    assert pump(qapp, lambda: app.controller.selected_secondary_subtitle_track() == 1)

    app.window._populate_subtitles_menu(menu)
    for action in menu.actions():
        if action.text() == "Secondary Track":
            secondary = action.menu()
            break
    _menu_action(secondary, "None").trigger()
    assert pump(qapp, lambda: app.controller.selected_secondary_subtitle_track() is None)


def test_audio_sync_shortcuts_and_status(app, qapp, qtbot, multi_track_mkv):
    _open_and_wait(app, qapp, multi_track_mkv)
    assert app.controller.audio_delay == pytest.approx(0.0, abs=1e-6)

    qtbot.keyClick(app.window, Qt.Key.Key_Minus)
    assert pump(qapp, lambda: app.controller.audio_delay < -0.01)
    assert "Audio delay: -0.05 s" in app.window.statusBar().currentMessage()

    qtbot.keyClick(app.window, Qt.Key.Key_Plus)
    assert pump(qapp, lambda: abs(app.controller.audio_delay) < 1e-6)
    qtbot.keyClick(app.window, Qt.Key.Key_Equal)
    assert pump(qapp, lambda: app.controller.audio_delay > 0.01)

    qtbot.keyClick(app.window, Qt.Key.Key_Minus, Qt.KeyboardModifier.ShiftModifier)
    assert pump(qapp, lambda: abs(app.controller.audio_delay) < 1e-6)


def test_screenshot_action_saves_png(app, qapp, qtbot, multi_track_mkv, tmp_path, monkeypatch):
    _open_and_wait(app, qapp, multi_track_mkv)
    monkeypatch.setattr(app.window, "_screenshot_directory", lambda: tmp_path)

    qtbot.keyClick(app.window, Qt.Key.Key_S)
    assert pump(qapp, lambda: any(tmp_path.glob("glint-*.png")))
    assert "Screenshot saved" in app.window.statusBar().currentMessage()


def test_audio_menu_shows_sync_section(app, qapp, multi_track_mkv):
    _open_and_wait(app, qapp, multi_track_mkv)
    menu = app.window._audio_menu
    app.window._populate_audio_menu(menu)
    labels = [a.text() for a in menu.actions()]
    assert any("Audio Sync" in label for label in labels)
    sync = next(a.menu() for a in menu.actions() if a.text() == "Audio Sync")
    sync_texts = [a.text() for a in sync.actions()]
    assert any(t.startswith("Earlier") for t in sync_texts)
    assert any(t.startswith("Later") for t in sync_texts)
    assert any(t.startswith("Reset") for t in sync_texts)
