import json
import os
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from activity_map.app import main, parse_args
from activity_map.widgets import MainWindow


@pytest.fixture(autouse=True)
def offscreen_qt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("ACTIVITY_MAP_DISABLE_TILES", "1")


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


def test_main_window_loads_directory_and_renders_nonblank_map(
    tmp_path: Path, qtbot: QtBot
) -> None:
    write_activity(tmp_path / "activity.json")
    window = MainWindow()
    qtbot.addWidget(window)

    window.load_path(tmp_path)
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


def test_main_window_updates_map_layer_controls(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.canvas.set_tile_opacity(45)
    window.canvas.set_tile_layer_enabled(False)

    assert window.canvas.tile_opacity == 0.45
    assert window.canvas.tile_layer_enabled is False

    window.canvas.set_tile_opacity(0)

    assert window.canvas.tile_opacity == 0.0


def test_main_smoke_test_returns_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_activity(tmp_path / "activity.json")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    assert main([str(tmp_path), "--smoke-test"]) == 0
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
