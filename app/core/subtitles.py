"""Subtitle-related constants and helpers (Qt-free).

The engine (libmpv + libass) owns parsing and rendering; this module only
carries the presets and format helpers the UI layer needs.

Color format note (verified against libmpv 0.40): mpv accepts ``#RRGGBB``
(opaque) and ``#AARRGGBB`` (alpha *first*) when setting, and property
readback is always ``#AARRGGBB``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Font size presets (engine units; 38 is libmpv's default).
SUBTITLE_SIZE_PRESETS: dict[str, float] = {
    "Small": 30,
    "Normal": 38,
    "Large": 50,
    "Huge": 64,
}
DEFAULT_SUBTITLE_SIZE = 38.0

#: Vertical position presets. Engine semantics (mpv manual): 100 is the
#: original position near the bottom; *higher* values move subtitles further
#: DOWN; range 0-150.
SUBTITLE_POSITION_PRESETS: dict[str, float] = {
    "Higher on screen": 85,
    "Default": 100,
    "Lower on screen": 110,
}
DEFAULT_SUBTITLE_POSITION = 100.0

#: Color presets as ``#RRGGBB``.
SUBTITLE_COLOR_PRESETS: dict[str, str] = {
    "White": "#FFFFFF",
    "Yellow": "#FFFF00",
}

DEFAULT_SUBTITLE_FONT = "sans-serif"

_MIN_SIZE = 5.0
_MAX_SIZE = 200.0
_MIN_POSITION = 0.0
_MAX_POSITION = 150.0

_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


@dataclass(frozen=True)
class SubtitleAppearance:
    """Subtitle rendering options (a partial view of the engine's knobs)."""

    font: str = DEFAULT_SUBTITLE_FONT
    size: float = DEFAULT_SUBTITLE_SIZE
    color: str = "#FFFFFFFF"  # engine readback format (#AARRGGBB)
    position: float = DEFAULT_SUBTITLE_POSITION


def is_valid_color(value: str) -> bool:
    """True for ``#RRGGBB`` or ``#AARRGGBB`` strings."""
    return bool(_COLOR_PATTERN.match(value or ""))


def clamp_size(size: float) -> float:
    return min(_MAX_SIZE, max(_MIN_SIZE, float(size)))


def clamp_position(position: float) -> float:
    return min(_MAX_POSITION, max(_MIN_POSITION, float(position)))


def mpv_color_to_rgb(mpv_color: str) -> str:
    """Convert an engine color readback (``#AARRGGBB``) to ``#RRGGBB``.

    Unknown/invalid input returns white.
    """
    value = (mpv_color or "").lstrip("#")
    if len(value) == 8:
        value = value[2:]  # drop leading alpha
    if len(value) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return "#FFFFFF"
    return f"#{value.upper()}"
