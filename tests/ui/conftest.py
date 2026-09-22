"""Shared GUI test fixtures and helpers.

Setting the GL sharing attribute at import time (before any QApplication
exists) — deterministically early, before pytest-qt creates the app.
"""

from __future__ import annotations

import gc
import shutil
import subprocess
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from tests.conftest import make_wav

# Must happen before the first QApplication is constructed (see
# app/player/mpv_surface.py — keeps the mpv render context alive across
# window-state changes like fullscreen).
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)


def pump(qapp: QApplication, predicate, timeout: float = 10.0) -> bool:
    """Process events until ``predicate()`` is true (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def destroy_application(application, qapp: QApplication) -> None:
    """Tear down an Application deterministically.

    A bare ``window.close()`` only *hides* the window: the widget tree (and
    with it the ``QOpenGLWidget`` and its llvmpipe GL context) survives until
    deferred deletion happens to run. Across a full UI suite dozens of hidden
    GL contexts accumulate inside the Xvfb/llvmpipe driver, until creating or
    using a fresh context blocks forever (observed as an order-dependent full-
    suite hang that never even reaches Python code). Deleting the window and
    flushing both the Python and Qt deferred-deletion queues keeps every test
    starting from a clean slate.
    """
    window = application.window
    window.close()
    application.shutdown()
    window.deleteLater()
    # ``processEvents()`` does not flush DeferredDelete events that were
    # posted outside a running event loop — sendPostedEvents() does, and it
    # is the only deterministic way to destroy the widget tree (and its GL
    # context) here. Python-side reference cycles (e.g. menu lambdas that
    # capture the window) additionally need the cyclic GC — flush both.
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@pytest.fixture(autouse=True)
def _isolated_config_dir(monkeypatch, tmp_path):
    """One config directory per UI test (recents etc.).

    ``tests/conftest.py`` isolates the whole run from the developer's real
    config; this narrows it further so no state (e.g. recents.json) leaks
    between tests — the same hermeticity the settings file already has via
    per-test ``settings_path`` arguments. ``config_dir()`` reads the
    environment lazily, so a per-test override is sufficient.
    """
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("GLINT_CONFIG_DIR", str(config))
    yield config


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """The single shared application instance for UI tests."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session")
def sample_media(tmp_path_factory: pytest.TempPathFactory):
    """A real video (mp4) when ffmpeg is available, else a tone WAV."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        path = tmp_path_factory.mktemp("media") / "clip.mp4"
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=4",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest",
                str(path),
            ],
            check=True,
            timeout=60,
        )
        return path
    return make_wav(tmp_path_factory.mktemp("media") / "tone.wav")


@pytest.fixture(scope="session")
def long_sample_media(tmp_path_factory: pytest.TempPathFactory):
    """A 10-second clip for seek tests: a +5 s seek from any early position
    must stay well inside the file even when box load delays the test loop
    (with the 4 s shared clip the seek could race into EOF)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate a test video")
    path = tmp_path_factory.mktemp("media") / "long-clip.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=8:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
            "-c:v", "mpeg4", "-q:v", "6", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    return path
