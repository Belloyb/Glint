"""Icon loading for the original Glint icon set (SVG, in ``assets/icons``)."""

from __future__ import annotations

from PySide6.QtGui import QIcon

from app.utils.logging import get_logger
from app.utils.paths import icon_path

logger = get_logger("ui.icons")


def load_icon(name: str) -> QIcon:
    """Load ``assets/icons/<name>.svg``; returns a null icon if missing."""
    path = icon_path(name)
    if not path.exists():
        logger.warning("missing icon: %s", path)
        return QIcon()
    return QIcon(str(path))
