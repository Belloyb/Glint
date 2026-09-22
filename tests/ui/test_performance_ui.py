"""Phase 10 performance regression tests: playlist mutation budgets and a
long-session stability soak.

Budgets are deliberately generous (≈10× the measured times on the 2-CPU
sandbox) — they exist to catch order-of-magnitude regressions, not to
benchmark. Requires a display (use xvfb-run on headless Linux).
"""

from __future__ import annotations

import gc
import os
import time

import pytest
from PySide6.QtWidgets import QApplication, QListView

from app.core.models import PlaybackState
from app.player.queue import PlaybackQueue
from app.ui.playlist_model import PlaylistModel
from tests.ui.conftest import destroy_application, pump
from tests.ui.test_queue import FakeController

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="requires a display with OpenGL (use xvfb-run on headless Linux)",
)

_N = 10_000


@pytest.fixture
def view_env(qapp):
    """A real queue + model + attached QListView (the production setup)."""
    queue = PlaybackQueue(FakeController(), seed=1)
    model = PlaylistModel(queue)
    view = QListView()
    view.setModel(model)
    view.setUniformItemSizes(True)
    view.resize(400, 600)
    view.show()
    qapp.processEvents()
    yield queue, model, view
    view.close()


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def test_large_playlist_mutation_budgets(view_env, qapp):
    queue, _model, _view = view_env
    uris = [f"/media/track-{i:05d}.mp3" for i in range(_N)]

    bulk = _timed(lambda: (queue.add(uris), qapp.processEvents()))
    assert bulk < 3.0, f"bulk add of {_N} rows took {bulk:.2f}s"
    assert len(queue.playlist) == _N

    one = _timed(lambda: (queue.add(["/media/extra.mp3"]), qapp.processEvents()))
    assert one < 0.3, f"single add to {_N} rows took {one*1000:.0f}ms"

    moved = _timed(lambda: (queue.move_rows(list(range(50)), _N), qapp.processEvents()))
    assert moved < 0.3, f"block move in {_N} rows took {moved*1000:.0f}ms"

    removed = _timed(lambda: (queue.remove_indices(range(50)), qapp.processEvents()))
    assert removed < 0.3, f"contiguous remove from {_N} rows took {removed*1000:.0f}ms"

    scattered = _timed(lambda: (queue.remove_indices([5, 77, 900]), qapp.processEvents()))
    assert scattered < 0.5, f"scattered remove (reset fallback) took {scattered*1000:.0f}ms"


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


def _count_widgets(qapp: QApplication) -> int:
    gc.collect()
    qapp.processEvents()
    return len(qapp.topLevelWidgets())


def test_long_session_open_cycle_no_widget_growth(app, qapp, sample_media, multi_track_mkv):
    """Play through a batch of open/stop cycles: no widget trees may leak
    (the Phase 7 leak class would show up as monotonically growing
    topLevelWidgets)."""
    media = [sample_media, multi_track_mkv]
    baseline = _count_widgets(qapp)
    for round_index in range(6):
        for item in media:
            app.controller.open(str(item))
            assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
            app.controller.stop()
            assert pump(qapp, lambda: app.controller.state is PlaybackState.STOPPED)
        assert _count_widgets(qapp) <= baseline + 1, f"widgets leaked by round {round_index}"


def test_long_session_playlist_churn_stable_memory(app, qapp):
    """Heavy playlist churn (bulk add / move / remove / clear) must not grow
    Python-side memory unboundedly. tracemalloc sees Python allocations only
    (Qt C++ internals are invisible to it) — the budget is accordingly loose
    and only guards against gross Python-side leaks."""
    import tracemalloc

    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    for round_index in range(5):
        uris = [f"/media/churn-{round_index}-{i:05d}.mp3" for i in range(2000)]
        app.queue.add(uris)
        qapp.processEvents()
        app.queue.move_rows(list(range(40)), 2000)
        qapp.processEvents()
        app.queue.remove_indices(range(400))
        qapp.processEvents()
        app.queue.load([])
        qapp.processEvents()
    gc.collect()
    qapp.processEvents()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    growth = peak - before
    assert growth < 30 * 1024 * 1024, f"playlist churn grew memory by {growth / 1e6:.1f} MB"
