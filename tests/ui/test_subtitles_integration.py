"""Real-engine UI integration tests for subtitle support (needs a display)."""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt

from app.core.models import PlaybackState
from app.core.subtitles import SUBTITLE_SIZE_PRESETS, mpv_color_to_rgb
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


def _open_and_wait(app, qapp, media) -> None:
    app.controller.open(str(media))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)


def test_subtitles_menu_lists_tracks(app, qapp, qtbot, subtitle_mkv):
    _open_and_wait(app, qapp, subtitle_mkv)
    assert pump(qapp, lambda: len(app.controller.subtitle_tracks()) >= 3)

    menu = app.window._subtitles_menu
    app.window._populate_subtitles_menu(menu)
    texts = [action.text() for action in menu.actions()]
    assert "Disabled" in texts
    external_actions = [t for t in texts if "external" in t]
    assert len(external_actions) == 2  # movie.srt + movie.en.srt (fuzzy auto-load)


def test_cycle_subtitles_round_trip(app, qapp, subtitle_mkv):
    _open_and_wait(app, qapp, subtitle_mkv)
    assert pump(qapp, lambda: len(app.controller.subtitle_tracks()) >= 3)

    track_ids = sorted(t.id for t in app.controller.subtitle_tracks())
    # Cycling from any start must visit every track exactly once, then None.
    visited = [app.controller.cycle_subtitles()]
    for _ in range(len(track_ids)):
        visited.append(app.controller.cycle_subtitles())
    assert None in visited
    non_none = [v for v in visited if v is not None]
    assert len(set(non_none)) == len(track_ids)


def test_cycle_shortcut_j(app, qtbot, qapp, subtitle_mkv):
    _open_and_wait(app, qapp, subtitle_mkv)
    assert pump(qapp, lambda: len(app.controller.subtitle_tracks()) >= 3)

    qtbot.keyClick(app.window, Qt.Key.Key_J)
    assert app.controller.selected_subtitle_track() is not None
    # Keep cycling (bounded): 'disabled' must be reachable.
    for _ in range(len(app.controller.subtitle_tracks()) + 1):
        if app.controller.selected_subtitle_track() is None:
            break
        qtbot.keyClick(app.window, Qt.Key.Key_J)
    assert app.controller.selected_subtitle_track() is None


def test_delay_nudges_and_status_feedback(app, qapp, subtitle_mkv):
    _open_and_wait(app, qapp, subtitle_mkv)

    app.controller.nudge_subtitle_delay(0.25)
    assert app.controller.subtitle_delay == pytest.approx(0.25)
    app.controller.nudge_subtitle_delay(0.25)
    assert app.controller.subtitle_delay == pytest.approx(0.50)
    app.controller.reset_subtitle_delay()
    assert app.controller.subtitle_delay == pytest.approx(0.0)

    status = app.window.statusBar().currentMessage()
    assert "Subtitle delay" in status


def test_delay_shortcuts(app, qtbot, qapp, subtitle_mkv):
    _open_and_wait(app, qapp, subtitle_mkv)

    # The engine stores the delay as float32: use a generous tolerance.
    qtbot.keyClick(app.window, Qt.Key.Key_X)  # later
    assert app.controller.subtitle_delay == pytest.approx(0.1, abs=1e-6)
    qtbot.keyClick(app.window, Qt.Key.Key_Z)  # earlier
    assert app.controller.subtitle_delay == pytest.approx(0.0, abs=1e-6)
    qtbot.keyClick(app.window, Qt.Key.Key_Z, Qt.KeyboardModifier.ShiftModifier)  # reset
    assert app.controller.subtitle_delay == pytest.approx(0.0, abs=1e-6)


def test_appearance_presets_apply(app, qapp, subtitle_mkv):
    _open_and_wait(app, qapp, subtitle_mkv)
    controller = app.controller

    controller.set_subtitle_appearance(size=SUBTITLE_SIZE_PRESETS["Large"])
    assert controller.subtitle_appearance.size == pytest.approx(SUBTITLE_SIZE_PRESETS["Large"])

    controller.set_subtitle_appearance(color="#FFFF00")
    assert mpv_color_to_rgb(controller.subtitle_appearance.color) == "#FFFF00"

    controller.set_subtitle_appearance(position=85)
    assert controller.subtitle_appearance.position == pytest.approx(85)
    # size/color survive a position-only change (partial update semantics)
    assert controller.subtitle_appearance.size == pytest.approx(SUBTITLE_SIZE_PRESETS["Large"])
    assert mpv_color_to_rgb(controller.subtitle_appearance.color) == "#FFFF00"


def test_add_subtitle_file_via_controller(app, qapp, subtitle_mkv, external_srt):
    _open_and_wait(app, qapp, subtitle_mkv)
    assert pump(qapp, lambda: len(app.controller.subtitle_tracks()) >= 3)

    before = len(app.controller.subtitle_tracks())
    app.controller.add_subtitle_file(str(external_srt), title="Manual")
    assert pump(qapp, lambda: len(app.controller.subtitle_tracks()) == before + 1)
    assert app.controller.selected_subtitle_track() is not None
