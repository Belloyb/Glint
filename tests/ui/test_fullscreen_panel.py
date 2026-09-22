"""GUI tests for fullscreen playlist-panel behaviour (v0.12.5 field fix).

The field bug: entering fullscreen hid the menu bar but left the playlist
dock (right sidebar) visible, so fullscreen was never a video-only view.

Requires a display (``xvfb-run -a python -m pytest tests/ui -q`` headless).
"""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt

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
    window.activateWindow()  # Xvfb has no WM: QShortcut needs an active window
    qapp.processEvents()
    yield application
    from tests.ui.conftest import destroy_application

    destroy_application(application, qapp)


def test_fullscreen_hides_playlist_panel_and_restores(app, qtbot):
    window = app.window
    window._playlist_dock.show()
    qtbot.keyClick(window, Qt.Key.Key_F)
    assert window.isFullScreen()
    assert not window._playlist_dock.isVisible(), "fullscreen must be video-only"

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isFullScreen()
    assert window._playlist_dock.isVisible(), "pre-fullscreen panel state restored"


def test_fullscreen_panel_is_chrome(app, qtbot):
    """In fullscreen the panel shows on request and hides with the chrome."""
    window = app.window
    window._playlist_dock.show()
    qtbot.keyClick(window, Qt.Key.Key_F)
    assert not window._playlist_dock.isVisible()

    window._toggle_playlist_panel()  # what Ctrl+L triggers
    assert window._playlist_dock.isVisible()

    window._on_chrome_hidden()  # idle timeout
    assert not window._playlist_dock.isVisible()

    window._on_chrome_shown()  # user activity
    assert window._playlist_dock.isVisible(), "requested panel returns with chrome"

    window._toggle_playlist_panel()  # hide it again on purpose
    assert not window._playlist_dock.isVisible()
    window._on_chrome_shown()
    assert not window._playlist_dock.isVisible(), "unrequested panel stays hidden"

    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert window._playlist_dock.isVisible(), "pre-fullscreen panel state restored"


def test_panel_closed_before_fullscreen_stays_closed(app, qtbot):
    window = app.window
    window._playlist_dock.hide()
    qtbot.keyClick(window, Qt.Key.Key_F)
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert not window._playlist_dock.isVisible()
