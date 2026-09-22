"""Main window: menus, video area, control bar, playlist dock, fullscreen.

The window is engine-agnostic — it only knows the controller API (transport)
and the playback-queue API (playlist-level operations). File dialogs, recent
files and drag-and-drop are owned here.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.core import m3u
from app.core.models import MediaInfo, PlaybackState
from app.core.playback import SPEED_PRESETS
from app.core.playlist import RepeatMode, title_for_uri
from app.core.shortcuts import PlayerAction, ShortcutConfig
from app.core.subtitles import (
    SUBTITLE_COLOR_PRESETS,
    SUBTITLE_POSITION_PRESETS,
    SUBTITLE_SIZE_PRESETS,
)
from app.player.backend import PlayerError
from app.player.controller import PlayerController
from app.player.queue import PlaybackQueue
from app.ui.autohide import AutoHideController
from app.ui.controls import ControlBar
from app.ui.dialogs import MediaInfoDialog, OpenUrlDialog
from app.ui.icons import load_icon
from app.ui.playlist_panel import PlaylistPanel
from app.ui.shortcuts import ShortcutManager
from app.ui.video_area import VideoArea
from app.ui.workers import FolderScanWorker
from app.utils.logging import get_logger
from app.utils.paths import config_dir

logger = get_logger("ui.main_window")

_ERROR_BANNER_MS = 6000
_STATUS_MESSAGE_MS = 4000
_SEEK_STEP_SECONDS = 5.0
_SUB_DELAY_STEP = 0.1  # seconds per delay nudge
_AUDIO_SYNC_STEP = 0.05  # seconds per audio-sync nudge (50 ms, VLC-style)
_SEEK_LONG_STEP_SECONDS = 30.0
_VOLUME_STEP = 5

# The file dialog filter is a *convenience*, not a capability claim: the
# engine decides what actually plays (spec §7).
_FILE_FILTER = (
    "All files (*);;"
    "Common media files (*.mp4 *.mkv *.avi *.mov *.webm *.mpeg *.mpg *.ts *.m4v "
    "*.mp3 *.aac *.flac *.wav *.ogg *.opus *.m4a)"
)
_PLAYLIST_FILTER = "Playlists (*.m3u8 *.m3u);;All files (*)"
_SUBTITLE_FILTER = (
    "Subtitles (*.srt *.ass *.ssa *.vtt *.sub *.idx *.sup *.smi);;All files (*)"
)


class MainWindow(QMainWindow):
    """Top-level window: owns layout and widget wiring, no engine knowledge."""

    def __init__(
        self,
        controller: PlayerController,
        queue: PlaybackQueue,
        recents,  # app.core.recents.RecentFiles (kept loose for testability)
        settings,  # app.settings_service.SettingsService
    ) -> None:
        super().__init__()
        self._controller = controller
        self._queue = queue
        self._recents = recents
        self._settings = settings
        self._was_maximized = False
        self._scans_in_flight = 0
        # Fullscreen chrome state: the playlist dock hides on enter (video-only
        # view, as the spec's fullscreen requirement demands), is restored on
        # exit, and behaves like the control bar while fullscreen (shown on
        # request, hidden again by the idle auto-hide).
        self._playlist_dock_was_visible = True
        self._fs_playlist_visible = False

        self.setWindowTitle("Glint")
        self.setWindowIcon(load_icon("app"))
        self.resize(1024, 640)
        self.setMinimumSize(560, 380)
        self.setAcceptDrops(True)

        self._shortcuts = ShortcutManager(
            self, ShortcutConfig.load(config_dir() / "shortcuts.json")
        )

        self._build_menu()
        self._build_ui(controller, queue)
        self._wire(controller, queue)
        self._register_shortcuts()

    # ------------------------------------------------------------------ setup
    def _build_menu(self) -> None:
        self._build_file_menu()
        self._build_playback_menu()
        self._build_audio_menu()
        self._build_video_menu()
        self._build_subtitles_menu()
        self._build_playlist_menu()
        self._build_view_menu()
        self._build_tools_menu()
        self._build_help_menu()

    def _build_file_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&File")

        act_open = QAction(load_icon("folder-open"), "Open File…", self)
        act_open.setText(self._shortcuts.display_text("Open File…", PlayerAction.OPEN_FILE))
        act_open.triggered.connect(self._open_files)
        menu.addAction(act_open)

        act_url = QAction("Open URL…", self)
        act_url.setText(self._shortcuts.display_text("Open URL…", PlayerAction.OPEN_URL))
        act_url.triggered.connect(self._open_url)
        menu.addAction(act_url)

        act_add = QAction("Add File(s)…", self)
        act_add.triggered.connect(self._add_files)
        menu.addAction(act_add)

        act_folder = QAction("Add Folder…", self)
        act_folder.triggered.connect(self._add_folder)
        menu.addAction(act_folder)

        menu.addSeparator()
        self._recent_menu = menu.addMenu("Recent Files")
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)

        menu.addSeparator()
        act_quit = QAction("Exit", self)
        act_quit.setText(self._shortcuts.display_text("Exit", PlayerAction.QUIT))
        act_quit.triggered.connect(self.close)
        menu.addAction(act_quit)

    def _build_playback_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&Playback")

        act_toggle = QAction("Play / Pause", self)
        act_toggle.setText(self._shortcuts.display_text("Play / Pause", PlayerAction.PLAY_PAUSE))
        act_toggle.triggered.connect(self._controller.toggle_play_pause)
        menu.addAction(act_toggle)

        act_prev = QAction("Previous", self)
        act_prev.setText(self._shortcuts.display_text("Previous", PlayerAction.PREVIOUS_TRACK))
        act_prev.triggered.connect(self._queue.previous)
        menu.addAction(act_prev)

        act_next = QAction("Next", self)
        act_next.setText(self._shortcuts.display_text("Next", PlayerAction.NEXT_TRACK))
        act_next.triggered.connect(lambda: self._queue.next(auto=False))
        menu.addAction(act_next)

        act_stop = QAction("Stop", self)
        act_stop.triggered.connect(self._controller.stop)
        menu.addAction(act_stop)

        menu.addSeparator()
        self._populate_speed_menu(menu.addMenu("Speed"))
        menu.addSeparator()

        act_normal = QAction("Normal Speed", self)
        act_normal.setText(self._shortcuts.display_text("Normal Speed", PlayerAction.SPEED_RESET))
        act_normal.triggered.connect(self._controller.reset_speed)
        menu.addAction(act_normal)

        act_step_fwd = QAction("Frame Forward", self)
        act_step_fwd.setText(
            self._shortcuts.display_text("Frame Forward", PlayerAction.FRAME_STEP_FORWARD)
        )
        act_step_fwd.triggered.connect(lambda: self._controller.step_frame(True))
        menu.addAction(act_step_fwd)

        act_step_back = QAction("Frame Back", self)
        act_step_back.setText(
            self._shortcuts.display_text("Frame Back", PlayerAction.FRAME_STEP_BACKWARD)
        )
        act_step_back.triggered.connect(lambda: self._controller.step_frame(False))
        menu.addAction(act_step_back)

    def _build_audio_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&Audio")
        self._audio_menu = menu
        menu.aboutToShow.connect(lambda: self._populate_audio_menu(menu))
        self._populate_audio_menu(menu)

    def _populate_audio_menu(self, menu: QMenu) -> None:
        menu.clear()
        controller = self._controller

        # --- dynamic track section (exclusive) ---
        group = QActionGroup(self)
        group.setExclusive(True)
        group.triggered.connect(self._on_audio_track_action)

        current = controller.selected_audio_track()
        off = QAction("Disabled", self)
        off.setCheckable(True)
        off.setChecked(current is None)
        off.setData(None)
        group.addAction(off)
        menu.addAction(off)
        for track in controller.audio_tracks():
            action = QAction(track.display_name, self)
            action.setCheckable(True)
            action.setChecked(current == track.id)
            action.setData(track.id)
            group.addAction(action)
            menu.addAction(action)

        menu.addSeparator()

        # --- audio sync (delay of audio relative to video) ---
        sync_menu = menu.addMenu("Audio Sync")
        act_earlier = QAction("Earlier", self)
        act_earlier.setText(
            self._shortcuts.display_text("Earlier", PlayerAction.AUDIO_DELAY_DOWN)
        )
        act_earlier.triggered.connect(lambda: self._nudge_audio_delay(-_AUDIO_SYNC_STEP))
        sync_menu.addAction(act_earlier)
        act_later = QAction("Later", self)
        act_later.setText(
            self._shortcuts.display_text("Later", PlayerAction.AUDIO_DELAY_UP)
        )
        act_later.triggered.connect(lambda: self._nudge_audio_delay(_AUDIO_SYNC_STEP))
        sync_menu.addAction(act_later)
        act_reset_sync = QAction("Reset", self)
        act_reset_sync.setText(
            self._shortcuts.display_text("Reset", PlayerAction.AUDIO_DELAY_RESET)
        )
        act_reset_sync.triggered.connect(self._reset_audio_delay)
        sync_menu.addAction(act_reset_sync)

    def _build_video_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&Video")
        self._video_menu = menu
        menu.aboutToShow.connect(lambda: self._populate_video_menu(menu))
        self._populate_video_menu(menu)

    def _populate_video_menu(self, menu: QMenu) -> None:
        menu.clear()
        controller = self._controller

        # --- dynamic track section (exclusive) ---
        group = QActionGroup(self)
        group.setExclusive(True)
        group.triggered.connect(self._on_video_track_action)

        current = controller.selected_video_track()
        off = QAction("Disabled", self)
        off.setCheckable(True)
        off.setChecked(current is None)
        off.setData(None)
        group.addAction(off)
        menu.addAction(off)
        for track in controller.video_tracks():
            label = track.display_name
            if track.dimensions:
                label = f"{label} — {track.dimensions}"
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(current == track.id)
            action.setData(track.id)
            group.addAction(action)
            menu.addAction(action)

        menu.addSeparator()

        act_screenshot = QAction("Take Screenshot", self)
        act_screenshot.setText(
            self._shortcuts.display_text("Take Screenshot", PlayerAction.SCREENSHOT)
        )
        act_screenshot.triggered.connect(self._take_screenshot)
        menu.addAction(act_screenshot)

    def _build_subtitles_menu(self) -> None:
        """Subtitles menu: track list is rebuilt on every show (fresh state)."""
        menu: QMenu = self.menuBar().addMenu("Su&btitles")
        self._subtitles_menu = menu
        menu.aboutToShow.connect(lambda: self._populate_subtitles_menu(menu))
        self._populate_subtitles_menu(menu)

    def _populate_subtitles_menu(self, menu: QMenu) -> None:
        menu.clear()
        controller = self._controller

        # --- dynamic track section (exclusive) ---
        group = QActionGroup(self)
        group.setExclusive(True)
        group.triggered.connect(self._on_subtitle_track_action)

        current = controller.selected_subtitle_track()
        off = QAction("Disabled", self)
        off.setCheckable(True)
        off.setChecked(current is None)
        off.setData(None)
        group.addAction(off)
        menu.addAction(off)
        for track in controller.subtitle_tracks():
            action = QAction(track.display_name, self)
            action.setCheckable(True)
            action.setChecked(current == track.id)
            action.setData(track.id)
            group.addAction(action)
            menu.addAction(action)

        menu.addSeparator()

        # --- secondary track (displayed in addition to the primary) ---
        secondary_menu = menu.addMenu("Secondary Track")
        secondary_group = QActionGroup(self)
        secondary_group.setExclusive(True)
        secondary_group.triggered.connect(self._on_secondary_track_action)
        current_secondary = controller.selected_secondary_subtitle_track()
        off_secondary = QAction("None", self)
        off_secondary.setCheckable(True)
        off_secondary.setChecked(current_secondary is None)
        off_secondary.setData(None)
        secondary_group.addAction(off_secondary)
        secondary_menu.addAction(off_secondary)
        for track in controller.subtitle_tracks():
            action = QAction(track.display_name, self)
            action.setCheckable(True)
            action.setChecked(current_secondary == track.id)
            action.setData(track.id)
            secondary_group.addAction(action)
            secondary_menu.addAction(action)

        menu.addSeparator()

        # --- static section ---
        act_add_sub = QAction("Add Subtitle File…", self)
        act_add_sub.triggered.connect(self._add_subtitle_file)
        menu.addAction(act_add_sub)

        act_show = QAction("Show Subtitles", self)
        act_show.setCheckable(True)
        act_show.setChecked(controller.subtitle_visibility)
        act_show.toggled.connect(controller.set_subtitle_visibility)
        menu.addAction(act_show)

        menu.addSeparator()

        delay_menu = menu.addMenu("Delay")
        act_earlier = QAction("Earlier", self)
        act_earlier.setText(
            self._shortcuts.display_text("Earlier", PlayerAction.SUB_DELAY_DOWN)
        )
        act_earlier.triggered.connect(lambda: self._nudge_subtitle_delay(-_SUB_DELAY_STEP))
        delay_menu.addAction(act_earlier)
        act_later = QAction("Later", self)
        act_later.setText(self._shortcuts.display_text("Later", PlayerAction.SUB_DELAY_UP))
        act_later.triggered.connect(lambda: self._nudge_subtitle_delay(_SUB_DELAY_STEP))
        delay_menu.addAction(act_later)
        act_reset_delay = QAction("Reset", self)
        act_reset_delay.setText(
            self._shortcuts.display_text("Reset", PlayerAction.SUB_DELAY_RESET)
        )
        act_reset_delay.triggered.connect(self._reset_subtitle_delay)
        delay_menu.addAction(act_reset_delay)

        appearance_menu = menu.addMenu("Appearance")

        size_menu = appearance_menu.addMenu("Size")
        for label, value in SUBTITLE_SIZE_PRESETS.items():
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, v=value: controller.set_subtitle_appearance(size=v)
            )
            size_menu.addAction(action)

        position_menu = appearance_menu.addMenu("Position")
        for label, value in SUBTITLE_POSITION_PRESETS.items():
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, v=value: controller.set_subtitle_appearance(position=v)
            )
            position_menu.addAction(action)

        color_menu = appearance_menu.addMenu("Color")
        for label, value in SUBTITLE_COLOR_PRESETS.items():
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, v=value: controller.set_subtitle_appearance(color=v)
            )
            color_menu.addAction(action)

    def _on_subtitle_track_action(self, action: QAction) -> None:
        track_id = action.data()
        self._controller.select_subtitle_track(track_id)

    def _build_playlist_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&Playlist")

        act_add = QAction("Add File(s)…", self)
        act_add.triggered.connect(self._add_files)
        menu.addAction(act_add)

        act_folder = QAction("Add Folder…", self)
        act_folder.triggered.connect(self._add_folder)
        menu.addAction(act_folder)

        menu.addSeparator()

        self._act_remove_selected = QAction("Remove Selected", self)
        menu.addAction(self._act_remove_selected)

        act_clear = QAction("Clear", self)
        act_clear.triggered.connect(self._queue.clear)
        menu.addAction(act_clear)

        menu.addSeparator()

        self._act_shuffle = QAction("Shuffle", self)
        self._act_shuffle.setCheckable(True)
        self._act_shuffle.triggered.connect(self._queue.toggle_shuffle)
        menu.addAction(self._act_shuffle)

        repeat_menu = menu.addMenu("Repeat")
        self._repeat_group = QActionGroup(self)
        self._repeat_group.setExclusive(True)
        self._repeat_group.triggered.connect(self._on_repeat_action)
        for mode in RepeatMode:
            action = QAction(mode.value.capitalize(), self)
            action.setCheckable(True)
            action.setData(mode)
            if mode is RepeatMode.OFF:
                action.setChecked(True)
            self._repeat_group.addAction(action)
            repeat_menu.addAction(action)

        menu.addSeparator()

        act_save = QAction("Save Playlist…", self)
        act_save.setText(self._shortcuts.display_text("Save Playlist…", PlayerAction.SAVE_PLAYLIST))
        act_save.triggered.connect(self._save_playlist)
        menu.addAction(act_save)

        act_load = QAction("Open Playlist…", self)
        act_load.triggered.connect(self._open_playlist)
        menu.addAction(act_load)

    def _build_tools_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&Tools")

        act_info = QAction("Media Information…", self)
        act_info.setText(self._shortcuts.display_text("Media Information…", PlayerAction.MEDIA_INFO))
        act_info.triggered.connect(self._show_media_info)
        menu.addAction(act_info)

        act_settings = QAction("Settings…", self)
        act_settings.setText(self._shortcuts.display_text("Settings…", PlayerAction.SETTINGS))
        act_settings.triggered.connect(self._show_settings)
        menu.addAction(act_settings)

    def _build_help_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&Help")

        act_about = QAction("About Glint", self)
        act_about.triggered.connect(self._show_about)
        menu.addAction(act_about)

        act_about_qt = QAction("About Qt", self)
        act_about_qt.triggered.connect(lambda: QMessageBox.aboutQt(self, "About Qt"))
        menu.addAction(act_about_qt)

    def _build_view_menu(self) -> None:
        menu: QMenu = self.menuBar().addMenu("&View")

        act_playlist = QAction(load_icon("list"), "Playlist", self)
        act_playlist.setText(self._shortcuts.display_text("Playlist", PlayerAction.TOGGLE_PLAYLIST))
        act_playlist.setCheckable(True)
        act_playlist.setChecked(True)
        act_playlist.triggered.connect(
            lambda checked: self._playlist_dock.setVisible(checked)
        )
        self._playlist_dock_action = act_playlist
        menu.addAction(act_playlist)

        act_fullscreen = QAction("Fullscreen", self)
        act_fullscreen.setText(self._shortcuts.display_text("Fullscreen", PlayerAction.FULLSCREEN))
        # Deferred: toggling fullscreen hides the menu bar while this very
        # menu is still closing, which some platforms handle badly.
        act_fullscreen.triggered.connect(lambda: QTimer.singleShot(0, self.toggle_fullscreen))
        menu.addAction(act_fullscreen)

    def _populate_speed_menu(self, menu: QMenu) -> None:
        """Fill a menu with the speed presets (shared by menus + context menu)."""
        current = self._controller.speed
        for preset in SPEED_PRESETS:
            action = menu.addAction(f"{preset:g}×")
            action.setCheckable(True)
            action.setChecked(abs(preset - current) < 1e-9)
            action.triggered.connect(
                lambda _checked=False, value=preset: self._controller.set_speed(value)
            )

    def _build_ui(self, controller: PlayerController, queue: PlaybackQueue) -> None:
        central = QWidget()
        central.setObjectName("CentralArea")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Non-blocking error banner (auto-hides).
        self._error_banner = QLabel(central)
        self._error_banner.setObjectName("ErrorBanner")
        self._error_banner.setWordWrap(True)
        self._error_banner.hide()
        root.addWidget(self._error_banner)
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._error_banner.hide)

        # Video area: engine surface + idle overlay, with mouse handling.
        self._video_area = VideoArea()
        self._surface = controller.create_video_surface(self._video_area)
        self._video_area.set_surface(self._surface)
        root.addWidget(self._video_area, 1)

        self._controls = ControlBar()
        root.addWidget(self._controls)

        self.setCentralWidget(central)

        # Playlist dock.
        self._playlist_panel = PlaylistPanel(queue)
        self._playlist_dock = QDockWidget("Playlist", self)
        self._playlist_dock.setVisible(self._settings.settings.interface.show_playlist_at_start)
        self._playlist_dock.setObjectName("PlaylistDock")
        self._playlist_dock.setWidget(self._playlist_panel)
        self._playlist_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._playlist_panel.setMinimumWidth(280)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._playlist_dock)
        self._playlist_dock.visibilityChanged.connect(
            lambda visible: self._playlist_dock_action.setChecked(visible)
        )

        # Menu actions that need the (now existing) panel.
        self._act_remove_selected.triggered.connect(self._playlist_panel.remove_selected)

        # Playlist panel requests → file dialogs (owned here).
        self._playlist_panel.addFilesRequested.connect(self._add_files)
        self._playlist_panel.addFolderRequested.connect(self._add_folder)
        self._playlist_panel.saveRequested.connect(self._save_playlist)
        self._playlist_panel.loadRequested.connect(self._open_playlist)

        self.statusBar().showMessage("Ready")

    def _wire(self, controller: PlayerController, queue: PlaybackQueue) -> None:
        # controller → UI
        controller.stateChanged.connect(self._on_state_changed)
        controller.mediaLoaded.connect(self._on_media_loaded)
        controller.positionChanged.connect(self._controls.set_position)
        controller.durationChanged.connect(self._controls.set_duration)
        controller.errorOccurred.connect(self._on_error)
        controller.volumeChanged.connect(self._controls.set_volume)
        controller.mutedChanged.connect(self._controls.set_muted)
        controller.speedChanged.connect(self._controls.set_speed)
        controller.subtitleDelayChanged.connect(self._on_subtitle_delay_changed)
        controller.audioDelayChanged.connect(self._on_audio_delay_changed)
        controller.bufferingChanged.connect(self._on_buffering)
        controller.streamTitleChanged.connect(self._on_stream_title)
        controller.softwareRenderingDetected.connect(self._on_software_renderer)

        # queue → UI
        queue.shuffleChanged.connect(self._act_shuffle.setChecked)
        queue.repeatChanged.connect(self._on_repeat_changed)
        self._act_shuffle.setChecked(queue.playlist.shuffle)
        self._on_repeat_changed(queue.playlist.repeat)

        # UI → controller/queue
        self._controls.playToggled.connect(controller.toggle_play_pause)
        self._controls.stopClicked.connect(controller.stop)
        self._controls.prevClicked.connect(queue.previous)
        self._controls.nextClicked.connect(lambda: queue.next(auto=False))
        self._controls.seekRequested.connect(controller.seek)
        self._controls.volumeChanged.connect(controller.set_volume)
        self._controls.muteToggled.connect(controller.toggle_mute)
        self._controls.speedSelected.connect(controller.set_speed)
        self._controls.fullscreenToggled.connect(self.toggle_fullscreen)

        # video area interactions
        self._video_area.fullscreenToggleRequested.connect(self.toggle_fullscreen)
        self._video_area.pauseToggleRequested.connect(controller.toggle_play_pause)
        self._video_area.volumeStepRequested.connect(self._step_volume)
        self._video_area.contextMenuRequested.connect(self._show_context_menu)
        self._video_area.userActivity.connect(self._on_user_activity)
        self._controls.entered.connect(self._on_user_activity)

        # fullscreen auto-hide
        self._autohide = AutoHideController(parent=self)
        self._autohide.hidden.connect(self._on_chrome_hidden)
        self._autohide.shown.connect(self._on_chrome_shown)

    def _register_shortcuts(self) -> None:
        shortcuts = self._shortcuts
        shortcuts.bind(PlayerAction.OPEN_FILE, self._open_files)
        shortcuts.bind(PlayerAction.OPEN_URL, self._open_url)
        shortcuts.bind(PlayerAction.QUIT, self.close)
        shortcuts.bind(PlayerAction.PLAY_PAUSE, self._controller.toggle_play_pause)
        shortcuts.bind(PlayerAction.STOP, self._controller.stop)
        shortcuts.bind(PlayerAction.NEXT_TRACK, lambda: self._queue.next(auto=False))
        shortcuts.bind(PlayerAction.PREVIOUS_TRACK, self._queue.previous)
        shortcuts.bind(PlayerAction.TOGGLE_PLAYLIST, self._toggle_playlist_panel)
        shortcuts.bind(PlayerAction.SAVE_PLAYLIST, self._save_playlist)
        shortcuts.bind(
            PlayerAction.SEEK_BACK_SHORT, lambda: self._controller.seek_relative(-_SEEK_STEP_SECONDS)
        )
        shortcuts.bind(
            PlayerAction.SEEK_FORWARD_SHORT,
            lambda: self._controller.seek_relative(_SEEK_STEP_SECONDS),
        )
        shortcuts.bind(
            PlayerAction.SEEK_BACK_LONG,
            lambda: self._controller.seek_relative(-_SEEK_LONG_STEP_SECONDS),
        )
        shortcuts.bind(
            PlayerAction.SEEK_FORWARD_LONG,
            lambda: self._controller.seek_relative(_SEEK_LONG_STEP_SECONDS),
        )
        shortcuts.bind(PlayerAction.VOLUME_UP, lambda: self._step_volume(_VOLUME_STEP))
        shortcuts.bind(PlayerAction.VOLUME_DOWN, lambda: self._step_volume(-_VOLUME_STEP))
        shortcuts.bind(PlayerAction.MUTE, self._controller.toggle_mute)
        shortcuts.bind(PlayerAction.FULLSCREEN, self.toggle_fullscreen)
        shortcuts.bind(PlayerAction.EXIT_FULLSCREEN, self._exit_fullscreen_if_active)
        shortcuts.bind(PlayerAction.SPEED_UP, lambda: self._controller.step_speed(+1))
        shortcuts.bind(PlayerAction.SPEED_DOWN, lambda: self._controller.step_speed(-1))
        shortcuts.bind(PlayerAction.SPEED_RESET, self._controller.reset_speed)
        shortcuts.bind(PlayerAction.FRAME_STEP_FORWARD, lambda: self._controller.step_frame(True))
        shortcuts.bind(PlayerAction.FRAME_STEP_BACKWARD, lambda: self._controller.step_frame(False))
        shortcuts.bind(PlayerAction.CYCLE_SUBTITLES, self._cycle_subtitles)
        shortcuts.bind(
            PlayerAction.SUB_DELAY_DOWN, lambda: self._nudge_subtitle_delay(-_SUB_DELAY_STEP)
        )
        shortcuts.bind(
            PlayerAction.SUB_DELAY_UP, lambda: self._nudge_subtitle_delay(_SUB_DELAY_STEP)
        )
        shortcuts.bind(PlayerAction.SUB_DELAY_RESET, self._reset_subtitle_delay)
        shortcuts.bind(PlayerAction.MEDIA_INFO, self._show_media_info)
        shortcuts.bind(PlayerAction.SETTINGS, self._show_settings)
        shortcuts.bind(PlayerAction.CYCLE_AUDIO, self._cycle_audio_tracks)
        shortcuts.bind(
            PlayerAction.AUDIO_DELAY_DOWN, lambda: self._nudge_audio_delay(-_AUDIO_SYNC_STEP)
        )
        shortcuts.bind(
            PlayerAction.AUDIO_DELAY_UP, lambda: self._nudge_audio_delay(_AUDIO_SYNC_STEP)
        )
        shortcuts.bind(PlayerAction.AUDIO_DELAY_RESET, self._reset_audio_delay)
        shortcuts.bind(PlayerAction.SCREENSHOT, self._take_screenshot)

    # ------------------------------------------------------------- file handling
    def _open_files(self) -> None:
        """Open = replace the playlist with the selection and play it."""
        files, _ = QFileDialog.getOpenFileNames(self, "Open media files", "", _FILE_FILTER)
        if files:
            self._queue.load(files)
            self._queue.play_index(0)

    def _open_url(self) -> None:
        """Ask for a stream URL and play it (replaces the playlist, like Open File)."""
        dialog = OpenUrlDialog(self)
        if dialog.exec() and dialog.url:
            self.open_url(dialog.url)

    def open_url(self, url: str) -> None:
        """Open a validated stream URL (also the drop/URL entry point)."""
        self._queue.load([url])
        self._queue.play_index(0)

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add media files", "", _FILE_FILTER)
        if files:
            self._add_uris_and_maybe_play(files)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if folder:
            self._scan_folder_async(Path(folder), recursive=False)

    def _add_uris_and_maybe_play(self, uris: list[str]) -> None:
        """Add URIs to the playlist; start playback when nothing is playing."""
        added = self._queue.add(uris)
        if added and self._queue.is_idle:
            self._queue.play_index(added[0])

    def _scan_folder_async(self, folder: Path, recursive: bool) -> None:
        """Scan a folder off the GUI thread and add what is found."""
        worker = FolderScanWorker(folder, recursive=recursive)
        self._scans_in_flight += 1
        worker.signals.finished.connect(self._on_scan_finished)
        worker.signals.failed.connect(self._on_scan_failed)
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(worker)

    def _on_scan_finished(self, uris: list) -> None:
        self._scans_in_flight = max(0, self._scans_in_flight - 1)
        self._add_uris_and_maybe_play([str(uri) for uri in uris])
        self.statusBar().showMessage(f"Added {len(uris)} file(s)", _STATUS_MESSAGE_MS)

    def _on_scan_failed(self, reason: str) -> None:
        self._scans_in_flight = max(0, self._scans_in_flight - 1)
        self.statusBar().showMessage(reason, _STATUS_MESSAGE_MS)

    def _save_playlist(self) -> None:
        items = self._queue.playlist.items()
        if not items:
            self.statusBar().showMessage("Playlist is empty — nothing to save", _STATUS_MESSAGE_MS)
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save playlist", "playlist.m3u8", _PLAYLIST_FILTER
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() not in (".m3u8", ".m3u"):
            path = path.with_suffix(".m3u8")
        try:
            m3u.save(
                path,
                [m3u.M3uEntry(uri=item.uri, title=item.title, duration=item.duration) for item in items],
            )
        except OSError as exc:
            self._show_error_message(f"Could not save playlist: {exc}")
            return
        self.statusBar().showMessage(f"Playlist saved — {path}", _STATUS_MESSAGE_MS)

    def _open_playlist(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Open playlist", "", _PLAYLIST_FILTER)
        if not path_str:
            return
        try:
            entries = m3u.load(Path(path_str))
        except OSError as exc:
            self._show_error_message(f"Could not open playlist: {exc}")
            return
        uris = [entry.uri for entry in entries]
        if not uris:
            self.statusBar().showMessage("Playlist contains no entries", _STATUS_MESSAGE_MS)
            return
        self._queue.load(uris)
        self._queue.play_index(0)

    def _rebuild_recent_menu(self) -> None:
        menu = self._recent_menu
        menu.clear()
        entries = self._recents.entries()
        if not entries:
            empty = QAction("No recent files", self)
            empty.setEnabled(False)
            menu.addAction(empty)
            return
        for uri in entries:
            action = QAction(title_for_uri(uri), self)
            action.setToolTip(uri)
            action.triggered.connect(lambda _checked=False, u=uri: self._open_recent(u))
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction("Clear List", self._recents.clear)

    def _open_recent(self, uri: str) -> None:
        self._queue.load([uri])
        self._queue.play_index(0)

    # ---------------------------------------------------------- drag and drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # Qt override
        urls = event.mimeData().urls()
        if urls:
            event.acceptProposedAction()
        self.handle_dropped_urls(urls)

    def handle_dropped_urls(self, urls) -> None:
        """Apply dropped URLs: local files are queued, folders scanned
        (recursively), remote URLs queued as-is. Playback starts if idle.

        Kept separate from :meth:`dropEvent` so it is testable without
        synthesising Qt drag events.
        """
        files: list[str] = []
        for url in urls:
            if url.isEmpty():
                continue
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.is_dir():
                    self._scan_folder_async(path, recursive=True)
                else:
                    files.append(str(path))
            else:
                files.append(url.toString())
        if files:
            self._add_uris_and_maybe_play(files)

    # ------------------------------------------------------------- UI actions
    def _step_volume(self, delta: int) -> None:
        self._controller.set_volume(self._controller.volume + delta)

    # ------------------------------------------------------------- dialogs
    def _show_settings(self) -> None:
        """Open (or raise) the settings dialog — non-modal, live-applying."""
        from app.ui.settings_dialog import SettingsDialog

        dialog = getattr(self, "_settings_dialog", None)
        if dialog is None:
            dialog = self._settings_dialog = SettingsDialog(
                self._settings, self._controller, self
            )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _show_media_info(self) -> None:
        """Open (or raise) the media information dialog — never blocking."""
        dialog = getattr(self, "_info_dialog", None)
        if dialog is None:
            dialog = self._info_dialog = MediaInfoDialog(self._controller, self)
        dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    # ------------------------------------------------------------- subtitles
    def _add_subtitle_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add subtitle file", "", _SUBTITLE_FILTER)
        if path:
            self._controller.add_subtitle_file(path)

    def _cycle_subtitles(self) -> None:
        selected = self._controller.cycle_subtitles()
        label = "Disabled" if selected is None else f"Track {selected}"
        self.statusBar().showMessage(f"Subtitles: {label}", _STATUS_MESSAGE_MS)

    def _nudge_subtitle_delay(self, delta: float) -> None:
        self._controller.nudge_subtitle_delay(delta)

    def _reset_subtitle_delay(self) -> None:
        self._controller.reset_subtitle_delay()

    def _on_subtitle_delay_changed(self, delay: float) -> None:
        self.statusBar().showMessage(f"Subtitle delay: {delay:+.2f} s", _STATUS_MESSAGE_MS)

    # ------------------------------------------------------------ audio tracks
    def _on_audio_track_action(self, action: QAction) -> None:
        track_id = action.data()
        self._controller.select_audio_track(track_id)

    def _cycle_audio_tracks(self) -> None:
        selected = self._controller.cycle_audio_tracks()
        label = "Disabled" if selected is None else f"Track {selected}"
        self.statusBar().showMessage(f"Audio: {label}", _STATUS_MESSAGE_MS)

    # ------------------------------------------------------------- audio sync
    def _nudge_audio_delay(self, delta: float) -> None:
        self._controller.nudge_audio_delay(delta)

    def _reset_audio_delay(self) -> None:
        self._controller.reset_audio_delay()

    def _on_audio_delay_changed(self, delay: float) -> None:
        self.statusBar().showMessage(f"Audio delay: {delay:+.2f} s", _STATUS_MESSAGE_MS)

    # ------------------------------------------------------------- about/misc
    def _show_about(self) -> None:
        """Open the About dialog (version, licence, third-party components)."""
        from app.ui.dialogs import AboutDialog

        dialog = getattr(self, "_about_dialog", None)
        if dialog is None:
            dialog = self._about_dialog = AboutDialog(self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_software_renderer(self) -> None:
        self._video_area.show_renderer_notice()

    # ------------------------------------------------------------ stream state
    def _on_buffering(self, percent: int | None) -> None:
        self._video_area.set_buffering(percent)

    def _on_stream_title(self, title: str) -> None:
        """ICY metadata arrived: reflect it in the window title and status bar."""
        self.setWindowTitle(f"{title} — Glint")
        self.statusBar().showMessage(f"Now playing: {title}", _STATUS_MESSAGE_MS)

    # ------------------------------------------------------------ video tracks
    def _on_video_track_action(self, action: QAction) -> None:
        track_id = action.data()
        self._controller.select_video_track(track_id)

    # -------------------------------------------------------- secondary subs
    def _on_secondary_track_action(self, action: QAction) -> None:
        track_id = action.data()
        self._controller.select_secondary_subtitle_track(track_id)

    # ------------------------------------------------------------ screenshots
    def _take_screenshot(self) -> None:
        path = self._controller.screenshot(self._screenshot_directory())
        if path is not None:
            self.statusBar().showMessage(f"Screenshot saved — {path}", _STATUS_MESSAGE_MS)
        else:
            self.statusBar().showMessage("Screenshot failed — details in the log", _STATUS_MESSAGE_MS)

    def _screenshot_directory(self) -> Path:
        """The user's Pictures/Glint folder when writable, else the config dir."""
        pictures = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        if pictures:
            candidate = Path(pictures) / "Glint"
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                logger.warning(
                    "cannot use the Pictures folder (%s); saving screenshots to the config dir",
                    candidate,
                )
        return config_dir() / "screenshots"

    def _toggle_playlist_panel(self) -> None:
        if self.isFullScreen():
            # In fullscreen the panel is chrome: shown on request, then
            # hidden again by the same idle auto-hide that manages the
            # control bar and the cursor.
            self._fs_playlist_visible = not self._fs_playlist_visible
            self._playlist_dock.setVisible(self._fs_playlist_visible)
            self._autohide.poke()
            return
        self._playlist_dock.setVisible(not self._playlist_dock.isVisible())

    def _on_repeat_action(self, action: QAction) -> None:
        mode = action.data()
        if isinstance(mode, RepeatMode):
            self._queue.set_repeat(mode)

    def _on_repeat_changed(self, mode: RepeatMode) -> None:
        for action in self._repeat_group.actions():
            data = action.data()
            action.setChecked(isinstance(data, RepeatMode) and data is mode)

    def _show_context_menu(self, global_pos: QPoint) -> None:
        controller = self._controller
        menu = QMenu(self)
        menu.addAction(
            self._shortcuts.display_text("Play / Pause", PlayerAction.PLAY_PAUSE),
            controller.toggle_play_pause,
        )
        menu.addAction("Stop", controller.stop)
        menu.addSeparator()
        self._populate_speed_menu(menu.addMenu("Speed"))
        menu.addSeparator()
        menu.addAction(
            self._shortcuts.display_text("Next", PlayerAction.NEXT_TRACK),
            lambda: self._queue.next(auto=False),
        )
        menu.addAction(
            self._shortcuts.display_text("Previous", PlayerAction.PREVIOUS_TRACK),
            self._queue.previous,
        )
        menu.addSeparator()
        menu.addAction(
            self._shortcuts.display_text("Fullscreen", PlayerAction.FULLSCREEN),
            self.toggle_fullscreen,
        )
        mute_action = menu.addAction(
            self._shortcuts.display_text("Mute", PlayerAction.MUTE), controller.toggle_mute
        )
        mute_action.setCheckable(True)
        mute_action.setChecked(controller.muted)
        menu.addSeparator()
        menu.addAction(
            self._shortcuts.display_text("Media Information…", PlayerAction.MEDIA_INFO),
            self._show_media_info,
        )
        menu.exec(global_pos)

    # -------------------------------------------------------------- fullscreen
    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        if self.isFullScreen():
            return
        self._was_maximized = self.isMaximized()
        self._playlist_dock_was_visible = self._playlist_dock.isVisible()
        self._fs_playlist_visible = False
        self.menuBar().hide()
        self._playlist_dock.hide()
        self._controls.show()
        self.showFullScreen()
        self._controls.set_fullscreen_active(True)
        self._autohide.start()

    def _exit_fullscreen(self) -> None:
        if not self.isFullScreen():
            return
        self._autohide.stop()
        if self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.menuBar().show()
        self._playlist_dock.setVisible(self._playlist_dock_was_visible)
        self._controls.show()
        self._controls.set_fullscreen_active(False)
        self._video_area.set_cursor_hidden(False)

    def _exit_fullscreen_if_active(self) -> None:
        if self.isFullScreen():
            self._exit_fullscreen()

    def _on_user_activity(self) -> None:
        if self.isFullScreen():
            self._autohide.poke()

    def _on_chrome_hidden(self) -> None:
        if not self.isFullScreen():
            return
        self._controls.hide()
        self._playlist_dock.hide()
        self._video_area.set_cursor_hidden(True)

    def _on_chrome_shown(self) -> None:
        self._controls.show()
        self._playlist_dock.setVisible(self._fs_playlist_visible)
        self._video_area.set_cursor_hidden(False)

    # ----------------------------------------------------------- controller → UI
    def _on_state_changed(self, state: PlaybackState) -> None:
        self._controls.set_playback_state(state)
        # Query the *live* state rather than the signal payload: the queue may
        # already have advanced to the next item (LOADING) before this slot
        # runs, and we must not flash the idle overlay in between.
        live = self._controller.state
        idle = live is PlaybackState.IDLE
        ended = live is PlaybackState.ENDED
        self._video_area.set_idle_visible(idle or ended)
        if idle:
            self._video_area.set_idle_message("Nothing playing", "Open a media file (Ctrl+O)")
        elif ended:
            self._video_area.set_idle_message(
                "Playback finished", "Open more files or review the playlist (Ctrl+L)"
            )
        if idle:
            self.setWindowTitle("Glint")
            self._controls.set_position(0.0)
            self._controls.set_duration(None)

    def _on_media_loaded(self, info: MediaInfo) -> None:
        self.setWindowTitle(f"{info.title} — Glint")
        self._controls.set_speed(self._controller.speed)
        dialog = getattr(self, "_info_dialog", None)
        if dialog is not None and dialog.isVisible():
            dialog.refresh()
        try:
            self._recents.add(info.uri)
        except Exception:
            logger.exception("could not record recent file")

    def _on_error(self, error: PlayerError) -> None:
        logger.warning("user-facing error: %s", error)
        self._show_error_message(error.message)

    def _show_error_message(self, message: str) -> None:
        self._error_banner.setText(f"Playback problem — {message}")
        self._error_banner.show()
        self._banner_timer.start(_ERROR_BANNER_MS)

    # --------------------------------------------------------------- lifecycle
    def closeEvent(self, event) -> None:  # Qt override
        logger.debug("main window closing")
        self._autohide.stop()
        try:
            self._controller.stop()
        except Exception:
            logger.exception("stop on close failed")
        try:
            release = getattr(self._surface, "release", None)
            if release is not None:
                release()  # free the render context before the engine dies
        except Exception:
            logger.exception("video surface release failed")
        event.accept()
