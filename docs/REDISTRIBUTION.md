# Redistribution & licensing review — Glint v0.13.0

**This is engineering documentation, not legal advice.** It records the
component inventory and the reasoning used for the Phase 1 promise to review
licensing before packaging. Anyone preparing an official public release
should have the final artefacts reviewed again (see *Warnings*).

## 1. Component inventory

| Component | Role | License | In the shipped artefacts? |
|---|---|---|---|
| Glint source code | the application | **GPL-3.0-or-later** (project choice, Phase 1) | yes (all artefacts) |
| Glint icon set (`app/assets/icons/*.svg`) | UI icons, **original work** made for this project | GPL-3.0-or-later (with the app) | yes |
| PySide6 (Qt 6 for Python) | GUI toolkit | **LGPL-3.0** (Qt dual-licensed; the PySide project distributes under LGPL) | only in frozen/installer builds; a plain `pip install` pulls it from PyPI at the user's behest |
| python-mpv | libmpv Python bindings | **GPL-2.0-or-later** (project also offers it under LGPL-2.1-or-later; either way GPL-3-compatible via the upgrade clause) | yes (dependency) |
| libmpv | playback engine (bundles FFmpeg, libass, etc.) | stock builds are **GPL-2.0-or-later** (mpv *can* be built LGPL-only, but the common prebuilt Windows binaries enable GPL components) | Windows installer / frozen build bundles `libmpv-2.dll`; Linux uses the system library |
| FFmpeg (inside libmpv builds) | demux/decode | LGPL-2.1+ or GPL-2+ **depending on the build flags of the libmpv binary you ship** | inside libmpv |
| libass (inside libmpv builds) | subtitle rendering | ISC | inside libmpv |
| PyInstaller | build tool for the Windows bundle | GPL-2.0 **with special bootloader exception** — bundled apps may carry any license | build-time only, not distributed |
| Inno Setup | Windows installer compiler | Free to use; installer *output* is unencumbered | build-time only, not distributed |

No VLC code, branding, logos or assets are used anywhere (project rule since
Phase 1); the icon set is original; the name "Glint" is our own (renamed from Lumen in v0.13.0 after a name-collision survey).

## 2. Compatibility analysis

* Everything that ends up *inside* the application process is either
  "GPL-2.0-or-later" (python-mpv, stock libmpv) or LGPL (PySide6).
  GPL-2.0-or-later explicitly allows relicensing under GPL-3.0-or-later, so
  the combined work is distributable under **GPL-3.0-or-later** — matching
  the project's own license. No conflict exists.
* PySide6 is LGPL-3.0: LGPL §3 permits use in a combined work under the
  GPL as long as LGPL obligations for the library itself are met (license
  text, source availability, relinkability — see checklist). Glint uses
  PySide6 exclusively as an unmodified, separately-installed / dynamically
  linked dependency, which is the intended LGPL use.
* The `dev` extras (pytest, ruff) never ship to users.

## 3. Distribution modes and their obligations

**A. Source / wheel (`pip install glint-player`)** — we distribute only
GPL-3.0-or-later code (app + icons). Users' pip fetches PySide6 and
python-mpv from PyPI themselves. Obligations: provide our complete
corresponding source (the repository / sdist), the GPL-3.0 text, and
copyright notices. *(Not yet published to PyPI — packaging artefacts are
prepared in Phase 11; publishing is a separate decision.)*

**B. Windows installer / frozen build** — we additionally distribute
PySide6 binaries (LGPL) and `libmpv-2.dll` (GPL-2.0+). Obligations:
1. Include the license texts: GPL-3.0, LGPL-3.0, and GPL-2.0 (for libmpv),
   plus the component notices inside the libmpv build.
2. Offer the corresponding source for the GPL/LGPL components: our source
   (the repository at the exact version) and a written offer / link for
   PySide6/Qt and for the exact libmpv source (mpv's build is reproducible;
   link the exact binary's source revision used).
3. Keep Qt dynamically linked (it is) and state that users may relink /
   replace the libraries (LGPL §4 compliant usage).
4. Name the copyright holders in an "About / Third-party licenses" view or
   accompanying file.

## 4. Warnings (explicit, per the project's licensing rule)

* **Verify the exact libmpv binary before shipping.** Distro builds may be
  LGPL-only; the common prebuilt Windows binaries (e.g. the official mpv
  "libmpv" packages) are GPL-2.0+ and statically fold GPL-enabled FFmpeg.
  The licence of the *specific binary you bundle* decides which texts and
  source offers ship with it. Run `mpv.com --version` (it prints the build
  configuration) and check the accompanying `Copyright`/`LICENSE` file.
* **Do not strip or replace licence files** that ship inside the libmpv or
  PySide6 packages.
* **PyInstaller's bootloader exception** covers apps of any license, but the
  apps *we* bundle are GPL-3.0+ anyway — no issue; just don't mistake the
  tool's license for the product's.
* If a future switch to an **LGPL-only libmpv build** is desired (to relax
  obligations), it must be built with `mpv-build` without GPL components —
  some formats/features may disappear. The backend abstraction keeps this
  option open (Phase 1 decision).
* This document was prepared against the versions listed above; re-verify
  whenever a dependency changes.

## 5. Ship checklist (final release gate — Phase 12)

- [ ] `glint --check` passes on every target platform
- [ ] Licence texts bundled: GPL-3.0, LGPL-3.0, GPL-2.0 + libmpv notices
- [ ] Source offer: repository link/tag for Glint; source links for PySide6
      and the exact libmpv build
- [ ] About dialog / README lists third-party components with licences
- [ ] No VLC assets or trademarks anywhere (automated grep as part of the
      release script)
- [ ] `python -m pip wheel .` builds; wheel smoke-installs and boots
      (done in Phase 11 — repeat for the release build)
