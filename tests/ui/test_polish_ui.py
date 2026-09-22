"""Phase 12 polish tests: About dialog, software-GL notice, pretty names.

Requires a display (use xvfb-run on headless Linux).
"""

from __future__ import annotations

import os

import pytest

from app import __version__
from app.ui.dialogs import AboutDialog
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


def test_about_dialog_content(qtbot, qapp):
    dialog = AboutDialog()
    qtbot.addWidget(dialog)
    from PySide6.QtWidgets import QLabel

    labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert __version__ in labels
    assert "GPL-3.0-or-later" in labels
    assert "PySide6" in labels and "libmpv" in labels and "python-mpv" in labels
    assert "open-source" in labels


def test_about_dialog_from_help_menu(app, qapp, qtbot):

    app.window._show_about()
    qapp.processEvents()
    dialog = app.window._about_dialog
    assert dialog is not None and dialog.isVisible()
    # Non-modal: playback state untouched, dialog stays until closed.
    dialog.close()


def _dismiss_notice(notice, qapp) -> None:
    from PySide6.QtWidgets import QPushButton

    notice.findChildren(QPushButton)[0].click()
    qapp.processEvents()


def test_software_renderer_notice_flow(app, qapp, qtbot):
    """The engine's software-renderer log line surfaces a dismissible notice,
    exactly once per session."""
    notice = app.window._video_area._renderer_notice
    # Under llvmpipe (this CI) the *real* engine already triggered the notice
    # during Application construction — the feature working as designed.
    # Dismiss it for a clean slate.
    if notice.isVisibleTo(app.window._video_area):
        _dismiss_notice(notice, qapp)
    assert not notice.isVisibleTo(app.window._video_area)

    # Handler wiring: the controller signal shows the notice.
    app.window._on_software_renderer()
    qapp.processEvents()
    assert notice.isVisibleTo(app.window._video_area)

    # Dismiss hides it; a re-emit of the handler can show it again, but the
    # controller guarantees the signal itself fires only once per session.
    _dismiss_notice(notice, qapp)
    assert not notice.isVisibleTo(app.window._video_area)


def test_software_renderer_signal_fires_once_per_session(app, qapp):
    from app.player.controller import PlayerController

    class _NullBackend:
        def __init__(self, listener):  # duck-typed BackendListener
            self.listener = listener

        def shutdown(self) -> None:
            pass

    fresh = PlayerController(backend_factory=lambda listener: _NullBackend(listener))
    fired = []
    fresh.softwareRenderingDetected.connect(lambda: fired.append(1))
    fresh.on_log("warn", "libmpv_render", "Suspected software renderer or indirect context.")
    fresh.on_log("warn", "libmpv_render", "Suspected software renderer AGAIN")
    fresh.on_log("warn", "ffmpeg", "unrelated message")
    assert len(fired) == 1
    fresh.shutdown()


def test_info_dialog_shows_pretty_container(app, qapp, sample_media):
    from app.core.models import PlaybackState

    app.controller.open(str(sample_media))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    app.window._show_media_info()
    qapp.processEvents()
    from PySide6.QtWidgets import QLabel

    labels = " | ".join(label.text() for label in app.window._info_dialog.findChildren(QLabel))
    # The mp4 fixture's raw name is the FFmpeg probe list; it must be shown
    # prettified, not raw.
    assert "mov,mp4" not in labels
    assert "MP4" in labels
