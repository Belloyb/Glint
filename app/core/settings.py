"""Persistent application settings: schema ↔ versioned JSON.

Qt-free and defensive by design: a missing file means first run (defaults, no
warning), a corrupt or hostile file degrades field-by-field to defaults with
warnings — settings must never crash the application. Writes are atomic
(temp file + ``os.replace``) so a crash mid-save can never destroy the file.

Adding a setting: add the field (with default) to the relevant section
dataclass, a validator in :data:`_FIELD_VALIDATORS` if it needs more than a
type check, and UI in the settings dialog. Bump ``SCHEMA_VERSION`` when a
migration becomes necessary (old files carry the version; ``from_dict``
accepts any version >= 1 and fills unknown sections from defaults).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from app.core.playback import clamp_speed
from app.core.subtitles import (
    DEFAULT_SUBTITLE_SIZE,
    clamp_size,
    is_valid_color,
)
from app.utils.logging import get_logger

logger = get_logger("core.settings")

SCHEMA_VERSION = 1

_THEMES = ("dark", "light")
_FONT_SCALES = ("small", "normal", "large")
_MAX_STRING = 200  # cap for free-text settings (fonts, device ids)
_MAX_ABS_DELAY = 3600.0  # seconds


@dataclass
class PlaybackSettings:
    default_volume: int = 100  # 0..200; above 100 = amplified (VLC-style)
    default_speed: float = 1.0
    autoplay_on_open: bool = True


@dataclass
class InterfaceSettings:
    theme: str = "dark"  # dark | light
    show_playlist_at_start: bool = True
    font_scale: str = "normal"  # small | normal | large


@dataclass
class SubtitleSettings:
    font: str = "sans-serif"
    size: float = DEFAULT_SUBTITLE_SIZE
    color: str = "#FFFFFF"  # #RRGGBB
    default_delay: float = 0.0  # seconds, signed
    auto_load_external: bool = True


@dataclass
class AudioSettings:
    output_device: str = "auto"  # engine device id


@dataclass
class VideoSettings:
    hardware_decoding: bool = True
    deinterlace: bool = False


@dataclass
class AppSettings:
    """The whole, versioned settings tree."""

    playback: PlaybackSettings = field(default_factory=PlaybackSettings)
    interface: InterfaceSettings = field(default_factory=InterfaceSettings)
    subtitles: SubtitleSettings = field(default_factory=SubtitleSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    schema_version: int = SCHEMA_VERSION

    # ------------------------------------------------------------- (de)serialisation
    def to_dict(self) -> dict:
        data = asdict(self)
        data["schema_version"] = SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: object) -> AppSettings:
        """Build settings from untrusted parsed JSON data, field-validated."""
        if not isinstance(data, dict):
            logger.warning("settings root is not an object; using defaults")
            return cls()
        version = data.get("schema_version", 0)
        if not isinstance(version, int) or version < 1 or version > SCHEMA_VERSION:
            logger.warning("settings schema_version %r unknown; using defaults", version)
            return cls()
        return cls(
            playback=_section(PlaybackSettings, data.get("playback")),
            interface=_section(InterfaceSettings, data.get("interface")),
            subtitles=_section(SubtitleSettings, data.get("subtitles")),
            audio=_section(AudioSettings, data.get("audio")),
            video=_section(VideoSettings, data.get("video")),
        )


# ------------------------------------------------------------- validation
def _section(section_type, data: object):
    """Validate one section dict against its dataclass, field by field."""
    if data is None:
        return section_type()
    if not isinstance(data, dict):
        logger.warning("settings section %s malformed; using defaults", section_type.__name__)
        return section_type()
    values = {}
    for spec in fields(section_type):
        name = spec.name
        if name not in data:
            values[name] = spec.default  # missing key → field default
            continue
        validator = _FIELD_VALIDATORS.get((section_type, name), _default_validator(spec.type))
        values[name] = validator(data[name], name)
    return section_type(**values)


def _clean_bool(value, name):
    if isinstance(value, bool):
        return value
    logger.warning("settings field %s: expected bool, got %r", name, value)
    return False


def _clean_int_in_range(lo: int, hi: int):
    def clean(value, name):
        if isinstance(value, bool) or not isinstance(value, int):
            logger.warning("settings field %s: expected int, got %r", name, value)
            value = 0
        return max(lo, min(hi, value))

    return clean


def _clean_speed(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        logger.warning("settings field %s: expected number, got %r", name, value)
        return 1.0
    return clamp_speed(float(value))


def _clean_size(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        logger.warning("settings field %s: expected number, got %r", name, value)
        return DEFAULT_SUBTITLE_SIZE
    return clamp_size(float(value))


def _clean_delay(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        logger.warning("settings field %s: expected number, got %r", name, value)
        return 0.0
    return max(-_MAX_ABS_DELAY, min(_MAX_ABS_DELAY, float(value)))


def _clean_choice(allowed: tuple[str, ...], fallback: str):
    def clean(value, name):
        if isinstance(value, str) and value in allowed:
            return value
        logger.warning("settings field %s: expected one of %s, got %r", name, allowed, value)
        return fallback

    return clean


def _clean_text(fallback: str):
    def clean(value, name):
        if isinstance(value, str) and value.strip() and len(value) <= _MAX_STRING:
            return value.strip()
        logger.warning("settings field %s: invalid text %r", name, value)
        return fallback

    return clean


def _clean_color(value, name):
    if isinstance(value, str) and is_valid_color(value):
        return value.upper()
    logger.warning("settings field %s: invalid color %r", name, value)
    return "#FFFFFF"


#: (section, field) → validator(untrusted_value, field_name) → clean value
_FIELD_VALIDATORS = {
    (PlaybackSettings, "default_volume"): _clean_int_in_range(0, 200),
    (PlaybackSettings, "default_speed"): _clean_speed,
    (PlaybackSettings, "autoplay_on_open"): _clean_bool,
    (InterfaceSettings, "theme"): _clean_choice(_THEMES, "dark"),
    (InterfaceSettings, "show_playlist_at_start"): _clean_bool,
    (InterfaceSettings, "font_scale"): _clean_choice(_FONT_SCALES, "normal"),
    (SubtitleSettings, "font"): _clean_text("sans-serif"),
    (SubtitleSettings, "size"): _clean_size,
    (SubtitleSettings, "color"): _clean_color,
    (SubtitleSettings, "default_delay"): _clean_delay,
    (SubtitleSettings, "auto_load_external"): _clean_bool,
    (AudioSettings, "output_device"): _clean_text("auto"),
    (VideoSettings, "hardware_decoding"): _clean_bool,
    (VideoSettings, "deinterlace"): _clean_bool,
}


def _default_validator(type_hint):
    """Fallback for fields without an explicit validator (bool today)."""
    return _clean_bool if "bool" in str(type_hint) else _clean_text("")


class SettingsStore:
    """Loads and atomically saves the settings file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppSettings:
        """Read settings; missing file is a normal first run (no warning)."""
        try:
            if not self._path.exists():
                return AppSettings()
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("settings file %s unreadable (%s); using defaults", self._path, exc)
            return AppSettings()
        return AppSettings.from_dict(data)

    def save(self, settings: AppSettings) -> None:
        """Persist settings atomically (temp file + replace)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".json.tmp")
        payload = json.dumps(settings.to_dict(), indent=2, ensure_ascii=False)
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, self._path)
        finally:
            if temp_path.exists():  # replace failed → remove the leftover
                try:
                    temp_path.unlink()
                except OSError:
                    logger.warning("could not remove temporary settings file %s", temp_path)
