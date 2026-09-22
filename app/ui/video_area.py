"""Video display area: mouse interaction around the video surface.

Owns the stacked layout (video surface + idle overlay) and implements the
mouse contract (spec §12):

* double-click → fullscreen toggle
* single left click → play/pause (delayed, so it does not fire on the first
  click of a double-click)
* mouse wheel → volume step
* right click → context menu (emitted as a signal; the window builds the menu)
* any movement → ``userActivity`` (used by the fullscreen auto-hide logic)

The backend-provided surface is a child widget (``QOpenGLWidget``). Mouse
events it does not consume would normally propagate here, but to be robust
regardless of the surface's own event handling we install an event filter on
it and handle the relevant events there — one code path, no double delivery
(the filter consumes the events it handles).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget

_SINGLE_CLICK_INTERVAL_MS = 260
_WHEEL_VOLUME_STEP = 5


class VideoArea(QWidget):
    """Video container implementing the player's mouse behaviour."""

    fullscreenToggleRequested = Signal()
    pauseToggleRequested = Signal()
    volumeStepRequested = Signal(int)  # signed step, positive = louder
    contextMenuRequested = Signal(QPoint)  # global position
    userActivity = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("VideoArea")
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self._cursor_hidden = False
        self._surface: QWidget | None = None

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(_SINGLE_CLICK_INTERVAL_MS)
        self._click_timer.timeout.connect(lambda: self.pauseToggleRequested.emit())

        self._stack = QStackedLayout(self)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self._idle_overlay = self._build_idle_overlay()
        self._stack.addWidget(self._idle_overlay)
        # Small always-on-top badge (StackAll): "Buffering… 42%" for streams.
        self._buffering_badge = QLabel("")
        self._buffering_badge.setObjectName("BufferingBadge")
        self._buffering_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._buffering_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._buffering_badge.hide()
        badge_wrap = QVBoxLayout()
        badge_wrap.setContentsMargins(0, 0, 0, 24)
        badge_wrap.addStretch()
        badge_wrap.addWidget(self._buffering_badge, 0, Qt.AlignmentFlag.AlignHCenter)
        badge_wrap.addStretch()
        badge_host = QWidget()
        badge_host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        badge_host.setLayout(badge_wrap)
        self._stack.addWidget(badge_host)
        # One-time software-renderer notice (top strip, dismissible).
        self._renderer_notice = self._build_renderer_notice()
        self._stack.addWidget(self._renderer_notice)  # last = topmost
        self._renderer_notice.hide()

    # ------------------------------------------------------------------ setup
    def _build_idle_overlay(self) -> QWidget:
        overlay = QWidget()
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(overlay)
        layout.addStretch()
        self._idle_title_label = QLabel("Nothing playing")
        self._idle_title_label.setObjectName("IdleTitle")
        self._idle_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._idle_hint_label = QLabel("Open a media file to start (Ctrl+O)")
        self._idle_hint_label.setObjectName("IdleHint")
        self._idle_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._idle_title_label)
        layout.addWidget(self._idle_hint_label)
        layout.addStretch()
        return overlay

    def set_surface(self, surface: QWidget) -> None:
        """Attach the backend's video surface below the idle overlay."""
        if self._surface is not None:
            return
        self._surface = surface
        surface.installEventFilter(self)
        self._stack.insertWidget(0, surface)  # underneath the overlay
        self._stack.setCurrentWidget(surface)

    def _build_renderer_notice(self) -> QWidget:
        notice = QWidget()
        notice.setObjectName("RendererNotice")
        layout = QHBoxLayout(notice)
        layout.setContentsMargins(10, 6, 6, 6)
        label = QLabel(
            "Software rendering detected — video may be slow or black "
            "(Remote Desktop or missing GPU drivers). Audio is unaffected."
        )
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        dismiss = QPushButton("×")
        dismiss.setFixedSize(22, 22)
        dismiss.setToolTip("Dismiss")
        dismiss.clicked.connect(notice.hide)
        layout.addWidget(dismiss, 0, Qt.AlignmentFlag.AlignTop)
        return notice

    def show_renderer_notice(self) -> None:
        """Show the one-time software-renderer warning strip."""
        self._renderer_notice.show()
        self._renderer_notice.raise_()

    def set_idle_visible(self, visible: bool) -> None:
        self._idle_overlay.setVisible(visible)

    def set_buffering(self, percent: int | None) -> None:
        """Show/hide the buffering badge (``None`` hides it)."""
        if percent is None:
            self._buffering_badge.hide()
            return
        text = "Buffering…" if percent <= 0 else f"Buffering… {percent}%"
        self._buffering_badge.setText(text)
        self._buffering_badge.adjustSize()
        self._buffering_badge.show()
        self._buffering_badge.raise_()

    def set_idle_message(self, title: str, hint: str) -> None:
        """Update the overlay text (e.g. 'Nothing playing' vs 'Finished')."""
        self._idle_title_label.setText(title)
        self._idle_hint_label.setText(hint)

    # ------------------------------------------------------------- event handling
    def eventFilter(self, watched, event) -> bool:
        if watched is self._surface:
            event_type = event.type()
            if event_type == QEvent.Type.MouseButtonDblClick:
                self._handle_double_click(event)
                return True
            if event_type == QEvent.Type.MouseButtonPress:
                self._handle_press(event)
                return True
            if event_type == QEvent.Type.Wheel:
                self._handle_wheel(event)
                return True
            if event_type == QEvent.Type.MouseMove:
                self.userActivity.emit()
                return False
        return super().eventFilter(watched, event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._handle_double_click(event)

    def mousePressEvent(self, event) -> None:
        self._handle_press(event)

    def mouseMoveEvent(self, event) -> None:
        self.userActivity.emit()

    def wheelEvent(self, event) -> None:
        self._handle_wheel(event)

    # -------------------------------------------------------------- shared logic
    def _handle_press(self, event) -> None:
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            # Delayed so the first click of a double-click does not pause.
            self._click_timer.start()
        elif button == Qt.MouseButton.RightButton:
            self.contextMenuRequested.emit(event.globalPosition().toPoint())
        self.userActivity.emit()

    def _handle_double_click(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.fullscreenToggleRequested.emit()
        self.userActivity.emit()

    def _handle_wheel(self, event) -> None:
        delta = event.angleDelta().y()
        if delta:
            step = _WHEEL_VOLUME_STEP if delta > 0 else -_WHEEL_VOLUME_STEP
            self.volumeStepRequested.emit(step)
        self.userActivity.emit()

    # ----------------------------------------------------------------- cursor
    def set_cursor_hidden(self, hidden: bool) -> None:
        """Blank/restore the cursor over the video area (fullscreen auto-hide)."""
        if hidden == self._cursor_hidden:
            return
        self._cursor_hidden = hidden
        self.setCursor(Qt.CursorShape.BlankCursor if hidden else Qt.CursorShape.ArrowCursor)
