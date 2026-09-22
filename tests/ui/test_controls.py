"""GUI tests for Phase 3 controls: shortcuts, mouse behaviour, fullscreen,
speed and the auto-hide logic.

Requires a display (``xvfb-run -a python -m pytest tests/ui -q`` headless).
"""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from app.core.models import PlaybackState
from app.ui.video_area import VideoArea
from tests.ui.conftest import destroy_application, pump

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="requires a display with OpenGL (use xvfb-run on headless Linux)",
)


@pytest.fixture
def app(qtbot, qapp, tmp_path):
    """A real application instance per test (audio muted for CI)."""
    from app.application import Application

    application = Application(qapp, mpv_options={"ao": "null"}, settings_path=tmp_path / "settings.json")
    window = application.window
    window.show()
    # Under Xvfb there is no window manager, so Qt never marks the window
    # active — and QShortcut (WindowShortcut context) needs an active window.
    # On real desktops this happens automatically on show().
    window.activateWindow()
    qapp.processEvents()
    yield application
    destroy_application(application, qapp)


def _wait_playing(qapp, app, media) -> None:
    app.controller.open(str(media))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING), (
        f"media never started (state={app.controller.state})"
    )


def _post_wheel(widget, up: bool = True) -> None:
    """Synthesize a wheel event over ``widget`` (pytest-qt has no wheel API)."""
    event = QWheelEvent(
        QPointF(10.0, 10.0),
        QPointF(10.0, 10.0),
        QPoint(0, 0),
        QPoint(0, 120 if up else -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.postEvent(widget, event)


# ------------------------------------------------------------------ shortcuts
def test_space_toggles_playback(app, qtbot, qapp, sample_media):
    _wait_playing(qapp, app, sample_media)
    qtbot.keyClick(app.window, Qt.Key.Key_Space)
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PAUSED)
    qtbot.keyClick(app.window, Qt.Key.Key_Space)
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)


def test_volume_and_mute_shortcuts(app, qtbot):
    app.controller.set_volume(50)
    qtbot.keyClick(app.window, Qt.Key.Key_Up)
    assert app.controller.volume == 55
    qtbot.keyClick(app.window, Qt.Key.Key_Down)
    assert app.controller.volume == 50
    qtbot.keyClick(app.window, Qt.Key.Key_M)
    assert app.controller.muted is True
    qtbot.keyClick(app.window, Qt.Key.Key_M)
    assert app.controller.muted is False


def test_speed_shortcuts_and_button_reflect(app, qtbot):
    app.controller.set_speed(1.5)
    qtbot.keyClick(app.window, Qt.Key.Key_BracketRight)
    assert app.controller.speed == pytest.approx(1.75)
    assert app.window._controls.btn_speed.text() == "1.75×"
    qtbot.keyClick(app.window, Qt.Key.Key_BracketLeft)
    assert app.controller.speed == pytest.approx(1.5)
    qtbot.keyClick(app.window, Qt.Key.Key_Backspace)
    assert app.controller.speed == pytest.approx(1.0)
    assert app.window._controls.btn_speed.text() == "1×"


def test_seek_shortcuts(app, qtbot, qapp, long_sample_media):
    _wait_playing(qapp, app, long_sample_media)
    assert pump(qapp, lambda: (app.controller.position or 0) >= 0.4)
    start = app.controller.position
    qtbot.keyClick(app.window, Qt.Key.Key_Right)
    assert pump(qapp, lambda: (app.controller.position or 0) >= start + 3.0)


# ------------------------------------------------------------------- fullscreen
def test_fullscreen_shortcut_and_escape(app, qtbot):
    qtbot.keyClick(app.window, Qt.Key.Key_F)
    assert app.window.isFullScreen()
    qtbot.keyClick(app.window, Qt.Key.Key_Escape)
    assert not app.window.isFullScreen()


