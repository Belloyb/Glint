"""M3U/M3U8 playlist reading and writing (defensive, Qt-free).

Playlist files are *untrusted input*: lines are length-capped, unknown
directives are ignored, and nothing is ever executed. Relative entries are
resolved against the playlist file's directory. Non-file entries (http://,
rtsp://, …) are kept verbatim — the playback engine decides how to handle
them, and errors surface through the normal player error path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.utils.logging import get_logger

logger = get_logger("core.m3u")

_MAX_LINE_LENGTH = 4096
_MAX_ENTRIES = 100_000
_EXTINF_PREFIX = "#EXTINF:"


@dataclass(frozen=True)
class M3uEntry:
    """One playlist entry as parsed from (or written to) an M3U file."""

    uri: str
    title: str | None = None
    duration: float | None = None


def parse(text: str, base_dir: Path | None = None) -> list[M3uEntry]:
    """Parse M3U/M3U8 text into entries.

    ``base_dir`` resolves relative paths (usually the playlist file's
    directory). Malformed lines never raise — they are skipped.
    """
    entries: list[M3uEntry] = []
    pending_title: str | None = None
    pending_duration: float | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > _MAX_LINE_LENGTH:
            continue
        if line.startswith(_EXTINF_PREFIX):
            payload = line[len(_EXTINF_PREFIX) :]
            duration_text, separator, title = payload.partition(",")
            pending_duration = _parse_duration(duration_text) if separator else None
            pending_title = title.strip() or None
            continue
        if line.startswith("#"):
            continue  # unknown directive or comment
        if len(entries) >= _MAX_ENTRIES:
            logger.warning("m3u entry cap (%d) reached; ignoring the rest", _MAX_ENTRIES)
            break
        entries.append(
            M3uEntry(
                uri=_resolve_uri(line, base_dir),
                title=pending_title,
                duration=pending_duration,
            )
        )
        pending_title = None
        pending_duration = None
    return entries


def load(path: Path) -> list[M3uEntry]:
    """Load and parse a playlist file (UTF-8 with BOM, Latin-1 fallback)."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        logger.info("playlist %s is not valid UTF-8; decoded as Latin-1", path)
    return parse(text, base_dir=path.parent)


def dumps(entries: list[M3uEntry]) -> str:
    """Serialise entries to M3U8 text."""
    lines = ["#EXTM3U"]
    for entry in entries:
        if entry.title is not None or entry.duration is not None:
            duration = int(entry.duration) if entry.duration else -1
            lines.append(f"#EXTINF:{duration},{entry.title or ''}")
        lines.append(entry.uri)
    return "\n".join(lines) + "\n"


def save(path: Path, entries: list[M3uEntry]) -> None:
    """Write entries to ``path`` as UTF-8 M3U8."""
    path.write_text(dumps(entries), encoding="utf-8")


def _parse_duration(text: str) -> float | None:
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _resolve_uri(entry: str, base_dir: Path | None) -> str:
    if "://" in entry:
        return entry
    path = Path(entry)
    if path.is_absolute() or base_dir is None:
        return str(path)
    return os.path.normpath(base_dir / path)
