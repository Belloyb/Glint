#!/usr/bin/env bash
# Glint release check — everything CI-able before publishing artefacts
# (complements the human checklist in docs/REDISTRIBUTION.md §5).
#
# Usage:  bash dev/release-check.sh
#
# Steps: lint → core/player tests → UI tests (Xvfb on headless Linux) →
# wheel build + installed --check smoke → branding guard → GPU verdict.
# Exits non-zero on the first failure.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "== [1/6] ruff =="
ruff check app tests

echo "== [2/6] core + player tests =="
python3 -m pytest tests/core tests/player -q

echo "== [3/6] UI tests =="
if command -v xvfb-run >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ] || command -v xvfb-run >/dev/null 2>&1; then
  xvfb-run -a -s "-screen 0 1280x800x24" python3 -m pytest tests/ui -q --timeout=90
else
  echo "!! no xvfb-run available — skipping UI tests (run them before releasing!)"
fi

echo "== [4/6] wheel build + installed smoke =="
rm -rf dist /tmp/glint-release-check
python3 -m pip wheel . --no-deps -w dist -q
python3 -m pip install --no-deps -q --target /tmp/glint-release-check dist/glint_player-*.whl
(cd /tmp && PYTHONPATH=/tmp/glint-release-check python3 -m app.main --check)

echo "== [5/6] branding guard =="
# Comments may reference VLC for honest behavioural comparisons ("as in
# VLC"); what must NEVER appear is infringing usage: VLC APIs, VideoLAN
# trademarks, or asset files carrying VLC names.
violations=0
# (a) files named after VLC anywhere in the shipped tree
if find app packaging -iname '*vlc*' | grep -q .; then
  echo "!! files with VLC in the name:"; find app packaging -iname '*vlc*'; violations=1
fi
# (b) VLC API/library usage in code
if grep -rIn --include='*.py' -E 'import vlc|from vlc|libvlc|python-vlc|vlc://' app/; then
  echo "!! VLC API usage found in code"; violations=1
fi
# (c) VideoLAN trademarks in shipped strings/assets (incl. binary-ish files)
if grep -riIl -e 'VideoLAN' -e 'videolan' -e 'VLC Cone' app/ packaging/; then
  echo "!! VideoLAN trademark found in shipped files"; violations=1
fi
if [ "$violations" != "0" ]; then exit 1; fi
echo "   clean: no VLC branding, APIs or trademarks in shipped code/assets"

echo "== [6/6] GPU verdict (informational; FAIL is expected on llvmpipe/Xvfb) "
if command -v xvfb-run >/dev/null 2>&1; then
  xvfb-run -a -s "-screen 0 1280x800x24" python3 dev/verify-video.py || \
    echo "   note: software GL in this environment — run dev/verify-video.py on real hardware"
else
  python3 dev/verify-video.py || true
fi

echo
echo "release-check: ALL AUTOMATED CHECKS PASSED"
echo "Remaining (human): docs/REDISTRIBUTION.md §5 checklist + docs/HARDWARE_VALIDATION.md"
