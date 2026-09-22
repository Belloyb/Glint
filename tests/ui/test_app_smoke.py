"""End-to-end GUI smoke test: builds the real application and drives it.

Requires a display with OpenGL. On headless Linux run under Xvfb::

    xvfb-run -a python -m pytest tests/ui -q

Note on video pixels: under software rasterizers (llvmpipe in Xvfb) the libmpv
render API executes (render context, frame scheduling, draw calls) but mpv's
shader output is black — a limitation of that environment, see
docs/PHASE2_NOTES.md. Pixel-level video verification therefore happens on
real GPU hardware; this test verifies everything around it.
"""

from __future__ import annotations

import os

import pytest

from app.core.models import PlaybackState
from tests.ui.conftest import destroy_application, pump

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="requires a display with OpenGL (use xvfb-run on headless Linux)",
)


def test_app_end_to_end(qtbot, qapp, sample_media, tmp_path):
    from app.application import Application

    app = Application(qapp, mpv_options={"ao": "null"}, settings_path=tmp_path / "settings.json")
    window = app.window
    window.show()
    qapp.processEvents()

    try:
        assert window.isVisible()

        # Open + play
        app.controller.open(str(sample_media))
        assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING), (
            f"never started playing (state={app.controller.state})"
        )
        assert pump(qapp, lambda: (app.controller.duration or 0) > 0), "duration never arrived"

        # Video surface must be alive (software GL under Xvfb is fine).
        assert window._surface.has_video_support, "OpenGL render context failed"

        # Seek
        app.controller.seek(2.0)
        assert pump(qapp, lambda: (app.controller.position or 0.0) > 1.4), "seek did not take effect"

        # Pause / resume / stop
        app.controller.pause()
        assert pump(qapp, lambda: app.controller.state is PlaybackState.PAUSED)
        app.controller.play()
        assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
        app.controller.stop()
        assert pump(qapp, lambda: app.controller.state is PlaybackState.STOPPED)

        # Volume / mute plumbing
        app.controller.set_volume(42)
        assert app.controller.volume == 42
        app.controller.toggle_mute()
        assert app.controller.muted is True
        app.controller.toggle_mute()
        assert app.controller.muted is False

        # Error path: a missing file must raise the banner, not crash.
        app.controller.open(str(tmp_path / "does-not-exist.mp4"))
        assert pump(qapp, lambda: app.controller.state is PlaybackState.ERROR)
        assert pump(qapp, lambda: window._error_banner.isVisible()), "error banner did not appear"
    finally:
        destroy_application(app, qapp)
