"""Non-blocking dialogs (media information).

The dialog is refreshed from the controller whenever it is shown and whenever
a new media loads while it is open — playback is never interrupted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.media_info import (
    MediaDetails,
    estimate_overall_bitrate,
    format_container_name,
    format_details_report,
    selected_or_first,
    tracks_of_kind,
)
from app.core.models import TrackKind
from app.utils.format import format_bitrate, format_size, format_time

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as QtWidget

    from app.player.controller import PlayerController

_SECTION_SPACING = 14


class MediaInfoDialog(QDialog):
    """Shows general/video/audio/subtitle information about the current media."""

    def __init__(self, controller: PlayerController, parent: QtWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("Media Information")
        self.setMinimumSize(520, 380)
        self.setSizeGripEnabled(True)

        self._report = ""

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setObjectName("InfoScroll")

        self._copy_button = QPushButton("Copy to Clipboard")
        self._copy_button.clicked.connect(self._copy_report)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(12, 8, 12, 12)
        buttons.addWidget(self._copy_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll, 1)
        layout.addLayout(buttons)

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Rebuild the content from the controller's current snapshot."""
        details = self._controller.media_details()
        self._report = format_details_report(details)
        self._scroll.setWidget(self._build_content(details))

    def _build_content(self, details: MediaDetails) -> QWidget:
        content = QWidget()
        content.setObjectName("InfoContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(_SECTION_SPACING)

        if details.is_empty:
            empty = QLabel("No media loaded.")
            empty.setObjectName("InfoValue")
            layout.addWidget(empty)
            layout.addStretch()
            return content

        self._add_section(layout, "General", self._general_rows(details))
        for header, rows in self._track_sections(details):
            self._add_section(layout, header, rows)
        layout.addStretch()
        return content

    # ------------------------------------------------------------- builders
    @staticmethod
    def _general_rows(details: MediaDetails) -> list[tuple[str, str]]:
        rows = [
            ("Title", details.title or "—"),
            ("File", details.file_path or details.uri or "—"),
            ("Size", format_size(details.file_size)),
            ("Container", format_container_name(details.container) or "—"),
            ("Duration", format_time(details.duration)),
        ]
        bitrate = estimate_overall_bitrate(details)
        rows.append(
            ("Overall bitrate", f"{format_bitrate(bitrate)} (estimated)" if bitrate else "—")
        )
        return rows

    @staticmethod
    def _track_sections(details: MediaDetails) -> list[tuple[str, list[tuple[str, str]]]]:
        sections: list[tuple[str, list[tuple[str, str]]]] = []

        video_tracks = tracks_of_kind(details, TrackKind.VIDEO)
        if video_tracks:
            primary = selected_or_first(video_tracks)
            rows: list[tuple[str, str]] = []
            for track in video_tracks:
                label = "Video" if len(video_tracks) == 1 else f"Track {track.id}"
                codec = track.codec or "—"
                if track.codec_desc:
                    codec += f" ({track.codec_desc})"
                if track.is_selected:
                    codec += "  ✓"
                rows.append((label, codec))
                rows.append(("", track.dimensions or "—"))
                rows.append(("", f"{track.framerate:.2f} fps" if track.framerate else "—"))
                if track.bitrate:
                    rows.append(("", format_bitrate(track.bitrate)))
            if primary is not None and primary.is_selected:
                if details.pixel_format:
                    rows.append(("Pixel format", details.pixel_format))
                if details.display_aspect:
                    rows.append(("Aspect", details.display_aspect))
            sections.append(("Video", rows))

        audio_tracks = tracks_of_kind(details, TrackKind.AUDIO)
        if audio_tracks:
            rows = []
            for track in audio_tracks:
                label = "Audio" if len(audio_tracks) == 1 else f"Track {track.id}"
                codec = track.codec or "—"
                if track.codec_desc:
                    codec += f" ({track.codec_desc})"
                if track.is_selected:
                    codec += "  ✓"
                rows.append((label, codec))
                if track.sample_rate:
                    rows.append(("", f"{track.sample_rate / 1000:g} kHz"))
                if track.channels:
                    layout = f" ({track.channel_layout})" if track.channel_layout else ""
                    rows.append(("", f"{track.channels}{layout}"))
                if track.language:
                    rows.append(("", track.language))
                if track.bitrate:
                    rows.append(("", format_bitrate(track.bitrate)))
            sections.append(("Audio", rows))

        subtitle_tracks = tracks_of_kind(details, TrackKind.SUBTITLE)
        if subtitle_tracks:
            rows = []
            for track in subtitle_tracks:
                name = track.title or (
                    track.language.upper() if track.language else f"Track {track.id}"
                )
                source = "external" if track.is_external else "embedded"
                rows.append((name, f"{track.codec or '—'} ({source})"))
            sections.append(("Subtitles", rows))
        else:
            sections.append(("Subtitles", [("None", "")]))

        return sections

    def _add_section(self, layout: QVBoxLayout, header: str, rows: list[tuple[str, str]]) -> None:
        header_label = QLabel(header)
        header_label.setObjectName("InfoSectionHeader")
        layout.addWidget(header_label)

        for key, value in rows:
            if key == "":
                # Continuation row (indented under the track it belongs to).
                row = QHBoxLayout()
                row.setContentsMargins(18, 0, 0, 0)
                row.setSpacing(12)
                value_label = QLabel(value)
                value_label.setObjectName("InfoValue")
                value_label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                row.addWidget(value_label)
                layout.addLayout(row)
                continue
            row = QHBoxLayout()
            row.setSpacing(12)
            key_label = QLabel(key)
            key_label.setObjectName("InfoKey")
            key_label.setMinimumWidth(120)
            value_label = QLabel(value)
            value_label.setObjectName("InfoValue")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.addWidget(key_label)
            row.addWidget(value_label)
            layout.addLayout(row)

    # -------------------------------------------------------------- clipboard
    def _copy_report(self) -> None:
        from PySide6.QtWidgets import QApplication

        if self._report:
            QApplication.clipboard().setText(self._report)

    # ------------------------------------------------------------------ Qt
    def showEvent(self, event) -> None:  # Qt override
        self.refresh()
        super().showEvent(event)


#: Stream URL schemes the engine is known to handle directly (whitelist —
#: everything else is rejected before it reaches the engine; note ytdl is
#: disabled, so e.g. youtube.com page URLs are *not* playable by design).
_SUPPORTED_URL_SCHEMES = frozenset(
    {"http", "https", "rtsp", "rtsps", "rtmp", "udp", "rtp", "mms", "ftp"}
)


def is_supported_stream_url(url: str) -> bool:
    """True for direct stream URLs the player can open (scheme whitelist)."""
    scheme, _, host_part = url.partition("://")
    return (
        scheme.lower() in _SUPPORTED_URL_SCHEMES
        and bool(host_part.strip())
        and " " not in url
    )


class OpenUrlDialog(QDialog):
    """Ask for a network stream URL (modal, with inline validation)."""

    def __init__(self, parent: QtWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open URL")
        self.setMinimumWidth(460)
        self._url: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Stream or media URL:"))

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("http://, https://, rtsp://, rtmp://, udp:// …")
        self._edit.setMinimumWidth(420)
        layout.addWidget(self._edit)

        self._validation = QLabel("")
        self._validation.setObjectName("ValidationError")
        self._validation.hide()
        layout.addWidget(self._validation)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Open).setEnabled(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._buttons = buttons
        self._edit.textChanged.connect(self._on_text_changed)
        self._edit.returnPressed.connect(self._on_accept)

    def _on_text_changed(self, text: str) -> None:
        url = text.strip()
        valid = is_supported_stream_url(url)
        self._buttons.button(QDialogButtonBox.StandardButton.Open).setEnabled(valid)
        if not text.strip():
            self._validation.hide()
        elif not valid:
            self._validation.setText(
                "Unsupported URL — expected a direct stream address "
                "(http, https, rtsp, rtmp, udp, rtp, mms or ftp)."
            )
            self._validation.show()
        else:
            self._validation.hide()

    def _on_accept(self) -> None:
        url = self._edit.text().strip()
        if not is_supported_stream_url(url):
            return
        self._url = url
        self.accept()

    @property
    def url(self) -> str | None:
        """The accepted URL (``None`` if cancelled or invalid)."""
        return self._url


class AboutDialog(QDialog):
    """About Glint: version, licence and the third-party inventory.

    The component list mirrors docs/REDISTRIBUTION.md — keeping the two in
    sync is covered by the release checklist.
    """

    def __init__(self, parent: QtWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Glint")
        self.setMinimumWidth(460)

        from app import __version__

        layout = QVBoxLayout(self)

        title = QLabel(f"Glint {__version__}")
        title.setObjectName("IdleTitle")
        layout.addWidget(title)

        intro = QLabel(
            "An original, open-source desktop media player built with "
            "Python, Qt and the libmpv playback engine."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(QLabel(""))

        licence = QLabel(
            "Licensed under the GNU General Public License v3.0 or later "
            "(GPL-3.0-or-later). The complete licence text ships with every "
            "distribution and is available at "
            "https://www.gnu.org/licenses/gpl-3.0.html"
        )
        licence.setWordWrap(True)
        layout.addWidget(licence)

        layout.addWidget(QLabel(""))

        components_header = QLabel("Third-party components")
        components_header.setObjectName("IdleHint")
        layout.addWidget(components_header)
        for line in (
            "Qt 6 / PySide6 — GUI toolkit (LGPL-3.0)",
            "libmpv — playback engine, bundling FFmpeg and libass (GPL-2.0-or-later builds)",
            "python-mpv — libmpv bindings (GPL-2.0-or-later / LGPL-2.1-or-later)",
        ):
            row = QLabel(f"• {line}")
            row.setWordWrap(True)
            layout.addWidget(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.reject)
        layout.addWidget(buttons)
