from __future__ import annotations

import json
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from activity_map.widgets import MainWindow, MapCanvas


def configure_gui_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("ACTIVITY_MAP_DISABLE_TILES", "1")
    monkeypatch.setenv("ACTIVITY_MAP_SETTINGS_PATH", str(settings_path))
    return settings_path


def write_synthetic_activity(
    path: Path,
    activity_id: int,
    *,
    point_count: int = 6,
    latitude: float = 52.0,
    longitude: float = 13.0,
) -> None:
    polyline = [
        {
            "lat": latitude + activity_id * 0.002 + index * 0.0002,
            "lon": longitude + activity_id * 0.002 + index * 0.0002,
            "timestamp": 1_735_689_600 + activity_id * 3_600 + index * 120,
        }
        for index in range(point_count)
    ]
    payload = {
        "summary": {
            "activityId": f"synthetic-{activity_id}",
            "activityName": f"Synthetic Track {activity_id}",
        },
        "details": {"geoPolylineDTO": {"polyline": polyline}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_activity_directory(
    root: Path,
    *,
    track_count: int,
    point_count: int = 6,
) -> Path:
    directory = root / "synthetic-activities"
    directory.mkdir()
    for activity_id in range(track_count):
        write_synthetic_activity(
            directory / f"activity-{activity_id:04d}.json",
            activity_id,
            point_count=point_count,
        )
    return directory


def make_malformed_activity_directory(root: Path) -> Path:
    directory = root / "malformed-activities"
    directory.mkdir()
    (directory / "broken.json").write_text("{not valid json", encoding="utf-8")
    (directory / "empty-track.json").write_text(
        json.dumps({"summary": {"activityId": "empty", "activityName": "Empty"}}),
        encoding="utf-8",
    )
    return directory


def launch_window(qtbot: QtBot) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 680)
    window.show()
    qtbot.waitExposed(window)
    return window


def select_directory_with_dialog(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(directory),
    )


def wait_for_completed_load(
    qtbot: QtBot,
    window: MainWindow,
    expected_tracks: int,
) -> None:
    qtbot.waitUntil(
        lambda: (
            window.report is not None and window.total_track_count == expected_tracks
        ),
        timeout=10_000,
    )


def mouse_event(
    event_type: QMouseEvent.Type,
    position: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        position,
        position,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def drag_canvas(canvas: MapCanvas, start: QPointF, end: QPointF) -> None:
    canvas.mousePressEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseMoveEvent(
        mouse_event(
            QMouseEvent.Type.MouseMove,
            end,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseReleaseEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonRelease,
            end,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )


def wheel_canvas(canvas: MapCanvas, position: QPointF, delta: int) -> None:
    canvas.wheelEvent(
        QWheelEvent(
            position,
            position,
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )
