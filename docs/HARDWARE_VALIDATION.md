# Hardware validation guide (Phase 12)

Everything in this document requires hardware this project did not have
during development (the sandbox renders through llvmpipe software GL and
cannot run Windows). Each section is a concrete, repeatable procedure with
expected results — nothing here is guesswork left to the runner.

> **Rename note (v0.13.0):** the project was renamed Lumen → Glint.
> Quoted field outputs below predate the rename and say "Lumen" — they are
> historical records and deliberately unchanged. Runbook commands are
> updated to the Glint names.

## 1. Real-GPU video pixel verification (Linux/Windows, any vendor)

> **STATUS: COMPLETED — 2026-09-21, real Windows machine, real GPU.**
> Field output: engine decode frame 100.0% non-black; on-screen framebuffer
> 100.0% non-black, 9 coarse colours, orientation upright; **PASS** (v0.12.4,
> which also fixed the upside-down orientation this very run exposed).
> Manual playback confirmed by the operator: "the video is playing fine".

The deferred "pixels are actually on screen" check since Phase 2.

```bash
# on the target machine, with real GPU drivers loaded (NOT under Xvfb):
python dev/verify-video.py
```

No external tools are needed — the script plays a bundled, vertically
asymmetric clip (red top / white band / blue bottom,
`dev/assets/orientation-clip.mp4`). Expected on healthy hardware:

```
verify-video: playing orientation-clip.mp4 (bundled orientation clip)
verify-video: engine decode frame: ~100% non-black, a few coarse colours
verify-video: on-screen framebuffer: ≥ 50% non-black, ≥ 3 coarse colours, orientation: upright
verify-video: PASS — real video frames rendered on screen, right side up   (exit 0)
```

The `orientation` line is the permanent regression gate for the v0.12.3
field bug (video played upside down on real hardware — QOpenGLWidget needs
mpv's `flip_y`; the sandbox could never see it, as software GL reads the
framebuffer back black).

The tool is verified in both directions: its negative path runs in CI
(llvmpipe produces exactly the documented FAIL: decode 100% non-black,
framebuffer 0% non-black, orientation indeterminate, exit 1 — see
PHASE12_NOTES), and unit tests pin the flip request and the orientation
detector. A FAIL on real hardware means drivers/OpenGL setup, not Lumen:
check `lspci -k | grep -A3 VGA`, `glxinfo | grep renderer` (must not say
`llvmpipe`), and that the machine is not in a Remote-Desktop session.

Then a 3-minute manual pass: play a real 1080p H.264 file — seek, pause,
frame-step (`,` / `.`), fullscreen (`F`), track switch (Audio/Video menus),
subtitles on/off, screenshot (`S`) — no stutter, no black frames, correct
colours.

## 2. Windows packaging validation

> **STATUS: COMPLETED — 2026-09-22, real Windows 10/11 x64 machine.**
> PyInstaller bundle built (`pyinstaller packaging\glint.spec`), frozen
> `Lumen.exe --check` PASS (engine + icons + config), frozen player runs.
> Installer compiled with Inno Setup 6.7.3 (`iscc packaging\windows-installer.iss`)
> and passed the full checklist: install (GPL-3.0 licence page, per-user,
> no UAC), launch + playback + fullscreen + playlist panel + 200% volume,
> UI icons visible, no Vulkan warning, uninstall preserves %APPDATA%\lumen,
> reinstall OK. Executing the never-run recipes caught 7 real defects
> along the way (recorded in PHASE12_NOTES): spec path resolution,
> SPECPATH off-by-one, frozen assets not read from _MEIPASS, console
> closefd ValueError, missing DefaultDirName/DefaultGroupName, an
> uncallable association macro, and the PrivilegesRequired=admin default.

Run on Windows 10/11 x64:

1. `git clone` the repository; `pip install -e ".[dev]" pyinstaller`.
2. Follow `packaging/README.md` steps 1–5 exactly (libmpv-2.dll from the
   official mpv-for-Windows libmpv archive; note the binary's exact version
   for the licence review).
3. `dist\Glint\Glint.exe --check` must print `preflight: PASS`
   (engine/assets/config rows all `ok`).
4. `python dev\verify-video.py` on that machine (Direct3D/OpenGL path) —
   expect PASS per §1.
5. Install `dist\installer\GlintSetup-<version>.exe` on a clean user
   profile: launch from the Start menu, run the §1 manual pass, verify the
   optional file-association task, then uninstall — `%APPDATA%\lumen`
   (settings/logs/recents) must survive while the program folder is gone.
6. Known-focus areas for the first Windows run: the PyInstaller spec's
   hidden imports (Qt plugins are auto-detected; a missing one usually
   shows as a blank window — re-run with `--debug all`), the console-less
   log location (`%APPDATA%\lumen\logs`), and high-DPI rendering.

## 3. macOS validation (needs real hardware)

1. `brew install mpv` (provides the dylib), `pip install .` into a venv.
2. `lumen --check` — the engine row must load `libmpv.dylib`.
3. `python dev/verify-video.py` (Metal/GL layer) — expect PASS.
4. Manual pass as in §1 plus: Retina scaling, Cmd key mappings (the
   shortcut manager remaps Ctrl→Cmd automatically), fullscreen-space
   behaviour.

## 4. What to do when something fails

* File the output (`--check` report, `dev/verify-video.py` lines, log file
  from `<config>/lumen/logs/lumen.log`) alongside the hardware/driver info.
* A `--check` engine failure is a library-resolution issue (see README
  troubleshooting table), not a code defect.
* A verify-video FAIL with healthy `glxinfo` is a genuine bug — open it
  with the exact reproduction; the dual capture (decode vs framebuffer)
  already narrows the faulty stage.
