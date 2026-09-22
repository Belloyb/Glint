"""Display keep-awake tests (v0.12.5): unit + controller integration.

The field bug: the display slept during playback on Windows — video
players must inhibit display/system sleep while PLAYING and release the
inhibition otherwise. The controller drives the inhibition from its
``stateChanged`` signal so the platform call happens on the GUI thread
(``SetThreadExecutionState`` is a per-thread request).
"""

from __future__ import annotations

from app.core.models import PlaybackState
from app.player.controller import PlayerController
from app.player.keep_awake import DisplayKeepAwake


class _NullBackend:
    """Stand-in backend: accepts the listener, does nothing."""

    def __init__(self, listener):
        self.listener = listener

    def shutdown(self) -> None:
        pass


class _FakeKeepAwake:
    """Recording stand-in for the OS-level service.

    Mirrors the real service's contract: duplicate acquire/release calls
    are no-ops (the controller deliberately releases on every non-PLAYING
    state — the service deduplicates).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = False

    def acquire(self) -> None:
        if not self.active:
            self.calls.append("acquire")
            self.active = True

    def release(self) -> None:
        if self.active:
            self.calls.append("release")
            self.active = False


def _controller(keep_awake: _FakeKeepAwake) -> PlayerController:
    return PlayerController(
        backend_factory=lambda listener: _NullBackend(listener),
        keep_awake=keep_awake,
    )


# ------------------------------------------------------------------- unit
def test_keep_awake_is_idempotent():
    service = DisplayKeepAwake()
    assert service.active is False
    service.acquire()
    assert service.active is True
    service.acquire()  # second acquire is a no-op
    assert service.active is True
    service.release()
    assert service.active is False
    service.release()  # releasing while inactive is a no-op
    assert service.active is False


def test_keep_awake_non_windows_reports_success():
    """On non-Windows the request is a logged no-op that still tracks state."""
    import sys

    service = DisplayKeepAwake()
    service.acquire()
    if sys.platform != "win32":
        assert service.active is True
    service.release()
    assert service.active is False


# ------------------------------------------------------ controller contract
def test_playing_acquires_and_other_states_release():
    keep_awake = _FakeKeepAwake()
    controller = _controller(keep_awake)

    for state in (PlaybackState.IDLE, PlaybackState.LOADING, PlaybackState.PAUSED):
        controller.on_state_changed(state)
    assert keep_awake.calls == [], "nothing but PLAYING may acquire"

    controller.on_state_changed(PlaybackState.PLAYING)
    assert keep_awake.calls == ["acquire"]
    assert keep_awake.active is True

    controller.on_state_changed(PlaybackState.PAUSED)
    controller.on_state_changed(PlaybackState.ENDED)
    controller.on_state_changed(PlaybackState.ERROR)
    controller.on_state_changed(PlaybackState.STOPPED)
    controller.on_state_changed(PlaybackState.IDLE)
    assert keep_awake.calls == ["acquire", "release"]
    assert keep_awake.active is False


def test_resume_reacquires():
    keep_awake = _FakeKeepAwake()
    controller = _controller(keep_awake)

    controller.on_state_changed(PlaybackState.PLAYING)
    controller.on_state_changed(PlaybackState.PAUSED)
    controller.on_state_changed(PlaybackState.PLAYING)
    assert keep_awake.calls == ["acquire", "release", "acquire"]


def test_shutdown_releases_even_while_playing():
    keep_awake = _FakeKeepAwake()
    controller = _controller(keep_awake)
    controller.on_state_changed(PlaybackState.PLAYING)
    assert keep_awake.active is True

    controller.shutdown()
    assert keep_awake.active is False
