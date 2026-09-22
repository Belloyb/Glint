"""Keep the display awake while video is playing.

Without this, the OS power plan turns the display off mid-playback: the
user sees a black screen while the audio continues. Players must actively
inhibit that while playing and release the inhibition when they pause,
stop or quit — otherwise the machine stops honouring its own power
settings while the app runs.

Windows implementation: ``SetThreadExecutionState`` — the same mechanism
browsers and streaming apps use. ``ES_CONTINUOUS | ES_SYSTEM_REQUIRED |
ES_DISPLAY_REQUIRED`` while playing, plain ``ES_CONTINUOUS`` otherwise.
It is per-thread, needs no privileges, and Windows clears it when the
thread/process exits — there is no way to leave the user's power plan
stuck even if the app crashes. The call happens on the GUI thread (via
the controller's ``stateChanged`` signal), which lives as long as the
app, exactly as the API requires.

Other platforms: a *documented no-op*. Linux needs a D-Bus screensaver
inhibitor (org.freedesktop.ScreenSaver / logind) and macOS an IOKit power
assertion; neither has been validated on real hardware by this project,
and the project rules forbid claiming untested features work.
"""

from __future__ import annotations

import sys

from app.utils.logging import get_logger

logger = get_logger("player.keepawake")

# SetThreadExecutionState flags (winbase.h).
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


class DisplayKeepAwake:
    """Idempotent display/system sleep inhibition tied to playback state.

    The controller calls :meth:`acquire` when playback starts and
    :meth:`release` on every other state (pause, stop, end, error) and at
    shutdown. Double calls in either direction are harmless.
    """

    def __init__(self) -> None:
        self._active = False
        self._unsupported_logged = False

    @property
    def active(self) -> bool:
        """True between a successful :meth:`acquire` and :meth:`release`."""
        return self._active

    def acquire(self) -> None:
        if self._active:
            return
        if self._apply(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED):
            self._active = True
            logger.debug("display keep-awake acquired")

    def release(self) -> None:
        if not self._active:
            return
        if self._apply(_ES_CONTINUOUS):
            self._active = False
            logger.debug("display keep-awake released")

    # ------------------------------------------------------------- internals
    def _apply(self, flags: int) -> bool:
        """Make the platform request; True when it was (or would be) made.

        On non-Windows platforms the request is reported as made so the
        acquire/release state machine stays consistent for tests — but
        nothing actually inhibits the screensaver there (see module doc).
        """
        if sys.platform != "win32":
            if not self._unsupported_logged:
                self._unsupported_logged = True
                logger.debug(
                    "display keep-awake not implemented on %s; "
                    "the OS power plan applies during playback",
                    sys.platform,
                )
            return True
        try:
            # ctypes.windll only exists on Windows — import lazily so this
            # module stays importable (and testable) everywhere.
            import ctypes

            result = ctypes.windll.kernel32.SetThreadExecutionState(
                ctypes.c_uint32(flags)
            )
        except (OSError, AttributeError, ValueError):  # pragma: no cover
            logger.warning(
                "SetThreadExecutionState failed; the display may sleep "
                "during playback (playback itself is unaffected)"
            )
            return False
        return result != 0
