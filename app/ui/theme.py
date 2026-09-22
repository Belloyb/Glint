"""Visual identity: design tokens + application stylesheet.

Every color and metric lives here so the look stays consistent; a light theme
can be added later by providing another :class:`Tokens` set and rebuilding the
stylesheet (Phase 7). The stylesheet uses :class:`string.Template` so QSS
braces stay literal.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from string import Template

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Tokens:
    """Design tokens for one theme."""

    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_dim: str
    accent: str
    accent_hover: str
    danger: str
    danger_bg: str
    warning: str
    warning_bg: str


DARK = Tokens(
    bg="#0f1115",
    surface="#161a21",
    surface_alt="#232a35",
    border="#2a303c",
    text="#e8eaf0",
    text_dim="#9aa3b2",
    accent="#f0a832",
    accent_hover="#ffc04d",
    danger="#ff6b6e",
    danger_bg="#3a1f22",
    warning="#f0c46a",
    warning_bg="#2b2416",
)

LIGHT = Tokens(
    bg="#f5f6f8",
    surface="#ffffff",
    surface_alt="#e6e9ef",
    border="#d3d7e0",
    text="#1c2027",
    text_dim="#5b6472",
    accent="#b97a10",  # darkened amber for contrast on light surfaces
    accent_hover="#8f5e08",
    danger="#c0392b",
    danger_bg="#fbeae8",
    warning="#8a6100",
    warning_bg="#fdf3d8",
)

#: theme name → tokens ("light" is a Phase 7 setting; more can follow)
THEMES: dict[str, Tokens] = {"dark": DARK, "light": LIGHT}

FONT_STACK = ["Segoe UI", "Ubuntu", "Noto Sans", "Cantarell", "Sans-serif"]

#: interface font scale name → point size
FONT_SCALES: dict[str, int] = {"small": 9, "normal": 10, "large": 12}


def apply_theme(app: QApplication, theme: str = "dark", font_scale: str = "normal") -> None:
    """Install a named theme (and font scale) on the application."""
    tokens = THEMES.get(theme, DARK)
    font = QFont()
    font.setFamilies(FONT_STACK)
    font.setPointSize(FONT_SCALES.get(font_scale, 10))
    app.setFont(font)
    app.setStyleSheet(build_stylesheet(tokens))


def build_stylesheet(tokens: Tokens) -> str:
    """Build the QSS for a token set."""
    return _QSS.substitute(**dataclasses.asdict(tokens))


_QSS = Template("""
QMainWindow { background: $bg; }

QWidget#CentralArea { background: $bg; }
QWidget#VideoArea { background: #000000; }
QWidget#ControlBar { background: $surface; border-top: 1px solid $border; }

QLabel#IdleTitle { color: $text; font-size: 22px; font-weight: 600; }
QLabel#IdleHint  { color: $text_dim; font-size: 13px; }
QLabel#TimeLabel { color: $text_dim; font-size: 12px; font-weight: 600; }

QLabel#ErrorBanner {
    background: $danger_bg;
    color: $danger;
    border: 1px solid $danger;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
}

QWidget#RendererNotice {
    background: $warning_bg;
    color: $warning;
    border: 1px solid $warning;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}
QWidget#RendererNotice QPushButton { background: transparent; border: none; color: $warning; font-weight: 700; }

QPushButton#IconButton { background: transparent; border: none; border-radius: 6px; }
QPushButton#IconButton:hover { background: $surface_alt; }
QPushButton#IconButton:pressed { background: $border; }

QPushButton#SpeedButton {
    color: $accent;
    background: transparent;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#SpeedButton:hover { border-color: $accent; color: $accent_hover; }
QPushButton#SpeedButton:pressed { background: $surface_alt; }
QPushButton#SpeedButton::menu-indicator { image: none; width: 0; height: 0; }

QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: $border; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal {
    background: $text; width: 12px; height: 12px;
    margin: -5px 0; border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: $accent_hover; }

QMenuBar { background: $bg; color: $text_dim; }
QMenuBar::item:selected { background: $surface_alt; color: $text; }
QMenu { background: $surface; color: $text; border: 1px solid $border; }
QMenu::item { padding: 6px 26px 6px 14px; }
QMenu::item:selected { background: $surface_alt; }
QMenu::item:disabled { color: $text_dim; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
QMenu::indicator {
    width: 12px; height: 12px; border-radius: 6px; margin-left: 6px;
}
QMenu::indicator:unchecked { background: $border; }
QMenu::indicator:checked { background: $accent; }
QMenu::indicator:exclusive:unchecked { background: $border; }
QMenu::indicator:exclusive:checked { background: $accent; }

QToolTip { background: $surface_alt; color: $text; border: 1px solid $border; padding: 4px 6px; }

QDialog { background: $bg; }

QLabel#InfoSectionHeader {
    color: $accent; font-size: 13px; font-weight: 600;
    padding-top: 6px; border-bottom: 1px solid $border;
}
QLabel#InfoKey { color: $text_dim; }
QLabel#InfoValue { color: $text; }

QScrollArea#InfoScroll { border: none; background: $bg; }
QWidget#InfoContent { background: $bg; }

QPushButton {
    background: $surface_alt; color: $text;
    border: 1px solid $border; border-radius: 6px; padding: 6px 16px;
}
QPushButton:hover { border-color: $accent; }
QPushButton:pressed { background: $border; }

QListView {
    background: transparent; border: none; outline: none;
}
QListView::item { padding: 5px 8px; border-radius: 4px; }
QListView::item:hover { background: $surface; }
QListView::item:selected { background: $surface_alt; }

QPushButton#PlaylistFooter {
    background: transparent; border: none; color: $text_dim;
    font-size: 11px; text-align: left; padding: 2px 4px;
}

QDockWidget { color: $text; titlebar-close-icon: none; titlebar-normal-icon: none; }
QDockWidget::title {
    background: $surface; border-bottom: 1px solid $border;
    padding: 4px 8px; font-size: 12px; font-weight: 600;
}

QStatusBar { background: $surface; color: $text_dim; border-top: 1px solid $border; }
QStatusBar::item { border: none; }
""")
