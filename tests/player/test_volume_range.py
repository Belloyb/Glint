"""Controller-level volume range tests (v0.12.6): 0..200, unity at 100.

Uses a null backend — no engine, no display.
"""

from __future__ import annotations

from app.player.controller import PlayerController


class _NullBackend:
    """Stand-in backend with a recording set_volume."""

    def __init__(self, listener):
        self.listener = listener
        self.volume = 100

    def set_volume(self, volume: int) -> None:
        self.volume = volume

    def shutdown(self) -> None:
        pass


def _controller(backend: _NullBackend) -> PlayerController:
    return PlayerController(backend_factory=lambda listener: backend)


def test_amplified_volume_passes_through():
    backend = _NullBackend(None)
    controller = _controller(backend)
    received: list[int] = []
    controller.volumeChanged.connect(received.append)

    controller.set_volume(150)
    assert backend.volume == 150
    assert received == [150]


def test_volume_clamps_at_200_and_0():
    backend = _NullBackend(None)
    controller = _controller(backend)

    controller.set_volume(250)
    assert backend.volume == 200
    controller.set_volume(-5)
    assert backend.volume == 0


def test_unity_volume_is_unchanged():
    backend = _NullBackend(None)
    controller = _controller(backend)

    controller.set_volume(100)
    assert backend.volume == 100  # no-op (already unity), still correct
