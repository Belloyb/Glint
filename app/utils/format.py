"""Small, dependency-free formatting helpers."""

from __future__ import annotations

_SIZE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")
_BITRATE_UNITS = ("bps", "kbps", "Mbps", "Gbps")


def format_time(seconds: float | None) -> str:
    """Format seconds as ``m:ss`` or ``h:mm:ss``; ``--:--`` when unknown."""
    if seconds is None or seconds < 0:
        return "--:--"
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_size(num_bytes: int | None) -> str:
    """Format a byte count with IEC units (``1.5 KiB``); ``—`` when unknown."""
    if num_bytes is None or num_bytes < 0:
        return "—"
    value = float(num_bytes)
    for unit in _SIZE_UNITS:
        if value < 1024 or unit == _SIZE_UNITS[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {_SIZE_UNITS[-1]}"


def format_bitrate(bits_per_second: int | None) -> str:
    """Format a bitrate (``384 kbps``); ``—`` when unknown."""
    if not bits_per_second or bits_per_second < 0:
        return "—"
    value = float(bits_per_second)
    for unit in _BITRATE_UNITS:
        if value < 1000 or unit == _BITRATE_UNITS[-1]:
            if unit == "bps":
                return f"{int(value)} {unit}"
            return f"{value:.2f}".rstrip("0").rstrip(".") + f" {unit}"
        value /= 1000
    return f"{value:.1f} {_BITRATE_UNITS[-1]}"
