#!/usr/bin/env python3
"""Real-GPU video pixel verification (the Phase 2/7/12 deferred check).

Plays the bundled, vertically asymmetric clip (red top / white band / blue
bottom — dev/assets/orientation-clip.mp4) through the *real* render path
(libmpv render API into a QOpenGLWidget) and captures two frames:

* the engine's own screenshot — proves the DECODE pipeline works;
* the widget's framebuffer — the real verdict: it proves frames reach the
  SCREEN through the GPU.

PASS requires the on-screen frame to be (a) substantially non-black,
(b) more than a couple of distinct colours, and (c) **upright** — red at
the top, blue at the bottom. (c) is the permanent regression gate for the
v0.12.3 field bug (video played upside down on real hardware — invisible
in the sandbox, where software GL reads the framebuffer back black).

No external tools are required — the clip ships with the repository.

Usage (needs a display; do NOT run under Xvfb-with-llvmpipe):

    python dev/verify-video.py [--keep]

    --keep  keep the screenshot artefacts for inspection

Exit code 0 = PASS, 1 = FAIL (also on setup errors, with a message).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CLIP = ROOT / "dev" / "assets" / "orientation-clip.mp4"

if TYPE_CHECKING:  # pragma: no cover — typing only, no GUI import needed
    from PySide6.QtGui import QImage


def analyse_image(path: Path) -> tuple[float, float]:
    """Return (nonblack_fraction, colour_variety) for a PNG.

    colour_variety is the number of distinct coarse colours (4 bits per
    channel) — a rendered frame of the orientation clip has several; a
    black frame has 1.
    """
    from PySide6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"cannot load {path}")
    nonblack = 0
    colours: set[int] = set()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixel(x, y)
            r, g, b = (pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF, pixel & 0xFF
            if r + g + b > 30:  # allow near-black noise
                nonblack += 1
            colours.add(((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4))
    total = image.width() * image.height()
    return nonblack / total, float(len(colours))


def orientation_of(image: QImage) -> str:
    """Classify a frame of the bundled clip.

    Returns ``"upright"`` (red top / blue bottom), ``"flipped"`` (blue top /
    red bottom) or ``"indeterminate"`` (anything else — including black
    frames, which carry no orientation signal).
    """
    if image.isNull():
        return "indeterminate"
    width, height = image.width(), image.height()
    band = max(1, height // 8)

    def dominant(part: QImage) -> tuple[float, float, float] | None:
        r = g = b = n = 0
        for y in range(part.height()):
            for x in range(0, part.width(), 4):
                pixel = part.pixel(x, y)
                r += (pixel >> 16) & 0xFF
                g += (pixel >> 8) & 0xFF
                b += pixel & 0xFF
                n += 1
        if n == 0:
            return None
        return r / n, g / n, b / n

    top_rgb = dominant(image.copy(0, 0, width, band))
    bottom_rgb = dominant(image.copy(0, height - band, width, band))
    if top_rgb is None or bottom_rgb is None:
        return "indeterminate"

    def is_red(c: tuple[float, float, float]) -> bool:
        return c[0] > 140 and c[2] < 100

    def is_blue(c: tuple[float, float, float]) -> bool:
        return c[2] > 140 and c[0] < 100

    if is_red(top_rgb) and is_blue(bottom_rgb):
        return "upright"
    if is_blue(top_rgb) and is_red(bottom_rgb):
        return "flipped"
    return "indeterminate"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep artefacts")
    args = parser.parse_args()

    if not CLIP.is_file():
        print(
            f"verify-video: bundled clip missing: {CLIP} — "
            "extract the full update zip / repository",
            flush=True,
        )
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="glint-verify-video-"))
    shot = workdir / "engine-frame.png"
    fb_path = workdir / "framebuffer.png"

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
        )
        qapp = QApplication([])

        from app.core.models import PlaybackState
        from app.player.mpv_backend import MpvBackend

        class _Listener:
            def on_state_changed(self, state): ...
            def on_media_loaded(self, info): ...
            def on_tracks_changed(self, tracks): ...
            def on_position_changed(self, position): ...
            def on_duration_changed(self, duration): ...
            def on_error(self, error): ...
            def on_log(self, level, component, message): ...
            def on_buffering_changed(self, percent): ...
            def on_stream_title(self, title): ...

        print(f"verify-video: playing {CLIP.name} (bundled orientation clip)", flush=True)
        backend = MpvBackend(listener=_Listener(), options={"ao": "null"})
        surface = backend.create_video_surface()
        surface.resize(640, 360)
        surface.show()
        qapp.processEvents()

        backend.open(str(CLIP))
        deadline = time.time() + 15
        while time.time() < deadline:
            qapp.processEvents()
            if backend.state is PlaybackState.PLAYING:
                break
            time.sleep(0.05)
        time.sleep(1.0)  # let a few frames render
        qapp.processEvents()

        # Two independent captures:
        # (a) the engine's own screenshot — proves the DECODE pipeline works;
        # (b) the widget's framebuffer — proves frames reach the SCREEN.
        # Only (b) is the real verdict: software GL (llvmpipe/Remote Desktop)
        # executes mpv's render API but composites black, which (a) cannot
        # see (mpv screenshots bypass the display path entirely). (b) also
        # carries the orientation signal — (a) always looks source-correct.
        decode_ok = backend.screenshot_to(str(shot))
        d_nonblack = 0.0
        if decode_ok:
            d_nonblack, d_variety = analyse_image(shot)
            print(
                f"verify-video: engine decode frame: {d_nonblack:.1%} non-black, "
                f"{d_variety:.0f} coarse colours",
                flush=True,
            )
        else:
            print("verify-video: engine decode frame: screenshot failed", flush=True)

        frame = surface.grabFramebuffer()  # QOpenGLWidget: the real pixels
        frame.save(str(fb_path))
        nonblack, variety = analyse_image(fb_path)
        orientation = orientation_of(frame)
        print(
            f"verify-video: on-screen framebuffer: {nonblack:.1%} non-black, "
            f"{variety:.0f} coarse colours, orientation: {orientation}",
            flush=True,
        )

        if nonblack >= 0.5 and variety >= 3 and orientation == "upright":
            print(
                "verify-video: PASS — real video frames rendered on screen, "
                "right side up",
                flush=True,
            )
            return 0
        if orientation == "flipped":
            print(
                "verify-video: FAIL — the image is UPSIDE DOWN "
                "(Y-flip regression in the render path)",
                flush=True,
            )
            return 1
        if decode_ok and d_nonblack >= 0.5:
            print(
                "verify-video: FAIL — decode works but the screen shows black: "
                "software GL (llvmpipe / Remote Desktop / missing drivers)",
                flush=True,
            )
        else:
            print("verify-video: FAIL — no usable video frames at all", flush=True)
        return 1
    finally:
        backend = locals().get("backend")
        surface = locals().get("surface")
        if backend is not None:
            try:
                if surface is not None:
                    surface.close()
                    # The render context MUST be freed while a GL context is
                    # current and BEFORE the mpv handle terminates —
                    # otherwise libmpv aborts the process by design.
                    surface.release()
                backend.shutdown()
            except Exception:  # noqa: BLE001, S110 — best-effort cleanup
                pass
        if args.keep:
            print(f"verify-video: artefacts kept in {workdir}", flush=True)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
