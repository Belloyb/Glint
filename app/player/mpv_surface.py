"""Qt video surface: libmpv renders into *our* OpenGL context.

This is the only place where mpv's render API meets Qt. The main window never
imports this module directly — it receives the surface from the controller,
which gets it from the backend (layer rule: the UI is engine-agnostic).

Lifecycle (the classic libmpv+Qt pitfalls, all handled here):

1. ``QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)`` must be set before
   QApplication is created (done in ``app.main``); otherwise toggling
   fullscreen destroys the widget's GL context and the render context dies.
2. ``QOpenGLWidget`` renders into its *own* framebuffer, never FBO 0 — the
   render target must be ``defaultFramebufferObject()``.
3. The render context must be freed *before* the mpv handle terminates and
   while a GL context is current — :meth:`release` does exactly that and is
   called from the main window's ``closeEvent``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import mpv
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from app.utils.logging import get_logger

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = get_logger("player.surface")

_GL_COLOR_BUFFER_BIT = 0x00004000  # OpenGL enum (Qt does not re-export it)

# mpv's render API draws the image with its first row at the TOP of the
# target (the convention of texture-oriented toolkits such as Qt Quick).
# QOpenGLWidget presents its framebuffer with standard OpenGL bottom-left
# origin semantics, so mpv's default orientation arrives upside down — the
# surface must ask mpv to flip. Found on real hardware (field fix,
# v0.12.4): the sandbox's software GL always reads the framebuffer back
# black, so orientation could never be observed there. The bundled-clip
# orientation check in dev/verify-video.py guards this permanently.
_FLIP_Y = True


class MpvVideoSurface(QOpenGLWidget):
    """Renders libmpv video frames via mpv's render API.

    Frames are scheduled by mpv (``update_cb`` on an mpv-internal thread) and
    drawn on the GUI thread inside ``paintGL`` — never the other way round.
    If GL setup fails the surface degrades to a black widget and playback
    continues as audio-only (``has_video_support`` reports this).
    """

    _frame_ready = Signal()

    def __init__(self, mpv_instance: mpv.MPV, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mpv = mpv_instance
        self._render_context: mpv.MpvRenderContext | None = None
        self._gl_failed = False
        self._released = False  # gate for the update callback (see release())
        # Keeps the ctypes wrapper alive for the render context's lifetime
        # (mpv may call it lazily long after creation).
        self._get_proc_address_cb: Any = None
        self._frame_ready.connect(self._do_update, Qt.QueuedConnection)

    # ---------------------------------------------------------------- OpenGL
    def initializeGL(self) -> None:
        if self._render_context is not None:
            return
        try:
            # ctypes requires a genuine CFUNCTYPE instance for the struct
            # field (a plain bound method is rejected).
            self._get_proc_address_cb = mpv.MpvGlGetProcAddressFn(self._get_proc_address)
            self._render_context = mpv.MpvRenderContext(
                self._mpv,
                "opengl",
                opengl_init_params={"get_proc_address": self._get_proc_address_cb},
            )
        except Exception:
            self._gl_failed = True
            logger.exception("could not create mpv render context — video disabled, audio continues")
            return
        self._render_context.update_cb = self._schedule_update
        if self.context() is not None:
            # If the GL context is about to be destroyed, free the render
            # context first — otherwise mpv would render into freed memory.
            self.context().aboutToBeDestroyed.connect(self._on_context_about_to_die)
        logger.debug("mpv render context created")

    def _get_proc_address(self, _ctx: Any, name: bytes) -> int | None:
        """GL loader callback required by mpv's render API (never raises)."""
        try:
            address = self.context().getProcAddress(name)
            return int(address) if address else None
        except Exception:
            logger.exception("getProcAddress failed for %r", name)
            return None

    @Slot()
    def _do_update(self) -> None:
        self.update()

    def _schedule_update(self) -> None:
        # Called from an mpv-internal thread: only ask the GUI thread to repaint.
        # Gated: once teardown begins (or the widget's C++ side is gone) the
        # callback must be a silent no-op — mpv may still invoke it briefly
        # while mpv_render_context_free() is in flight.
        if self._released:
            return
        try:
            self._frame_ready.emit()
        except RuntimeError:
            # Shiboken wrapper already deleted (widget destruction race).
            self._released = True

    def paintGL(self) -> None:
        context = self._render_context
        if context is None or self._gl_failed:
            self._paint_black()
            return
        ratio = self.devicePixelRatioF()
        width = max(1, int(self.width() * ratio))
        height = max(1, int(self.height() * ratio))
        try:
            if context.update():  # MPV_RENDER_UPDATE_FRAME
                context.render(
                    # QOpenGLWidget renders into its own FBO, never FBO 0 —
                    # this is the framebuffer Qt will actually composite.
                    opengl_fbo={
                        "fbo": self.defaultFramebufferObject(),
                        "w": width,
                        "h": height,
                    },
                    flip_y=_FLIP_Y,
                )
        except Exception:
            self._gl_failed = True
            logger.exception("rendering frame failed — video disabled for this session")
            self._paint_black()

    def _paint_black(self) -> None:
        functions = self.context().functions() if self.context() else None
        if functions is not None:
            functions.glClearColor(0.0, 0.0, 0.0, 1.0)
            functions.glClear(_GL_COLOR_BUFFER_BIT)

    def resizeGL(self, width: int, height: int) -> None:
        # The current framebuffer size is passed on every render call.
        return

    # ------------------------------------------------------------- lifecycle
    def release(self) -> None:
        """Free the render context while our GL context is still valid.

        Called by the main window on close, *before* the mpv handle terminates
        (terminating the handle with a live render context aborts the process).

        Threading note: the render API forbids concurrent ``mpv_render_*``
        calls, and ``set_update_callback`` "will raise an update callback
        immediately" (render.h) — so teardown must NOT touch the callback
        registration. The callback is made inert with a flag instead, then
        the context is freed; mpv stops invoking it once free() returns.
        """
        context, self._render_context = self._render_context, None
        self._released = True
        if context is None:
            return
        self.makeCurrent()
        try:
            context.free()
            logger.debug("mpv render context released")
        except Exception:
            logger.exception("error freeing mpv render context")
        finally:
            # Break the ctypes reference cycle surface -> CFUNCTYPE thunk ->
            # bound method -> surface. ctypes objects do not participate in
            # cyclic GC, so without this the whole widget tree (including the
            # GL context) would leak on every window.
            self._get_proc_address_cb = None
            self.doneCurrent()

    def _on_context_about_to_die(self) -> None:
        context, self._render_context = self._render_context, None
        self._released = True
        if context is None:
            return
        try:
            context.free()
            logger.debug("mpv render context freed (GL context loss)")
        except Exception:
            logger.exception("error freeing render context on GL context loss")
        finally:
            # Same ctypes-cycle break as in release() — see the note there.
            self._get_proc_address_cb = None

    @property
    def has_video_support(self) -> bool:
        """``False`` once rendering has failed (audio-only fallback)."""
        return not self._gl_failed
