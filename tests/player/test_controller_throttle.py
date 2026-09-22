"""Position-signal throttle tests (Phase 10).

The controller re-emits engine position updates at most ~10 Hz (with large
jumps always passing through) so the UI never pays full engine tick rate.
These tests inject a null backend and drive the listener callbacks directly
— no engine, no display.
"""

from __future__ import annotations

import time

import pytest

from app.player.controller import (
    _POSITION_EMIT_INTERVAL,
    _POSITION_JUMP_THRESHOLD,
    PlayerController,
)


class _NullBackend:
    """Stand-in backend: accepts the listener, does nothing."""

    def __init__(self, listener):
        self.listener = listener

    def shutdown(self) -> None:
        pass


@pytest.fixture
def controller():
    instance = PlayerController(backend_factory=lambda listener: _NullBackend(listener))
    yield instance


def _push(controller, positions):
    for position in positions:
        controller.on_position_changed(position)


def test_rapid_updates_are_throttled(controller):
    received: list[float] = []
    controller.positionChanged.connect(received.append)
    # 100 engine ticks in a few milliseconds (engine pushes ~16/s normally,
    # but bursts happen after seeks or on property-change storms).
    _push(controller, [1.0 + i * 0.01 for i in range(100)])
    assert len(received) <= 3, f"expected <= 3 emissions, got {len(received)}"
    assert received[0] == pytest.approx(1.0)


def test_large_jump_emits_immediately(controller):
    received: list[float] = []
    controller.positionChanged.connect(received.append)
    _push(controller, [5.0 + i * 0.01 for i in range(50)])  # throttled burst
    _push(controller, [5.5 + 50 * 0.01 + _POSITION_JUMP_THRESHOLD])  # seek jump
    # The jump must be the last thing delivered, immediately.
    assert received[-1] >= 6.0


def test_emits_again_after_interval(controller):
    received: list[float] = []
    controller.positionChanged.connect(received.append)
    _push(controller, [2.0])
    assert len(received) == 1
    time.sleep(_POSITION_EMIT_INTERVAL + 0.05)
    _push(controller, [2.01])
    assert len(received) == 2
    assert received[1] == pytest.approx(2.01, abs=1e-6)


def test_throttle_constants_are_sane():
    # ~10 Hz UI updates; jumps above one second break through.
    assert 0.05 <= _POSITION_EMIT_INTERVAL <= 0.2
    assert _POSITION_JUMP_THRESHOLD == pytest.approx(1.0)
