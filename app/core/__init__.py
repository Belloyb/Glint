"""Qt-free core: shared data models.

Everything in ``app.core`` must be importable without PySide6 so that the
core logic stays fast to test and usable from any layer.
"""

from app.core.models import MediaInfo, PlaybackState

__all__ = ["MediaInfo", "PlaybackState"]
