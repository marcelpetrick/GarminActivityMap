import json
import os
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor
from pytestqt.qtbot import QtBot

from activity_map import __version__
from activity_map.app import main, parse_args
from activity_map.widgets import MainWindow


@pytest.fixture(autouse=True)
def offscreen_qt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("ACTIVITY_MAP_DISABLE_TILES", "1")
    monkeypatch.setenv(
        "ACTIVITY_MAP_SETTINGS_PATH",
        str(tmp_path / "settings.json"),
    )


def write_activity(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "summary": {"activityId": 1, "activityName": "Synthetic"},
                "details": {
                    "geoPolylineDTO": {
                        "polyline": [
                            {"lat": 52.50, "lon": 13.40},
                            {"lat": 52.51, "lon": 13.41},
                            {"lat": 52.52, "lon": 13.42},
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_parse_args_accepts_directory_and_smoke_flag(tmp_path: Path) -> None:
    args = parse_args([str(tmp_path), "--smoke-test"])

    assert args.directory == tmp_path
    assert args.smoke_test is True


def test_main_window_title_includes_version(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == f"Garmin Activity Map {__version__}"


def test_main_window_loads_directory_and_renders_nonblank_map(
    tmp_path: Path, qtbot: QtBot
) -> None:
    write_activity(tmp_path / "activity.json")
    window = MainWindow()
    qtbot.addWidget(window)

    window.load_path(tmp_path)
    qtbot.waitUntil(lambda: window.report is not None)
    window.resize(960, 640)
    window.show()
    qtbot.waitExposed(window)
    pixmap = window.canvas.render_to_pixmap()
    image = pixmap.toImage()

    assert window.report is not None
    assert len(window.report.tracks) == 1
    assert window.report.point_count == 3
    sampled_colors = {
        image.pixelColor(x, y).name()
        for x in range(0, image.width(), max(image.width() // 5, 1))
        for y in range(0, image.height(), max(image.height() // 5, 1))
    }
    assert len(sampled_colors) > 1
    assert window.canvas.render_tracks[0].segments


def test_main_window_updates_map_layer_controls(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.canvas.set_tile_opacity(45)
    window.canvas.set_tile_layer_enabled(False)

    assert window.canvas.tile_opacity == 0.45
    assert window.canvas.tile_layer_enabled is False

    window.canvas.set_tile_opacity(0)

    assert window.canvas.tile_opacity == 0.0


def test_main_window_updates_track_color(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.canvas.set_track_color(QColor("#ff00aa"))
    window.update_track_color_button()

    assert window.canvas.track_color.name() == "#ff00aa"
    assert "#ff00aa" in window.track_color_button.styleSheet()
    assert "#ff00aa" in window.track_legend_swatch.styleSheet()


def test_side_panel_sliders_have_room_for_their_handles(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.opacity_slider.minimumHeight() == 24
    assert window.map_opacity_slider.minimumHeight() == 24


def test_main_window_toggles_track_names(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.canvas.track_names_visible is False

    window.track_names_checkbox.setChecked(True)

    assert window.canvas.track_names_visible is True


def test_main_window_persists_runtime_preferences(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_path = tmp_path / "preferences.json"
    monkeypatch.setenv("ACTIVITY_MAP_SETTINGS_PATH", str(settings_path))
    window = MainWindow()
    qtbot.addWidget(window)

    window.opacity_slider.setValue(44)
    window.track_names_checkbox.setChecked(True)
    window.map_opacity_slider.setValue(33)
    window.map_layer_checkbox.setChecked(False)
    window.canvas.set_track_color(QColor("#123456"))
    window.settings.track_color = "#123456"
    window.save_settings()

    restored = MainWindow()
    qtbot.addWidget(restored)

    assert restored.canvas.track_opacity == 0.44
    assert restored.canvas.track_names_visible is True
    assert restored.canvas.tile_opacity == 0.33
    assert restored.canvas.tile_layer_enabled is False
    assert restored.canvas.track_color.name() == "#123456"


def test_main_smoke_test_returns_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_activity(tmp_path / "activity.json")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    assert main([str(tmp_path), "--smoke-test"]) == 0
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
