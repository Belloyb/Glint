#!/usr/bin/env bash
# Restore the development sandbox after a reset (apt + pip packages are not
# part of the workspace snapshot). Not needed on a normal dev machine — see
# README for per-OS native dependency installation.
set -euo pipefail

SUDO=""
if command -v sudo >/dev/null && sudo -n true 2>/dev/null; then SUDO="sudo"; fi

if ! python3 -c "import mpv" 2>/dev/null; then
  $SUDO apt-get update -qq >/dev/null
  $SUDO apt-get install -y -qq libmpv2 xvfb libgl1 libegl1 libglx-mesa0 libegl-mesa0 \
    libxcb-cursor0 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 \
    libxcb-xinerama0 libxcb-xkb1 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 \
    fonts-dejavu-core ffmpeg >/dev/null
fi

python3 -m pip install --quiet PySide6 python-mpv pytest pytest-qt pytest-timeout ruff

python3 - <<'PY'
import mpv, PySide6
print("libmpv/python-mpv OK, PySide6", PySide6.__version__)
PY
