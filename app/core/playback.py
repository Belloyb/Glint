"""Pure playback helpers (Qt-free, trivially testable)."""

from __future__ import annotations

#: Speed presets offered by the UI (also the stepping grid for [ / ] keys).
#: All values are exact binary fractions, so equality comparisons are safe.
SPEED_PRESETS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)

MIN_SPEED: float = SPEED_PRESETS[0]
MAX_SPEED: float = SPEED_PRESETS[-1]

_EPSILON = 1e-9

#: Volume range: 0 = silence, 100 = unity (no amplification), above 100 =
#: software amplification (VLC-style "200% volume"). The engine applies
#: above-unity values as digital gain — loud material may clip/distort, the
#: same trade-off every player with >100% volume makes.
VOLUME_UNITY: int = 100
VOLUME_MAX: int = 200


def clamp_volume(value: float) -> int:
    """Clamp a volume into the supported 0..200 range (int percent)."""
    return max(0, min(VOLUME_MAX, round(float(value))))


def clamp_speed(value: float) -> float:
    """Clamp a speed into the supported UI range."""
    return min(MAX_SPEED, max(MIN_SPEED, float(value)))


def next_speed(current: float, direction: int) -> float:
    """Return the next speed preset from ``current`` in ``direction``.

    ``direction`` is ``+1`` (faster) or ``-1`` (slower). Values already on a
    preset move to the neighbouring preset; off-preset values snap to the
    nearest preset in the direction of travel. The ends are sticky.
    """
    if direction == 0:
        return clamp_speed(current)
    if direction > 0:
        faster = [preset for preset in SPEED_PRESETS if preset > current + _EPSILON]
        return faster[0] if faster else MAX_SPEED
    slower = [preset for preset in SPEED_PRESETS if preset < current - _EPSILON]
    return slower[-1] if slower else MIN_SPEED
