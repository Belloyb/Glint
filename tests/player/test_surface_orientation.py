"""Regression tests for the v0.12.3 Windows field bug: upside-down video.

The sandbox could never observe video orientation (software GL reads the
framebuffer back black), so this file pins both halves of the fix:

* the surface must request mpv's Y-flip for QOpenGLWidget presentation;
* dev/verify-video.py must be able to tell an upright frame from a
  flipped one — it is the permanent orientation gate on real hardware.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PySide6.QtGui import QColor, QImage

ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "dev" / "assets" / "orientation-clip.mp4"


def _load_verify_video():
    spec = importlib.util.spec_from_file_location(
        "glint_verify_video", ROOT / "dev" / "verify-video.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _banded_image(top: str, bottom: str) -> QImage:
    image = QImage(160, 90, QImage.Format.Format_RGB32)
    image.fill(QColor(top))
    bottom_rgb = QColor(bottom).rgb()
    for y in range(45, 90):
        for x in range(160):
            image.setPixel(x, y, bottom_rgb)
    return image


def test_surface_requests_y_flip_for_qopenglwidget():
    # The v0.12.3 bug: flip_y=False rendered video upside down on real
    # hardware. mpv draws with its first row at the TOP of the target;
    # QOpenGLWidget presents with bottom-left-origin GL conventions.
    from app.player.mpv_surface import _FLIP_Y

    assert _FLIP_Y is True


def test_orientation_detects_upright_and_flipped():
    verify = _load_verify_video()
    assert verify.orientation_of(_banded_image("#ff0000", "#0000ff")) == "upright"
    assert verify.orientation_of(_banded_image("#0000ff", "#ff0000")) == "flipped"


def test_orientation_indeterminate_without_signal():
    verify = _load_verify_video()
    black = QImage(160, 90, QImage.Format.Format_RGB32)
    black.fill(0)
    assert verify.orientation_of(black) == "indeterminate"
    assert verify.orientation_of(QImage()) == "indeterminate"  # null image


def test_bundled_orientation_clip_present():
    assert CLIP.is_file(), "dev/assets/orientation-clip.mp4 must ship with the repo"
    # A real encoded clip, not a stub (solid-colour H.264 compresses to KBs).
    assert CLIP.stat().st_size > 1_000
