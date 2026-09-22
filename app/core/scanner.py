"""Media file discovery (Qt-free, thread-safe: pure functions).

Used from GUI-worker threads to enumerate candidate media files. Extension
matching is only a *discovery filter* — actual playability is decided by the
playback engine, never by us (spec §7).
"""

from __future__ import annotations

import os
from pathlib import Path

from app.utils.logging import get_logger

logger = get_logger("core.scanner")

#: Common media containers/codecs worth discovering. Deliberately broad;
#: the engine makes the final call on what plays.
MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".3gp", ".aac", ".aiff", ".avi", ".flac", ".flv", ".m2ts", ".m4a",
        ".m4v", ".mkv", ".mov", ".mp3", ".mp4", ".mpeg", ".mpg", ".oga",
        ".ogg", ".ogv", ".opus", ".ts", ".wav", ".webm", ".wma", ".wmv",
    }
)

_MAX_ENTRIES = 50_000


def is_media_file(path: Path) -> bool:
    """Extension-based discovery check (not a playability claim)."""
    return path.suffix.lower() in MEDIA_EXTENSIONS


def scan_directory(
    directory: Path, recursive: bool = False, max_entries: int = _MAX_ENTRIES
) -> list[Path]:
    """Find media files under ``directory`` (sorted by relative path).

    Unreadable directories are logged and skipped; a missing/unreadable root
    yields an empty list rather than an exception (the UI decides whether
    that deserves a message).
    """
    directory = Path(directory)
    results: list[Path] = []
    try:
        if recursive:
            for root, dirs, files in os.walk(directory, onerror=_log_walk_error):
                dirs.sort()
                for name in sorted(files):
                    path = Path(root) / name
                    if is_media_file(path):
                        results.append(path)
                        if len(results) >= max_entries:
                            logger.warning("scan cap (%d) reached in %s", max_entries, directory)
                            return _sorted(directory, results)
        else:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    path = Path(entry.path)
                    if entry.is_file() and is_media_file(path):
                        results.append(path)
                        if len(results) >= max_entries:
                            break
    except OSError as exc:
        logger.warning("could not scan %s: %s", directory, exc)
        return []
    return _sorted(directory, results)


def _sorted(directory: Path, results: list[Path]) -> list[Path]:
    return sorted(results, key=lambda p: p.relative_to(directory).as_posix().lower())


def _log_walk_error(error: OSError) -> None:
    logger.warning("skipping unreadable directory: %s", error)
