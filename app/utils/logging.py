"""Application logging: rotating file + console, with URL credential redaction.

All loggers live under the ``glint`` namespace; use :func:`get_logger` from
anywhere instead of configuring handlers at call sites.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER = "glint"

# Matches user:password@ inside URLs, e.g. http://user:pass@host/path
_URL_CREDENTIALS = re.compile(r"(?<=//)[^/@\s:]++:[^/@\s]*+@")


class _RedactingFilter(logging.Filter):
    """Strip URL credentials from messages before they reach a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _URL_CREDENTIALS.sub("***@", record.msg)
        return True


def setup_logging(log_dir: Path, console_level: int = logging.INFO, file_level: int = logging.DEBUG) -> None:
    """Attach rotating-file and console handlers to the ``glint`` logger.

    Safe to call more than once; later calls are no-ops.
    """
    root = logging.getLogger(_LOGGER)
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    redactor = _RedactingFilter()

    file_handler = RotatingFileHandler(
        log_dir / "glint.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redactor)

    root.addHandler(file_handler)
    root.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced child logger, e.g. ``glint.player.mpv``."""
    return logging.getLogger(f"{_LOGGER}.{name}")
