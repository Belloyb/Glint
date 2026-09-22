"""Recent-files list persisted as JSON in the user config directory.

Qt-free and untrusted-input safe: a corrupt or missing file simply starts
an empty list.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.utils.logging import get_logger

logger = get_logger("core.recents")

_MAX_JSON_BYTES = 1_000_000


class RecentFiles:
    """An ordered (newest first) list of recently played URIs."""

    def __init__(self, path: Path, limit: int = 10) -> None:
        self._path = path
        self._limit = max(1, limit)
        self._uris: list[str] = self._load()

    # ------------------------------------------------------------- queries
    def entries(self) -> tuple[str, ...]:
        return tuple(self._uris)

    def __len__(self) -> int:
        return len(self._uris)

    # ------------------------------------------------------------ mutations
    def add(self, uri: str) -> None:
        """Remember ``uri`` (moved to the front, de-duplicated, capped)."""
        if uri in self._uris:
            self._uris.remove(uri)
        self._uris.insert(0, uri)
        del self._uris[self._limit :]
        self._save()

    def remove(self, uri: str) -> None:
        if uri in self._uris:
            self._uris.remove(uri)
            self._save()

    def clear(self) -> None:
        self._uris = []
        self._save()

    # ---------------------------------------------------------- persistence
    def _load(self) -> list[str]:
        try:
            if not self._path.exists():
                return []
            if self._path.stat().st_size > _MAX_JSON_BYTES:
                raise ValueError("recents file suspiciously large")
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                # ValueError (not TypeError): untrusted-data validation,
                # caught below which falls back to an empty list.
                raise ValueError("recents root must be a list")  # noqa: TRY004
            uris = [item for item in data if isinstance(item, str) and item]
            return uris[: self._limit]
        except (OSError, ValueError, json.JSONDecodeError):
            logger.warning("recents file %s unreadable; starting empty", self._path)
            return []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._uris, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            logger.warning("could not save recents to %s", self._path, exc_info=True)
