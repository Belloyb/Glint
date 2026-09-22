"""Fixtures for headless backend contract tests (no Qt, no display)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from app.core.models import MediaInfo, PlaybackState
from app.player.backend import PlayerError
from app.player.mpv_backend import MpvBackend


class RecordingListener:
    """Thread-safe listener that records backend events for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self._lock = threading.Lock()

    def _record(self, kind: str, payload: Any) -> None:
        with self._lock:
            self.events.append((kind, payload))

    def on_state_changed(self, state: PlaybackState) -> None:
        self._record("state", state)

    def on_media_loaded(self, info: MediaInfo) -> None:
        self._record("loaded", info)

    def on_tracks_changed(self, tracks: list) -> None:
        self._record("tracks", tracks)

    def on_position_changed(self, position: float) -> None:
        self._record("position", position)

    def on_duration_changed(self, duration: float) -> None:
        self._record("duration", duration)

    def on_error(self, error: PlayerError) -> None:
        self._record("error", error)

    def on_log(self, level: str, component: str, message: str) -> None:
        pass  # not asserted in contract tests

    def on_buffering_changed(self, percent: int | None) -> None:
        self._record("buffering", percent)

    def on_stream_title(self, title: str) -> None:
        self._record("stream_title", title)

    def wait_for(self, kind: str, timeout: float = 10.0, predicate: Any = None) -> Any | None:
        """Block until an event of ``kind`` (matching ``predicate``) was seen."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                matches = [p for k, p in self.events if k == kind and (predicate is None or predicate(p))]
            if matches:
                return matches[0]
            time.sleep(0.02)
        return None


class BackendHarness:
    """A backend wired to a recording listener."""

    def __init__(self) -> None:
        self.listener = RecordingListener()
        self.backend = MpvBackend(
            listener=self.listener,
            # vo/ao null: playable without any display or audio device.
            options={"vo": "null", "ao": "null"},
        )

    def wait_for(self, *args: Any, **kwargs: Any) -> Any | None:
        return self.listener.wait_for(*args, **kwargs)

    def shutdown(self) -> None:
        self.backend.shutdown()


@pytest.fixture
def harness() -> BackendHarness:
    fixture = BackendHarness()
    yield fixture
    fixture.shutdown()
