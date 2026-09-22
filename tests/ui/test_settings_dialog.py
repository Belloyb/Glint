"""UI integration tests for the settings dialog and live application."""

from __future__ import annotations

import json
import os

import pytest

from app.core.models import PlaybackState
from app.core.settings import AppSettings
from tests.ui.conftest import destroy_application, pump

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="requires a display with OpenGL (use xvfb-run on headless Linux)",
)


@pytest.fixture
def app(qtbot, qapp, tmp_path):
    from app.application import Application

    application = Application(
        qapp,
        mpv_options={"ao": "null"},
        queue_seed=42,
        settings_path=tmp_path / "settings.json",
    )
    window = application.window
    window.show()
    window.activateWindow()
    qapp.processEvents()
    yield application
    dialog = getattr(window, "_settings_dialog", None)
    if dialog is not None:
        dialog.close()
    destroy_application(application, qapp)


def _open_dialog(app) -> object:
    app.window._show_settings()
    dialog = app.window._settings_dialog
    assert dialog.isVisible()
    return dialog


def test_dialog_pages_and_initial_values(app, qapp):
    dialog = _open_dialog(app)
    assert dialog._categories.count() == 5
    assert dialog._volume_slider.value() == 100
    assert dialog._autoplay_check.isChecked() is True
    assert dialog._hwdec_check.isChecked() is True
    # audio devices were enumerated (>= "auto")
    assert dialog._device_combo.count() >= 1


def test_volume_change_applies_live_and_persists(app, qapp, qtbot):
    dialog = _open_dialog(app)
    dialog._volume_slider.setValue(37)
    qapp.processEvents()

    assert app.controller.volume == 37  # applied to the engine live
    data = json.loads(app.settings.path.read_text(encoding="utf-8"))
    assert data["playback"]["default_volume"] == 37  # persisted


def test_theme_switch_applies_live(app, qapp, qtbot):
    dialog = _open_dialog(app)
    light_bg = "#f5f6f8"
    dialog._theme_combo.setCurrentIndex(1)  # Light
    qapp.processEvents()
    assert light_bg in qapp.styleSheet()

    dialog._theme_combo.setCurrentIndex(0)  # back to Dark
    qapp.processEvents()
    assert light_bg not in qapp.styleSheet()


def test_autoplay_off_opens_paused(app, qapp, qtbot, sample_media):
    dialog = _open_dialog(app)
    dialog._autoplay_check.setChecked(False)
    qapp.processEvents()
    assert app.controller.autoplay_on_open is False

    app.controller.open(str(sample_media))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PAUSED), (
        f"expected paused load, state={app.controller.state}"
    )


def test_subtitle_defaults_apply_to_engine(app, qapp, qtbot):
    from app.core.subtitles import mpv_color_to_rgb

    dialog = _open_dialog(app)
    dialog._size_spin.setValue(60)
    dialog._delay_spin.setValue(-0.5)
    qapp.processEvents()

    appearance = app.controller.subtitle_appearance
    assert appearance.size == 60.0
    assert appearance.position == 100.0  # untouched settings keep engine value
    assert app.controller.subtitle_delay == pytest.approx(-0.5, abs=1e-6)
    assert mpv_color_to_rgb(appearance.color) == "#FFFFFF"


def test_hwdec_toggle_applies_to_engine(app, qapp, qtbot):
    dialog = _open_dialog(app)
    assert app.controller.hardware_decoding is True
    dialog._hwdec_check.setChecked(False)
    qapp.processEvents()
    assert app.controller.hardware_decoding is False
    dialog._hwdec_check.setChecked(True)
    qapp.processEvents()
    assert app.controller.hardware_decoding is True


def test_deinterlace_toggle_applies_to_engine(app, qapp, qtbot):
    dialog = _open_dialog(app)
    dialog._deinterlace_check.setChecked(True)
    qapp.processEvents()
    assert app.controller.deinterlace is True
    dialog._deinterlace_check.setChecked(False)
    qapp.processEvents()
    assert app.controller.deinterlace is False


def test_audio_device_selection_applies(app, qapp, qtbot):
    dialog = _open_dialog(app)
    devices = app.controller.audio_devices()
    assert ("auto", "Autoselect device") in devices or any(d[0] == "auto" for d in devices)

    # Select a non-auto device if one exists; otherwise select "auto".
    target = next((d for d in devices if d[0] != "auto"), devices[0])
    index = dialog._device_combo.findData(target[0])
    dialog._device_combo.setCurrentIndex(index)
    qapp.processEvents()
    assert app.controller.audio_device == target[0]


def test_sub_auto_load_toggle_changes_engine_behaviour(app, qapp, qtbot, subtitle_mkv):
    dialog = _open_dialog(app)
    dialog._autoload_check.setChecked(False)
    qapp.processEvents()

    app.controller.open(str(subtitle_mkv))
    assert pump(qapp, lambda: app.controller.state is PlaybackState.PLAYING)
    assert pump(qapp, lambda: len(app.controller.media_details().tracks) >= 2)

    externals = [t for t in app.controller.subtitle_tracks() if t.is_external]
    assert externals == [], "sidecar subtitles should not auto-load when disabled"


def test_reset_to_defaults(app, qapp, qtbot):
    dialog = _open_dialog(app)
    dialog._volume_slider.setValue(11)
    qapp.processEvents()
    assert app.settings.settings.playback.default_volume == 11

    dialog._reset()
    qapp.processEvents()
    assert app.settings.settings == AppSettings()
    assert dialog._volume_slider.value() == 100
    assert app.controller.volume == 100


def test_show_playlist_at_start_is_honoured(qtbot, qapp, tmp_path):
    from app.application import Application

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "interface": {"show_playlist_at_start": False},
            }
        ),
        encoding="utf-8",
    )
    application = Application(
        qapp,
        mpv_options={"ao": "null"},
        settings_path=settings_path,
    )
    window = application.window
    window.show()
    qapp.processEvents()
    try:
        assert not window._playlist_dock.isVisible()
    finally:
        destroy_application(application, qapp)
