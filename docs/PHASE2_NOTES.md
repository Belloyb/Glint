# Phase 2 — Engineering notes (2026-09-14)

Decisions and pitfalls discovered while building and verifying the minimal
player. Recorded so they are not re-learned the hard way.

## Verified in this environment (Debian 13, libmpv 0.40, python-mpv 1.0.8, PySide6 6.11)

- Full engine contract: open/play/pause/stop/accurate seek/volume/mute,
  state machine incl. ENDED and ERROR paths, corrupt-file classification
  (`tests/player/` — 9 tests, headless, no display needed).
- Full application end-to-end under Xvfb: window, theme, controls, seeking,
  error banner, clean shutdown (`tests/ui/test_app_smoke.py`).
- Clean process exit during/after playback (no aborts) when the render
  context is freed before `mpv.terminate()`.

## Pitfalls found (and fixed)

1. **`QOpenGLWidget` never renders into FBO 0.** It renders into its own
   internal framebuffer. mpv's render target must be
   `defaultFramebufferObject()` — rendering to FBO 0 produces a silently
   black widget (mpv drew, nobody displayed it).

2. **python-mpv requires a real `CFUNCTYPE` for `get_proc_address`.**
   `MpvOpenGLInitParams` rejects a plain bound method
   (`expected CFunctionType instance, got method`). Wrap it:
   `mpv.MpvGlGetProcAddressFn(fn)` — and keep a reference alive for the
   render context's lifetime (mpv may call it lazily).

3. **Terminating mpv with a live render context aborts the process**
   (observed SIGABRT in libmpv). The teardown order must be:
   `closeEvent → surface.release() (render ctx freed, GL current) →
   app shutdown → mpv.terminate()`.

4. **`end-file(reason=stop)` is ambiguous** — it fires both for user stop and
   for "replaced by a new loadfile". A first-open failure also arrives as
   `end-file(reason=error)` *while still in the opening phase*. The backend
   tracks `_opening`/`_stop_requested` intent flags to disambiguate
   (this was a real bug caught by the contract tests).

5. **Event payloads must be extracted inside the callback** —
   `event.as_dict()` reads ctypes memory that is invalidated after the
   callback returns.

## Known limitation: software rasterizers (llvmpipe)

Under Mesa llvmpipe (Xvfb, and real-world cases like Windows' `opengl32sw`
fallback or some RDP sessions), libmpv's render API executes fully — context
creation, `update_cb` scheduling, `render()` draw calls — but the video output
is black. mpv also logs `after creating texture: OpenGL error INVALID_ENUM`,
which on real GPUs is a **benign** known log (mpv issue #15019 — playback is
otherwise normal there). Disabling `opengl_pbo` silences the error but does
not restore pixels on llvmpipe.

Consequences for Lumen:

- The app already degrades gracefully (audio keeps playing; `has_video_support`
  reports the state). A user-facing warning for software-GL systems is a
  Phase 7/12 polish item.
- Video-pixel verification is done on real GPU hardware (primary target:
  Windows). The automated smoke test verifies everything else.

## glX trivia (relevant later)

`glXGetProcAddress` may return a non-NULL stub trampoline for *unknown*
function names — filtering on "address is non-zero" is not a valid
"extension exists" check on X11.