def test_autohide_hides_and_reveals_chrome(app, qtbot):
    window = app.window
    window._autohide.set_interval(150)
    qtbot.keyClick(window, Qt.Key.Key_F)
    assert window.isFullScreen()

    with qtbot.waitSignal(window._autohide.hidden, timeout=3000):
        pass
    assert not window._controls.isVisible()

    with qtbot.waitSignal(window._autohide.shown, timeout=3000):
        window._video_area.userActivity.emit()
    assert window._controls.isVisible()

    with qtbot.waitSignal(window._autohide.hidden, timeout=3000):
        pass
    assert not window._controls.isVisible()

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isFullScreen()
    assert window._controls.isVisible()


# ------------------------------------------------------------------ mouse rules
def test_double_click_fullscreen_without_pause(app, qtbot, qapp, sample_media):
    _wait_playing(qapp, app, sample_media)
    area = app.window._video_area

    qtbot.mouseDClick(area, Qt.MouseButton.LeftButton)
    assert app.window.isFullScreen()
    # The single-click pause must have been cancelled by the double-click.
    qtbot.wait(420)
    assert app.controller.state is PlaybackState.PLAYING

    qtbot.mouseDClick(area, Qt.MouseButton.LeftButton)
    assert not app.window.isFullScreen()


def test_single_click_on_video_area_pauses(app, qtbot, qapp, sample_media):
    _wait_playing(qapp, app, sample_media)
    qtbot.mouseClick(app.window._video_area, Qt.MouseButton.LeftButton)
    qtbot.wait(420)  # single-click delay is 260 ms
    assert app.controller.state is PlaybackState.PAUSED


def test_single_click_on_surface_child_pauses(app, qtbot, qapp, sample_media):
    """Clicks landing on the QOpenGLWidget child go through the event filter."""
    _wait_playing(qapp, app, sample_media)
    qtbot.mouseClick(app.window._surface, Qt.MouseButton.LeftButton)
    qtbot.wait(420)
    assert app.controller.state is PlaybackState.PAUSED


def test_wheel_over_video_area_requests_volume_step(qtbot, qapp):
    area = VideoArea()
    qtbot.addWidget(area)
    area.resize(400, 300)
    with qtbot.waitSignal(area.volumeStepRequested) as blocker:
        _post_wheel(area, up=True)
    assert blocker.args == [5]
    with qtbot.waitSignal(area.volumeStepRequested) as blocker:
        _post_wheel(area, up=False)
    assert blocker.args == [-5]


def test_wheel_over_surface_in_app_steps_volume(app, qtbot, qapp, sample_media):
    _wait_playing(qapp, app, sample_media)
    app.controller.set_volume(50)
    _post_wheel(app.window._surface, up=True)
    assert pump(qapp, lambda: app.controller.volume == 55)


def test_right_click_emits_context_menu_signal(qtbot, qapp):
    area = VideoArea()
    qtbot.addWidget(area)
    area.resize(400, 300)
    with qtbot.waitSignal(area.contextMenuRequested):
        qtbot.mouseClick(area, Qt.MouseButton.RightButton)


def test_context_menu_speed_selection(app, qtbot, qapp):
    """The (modal) context menu itself is exercised manually; the speed
    actions it contains route through the same controller path tested here."""
    app.controller.set_speed(1.25)
    assert app.window._controls.btn_speed.text() == "1.25×"


# ------------------------------------------------------- amplified volume
def test_volume_slider_amplified_range(app, qtbot):
    """v0.12.6: slider 0..200, tooltip tracks amplified state end-to-end."""
    slider = app.window._controls.volume_slider
    assert slider.maximum() == 200

    app.controller.set_volume(150)
    assert slider.value() == 150
    assert "150%" in slider.toolTip()
    assert "amplified" in slider.toolTip()

    slider.setValue(190)  # user drag beyond unity
    assert app.controller.volume == 190

    slider.setValue(80)  # back inside the normal zone
    assert "amplified" not in slider.toolTip()
