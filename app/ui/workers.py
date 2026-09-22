"""Background workers (folder scanning) run on the global QThreadPool.

QRunnable objects cannot hold Qt signals, so each worker owns a small
QObject "signaller" it emits through. Results are delivered as plain lists
of URI strings; the receiver (main thread) applies them to the queue.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.core.scanner import scan_directory
from app.utils.logging import get_logger

logger = get_logger("ui.workers")


class FolderScanSignals(QObject):
    finished = Signal(list)  # list[str] URIs
    failed = Signal(str)  # human-readable reason


class FolderScanWorker(QRunnable):
    """Scans a directory for media files off the GUI thread."""

    def __init__(self, directory: Path, recursive: bool = False) -> None:
        super().__init__()
        self._directory = Path(directory)
        self._recursive = recursive
        self.signals = FolderScanSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            paths = scan_directory(self._directory, recursive=self._recursive)
        except Exception:
            logger.exception("folder scan crashed for %s", self._directory)
            self.signals.failed.emit(f"Could not scan {self._directory}")
            return
        if not paths:
            self.signals.failed.emit(f"No media files found in {self._directory}")
            return
        logger.debug("scanned %s: %d media files", self._directory, len(paths))
        self.signals.finished.emit([str(path) for path in paths])
