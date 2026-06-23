from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from threading import Event

import pytest
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QColorDialog, QFileDialog
from pytestqt.qtbot import QtBot

import activity_map.widgets as widgets
from activity_map.geo import ProjectedPoint, ScreenPoint, Viewport
from activity_map.loading import PreparedLoad
from activity_map.models import (
    ActivityTrack,
    LoadReport,
    LoadWarning,
    TrackPoint,
)
from activity_map.render import prepare_tracks
from activity_map.tiles import TileCoordinate
from activity_map.widgets import MainWindow, MapCanvas, gesture_transform


@pytest.fixture(autouse=True)
def offscreen_qt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("ACTIVITY_MAP_DISABLE_TILES", "1")
    monkeypatch.setenv("ACTIVITY_MAP_SETTINGS_PATH", str(tmp_path / "settings.json"))


def synthetic_track() -> ActivityTrack:
    return ActivityTrack(
        activity_id="interactive",
        name="Interactive Track",
        source_file=Path("interactive.json"),
        points=(
            TrackPoint(52.50, 13.40),
            TrackPoint(52.51, 13.41),
            TrackPoint(52.52, 13.42),
        ),
    )


def png_bytes() -> bytes:
    pixmap = QPixmap(4, 4)
    pixmap.fill(QColor("#abcdef"))
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert pixmap.save(buffer, "PNG")
    buffer.close()
    return data.data()


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


def test_canvas_mouse_navigation_and_resize(qtbot: QtBot) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 500)
    canvas.show()
    qtbot.waitExposed(canvas)
    original = canvas.viewport

    canvas.mousePressEvent(None)
    canvas.mouseMoveEvent(None)
    canvas.mouseReleaseEvent(None)
    canvas.mouseDoubleClickEvent(None)
    canvas.wheelEvent(None)
    canvas.mouseMoveEvent(
        mouse_event(
            QMouseEvent.Type.MouseMove,
            QPointF(20, 20),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
        )
    )
    canvas.mousePressEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(100, 100),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseMoveEvent(
        mouse_event(
            QMouseEvent.Type.MouseMove,
            QPointF(130, 120),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    assert canvas.viewport.center != original.center
    canvas.mouseReleaseEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(130, 120),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    assert canvas._last_drag_pos is None
    assert canvas._gesture_pixmap is None

    zoom_before = canvas.viewport.zoom
    wheel_in = QWheelEvent(
        QPointF(200, 200),
        QPointF(200, 200),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    canvas.wheelEvent(wheel_in)
    assert canvas.viewport.zoom > zoom_before
    assert canvas._gesture_pixmap is not None
    wheel_out = QWheelEvent(
        QPointF(200, 200),
        QPointF(200, 200),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    canvas.wheelEvent(wheel_out)
    canvas.finish_gesture()

    canvas.set_tracks((synthetic_track(),))
    moved = canvas.viewport.pan(100, 100)
    canvas.viewport = moved
    canvas.mouseDoubleClickEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonDblClick,
            QPointF(200, 200),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    assert canvas.viewport.center != moved.center
    assert canvas.viewport.width == canvas.width()
    assert canvas.viewport.height == canvas.height()


def test_gesture_transform_maps_source_center_to_target_view(
    qtbot: QtBot,
) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    source = Viewport(ProjectedPoint(0.5, 0.5), 1_000.0, 800, 600)
    target = source.pan(20.0, 10.0).zoom_at(
        1.2,
        ScreenPoint(400.0, 300.0),
    )

    mapped = gesture_transform(source, target).map(400.0, 300.0)
    expected = target.world_to_screen(source.center)

    assert mapped[0] == pytest.approx(expected.x)
    assert mapped[1] == pytest.approx(expected.y)


def test_canvas_tile_cache_and_future_paths(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    coordinate = TileCoordinate(1, 0, 0)
    data = png_bytes()

    canvas.tile_pixmaps[coordinate] = QPixmap(2, 2)
    assert canvas._tile_pixmap(coordinate) is canvas.tile_pixmaps[coordinate]
    canvas.tile_pixmaps.clear()
    monkeypatch.setattr(canvas.tile_cache, "load_cached_tile", lambda _: None)
    assert canvas._tile_pixmap(coordinate) is None
    monkeypatch.setattr(canvas.tile_cache, "load_cached_tile", lambda _: b"invalid")
    assert canvas._tile_pixmap(coordinate) is None
    monkeypatch.setattr(canvas.tile_cache, "load_cached_tile", lambda _: data)
    assert canvas._tile_pixmap(coordinate) is not None

    canvas.pending_tiles.add(coordinate)
    canvas._request_tile(coordinate)
    canvas.pending_tiles.clear()
    submitted: list[TileCoordinate] = []

    class ImmediateExecutor:
        def submit(self, operation: object, selected: TileCoordinate) -> Future[bytes]:
            submitted.append(selected)
            future: Future[bytes] = Future()
            future.set_result(data)
            return future

    canvas.tile_executor.shutdown(wait=False, cancel_futures=True)
    canvas.tile_executor = ImmediateExecutor()  # type: ignore[assignment]
    canvas._request_tile(coordinate)
    assert submitted == [coordinate]
    assert coordinate in canvas.tile_pixmaps

    missing: Future[bytes | None] = Future()
    missing.set_result(None)
    canvas.pending_tiles.add(coordinate)
    canvas._emit_tile_result(coordinate, missing)
    assert coordinate not in canvas.pending_tiles

    failed: Future[bytes | None] = Future()
    failed.set_exception(OSError("offline"))
    canvas.pending_tiles.add(coordinate)
    canvas._emit_tile_result(coordinate, failed)
    assert coordinate not in canvas.pending_tiles

    callback_future: Future[bytes | None] = Future()
    callback_future.set_result(None)
    canvas.pending_tiles.add(coordinate)
    canvas._tile_result_callback(coordinate)(callback_future)
    assert coordinate not in canvas.pending_tiles
    canvas._store_tile(coordinate, b"invalid")


def test_canvas_renders_tiles_markers_lines_names_and_attribution(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 500)
    canvas.set_tracks((synthetic_track(),))
    canvas.set_track_names_visible(True)
    canvas.set_tile_layer_enabled(True)
    coordinate = TileCoordinate(0, 0, 0)
    tile = QPixmap(8, 8)
    tile.fill(QColor("#123456"))
    canvas.tile_pixmaps[coordinate] = tile
    monkeypatch.setattr(widgets, "visible_tiles", lambda _: (coordinate,))

    canvas.viewport = Viewport(ProjectedPoint(0.5, 0.5), 1_000, 800, 500)
    broad = canvas.render_to_pixmap()
    assert not broad.isNull()

    canvas.viewport = Viewport(ProjectedPoint(0.5, 0.5), 1_000_000, 800, 500)
    detailed = canvas.render_to_pixmap()
    assert not detailed.isNull()

    canvas.set_track_opacity(0)
    canvas.set_track_color(QColor())
    canvas.set_tile_layer_enabled(False)
    without_layers = canvas.render_to_pixmap()
    assert not without_layers.isNull()


def test_main_window_dialogs_status_and_restore_paths(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "tracks"
    selected.mkdir()
    window = MainWindow()
    qtbot.addWidget(window)

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args: "",
    )
    window.choose_directory()
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args: str(selected),
    )
    window.choose_directory()
    qtbot.waitUntil(lambda: window.settings.last_track_directory == str(selected))
    assert window.settings.last_track_directory == str(selected)

    monkeypatch.setattr(
        QColorDialog,
        "getColor",
        lambda *args: QColor(),
    )
    previous = window.canvas.track_color
    window.choose_track_color()
    assert window.canvas.track_color == previous
    monkeypatch.setattr(
        QColorDialog,
        "getColor",
        lambda *args: QColor("#654321"),
    )
    window.choose_track_color()
    assert window.settings.track_color == "#654321"

    warning_report = LoadReport(
        root=selected,
        files_read=1,
        tracks=(),
        warnings=(LoadWarning(selected / "bad.json", "bad"),),
    )
    monkeypatch.setattr(
        widgets,
        "load_and_prepare_directory",
        lambda *_args, **_kwargs: PreparedLoad(warning_report, ()),
    )
    window.load_path(selected)
    qtbot.waitUntil(lambda: window.report == warning_report)
    assert "files skipped" in window.warning_label.text()

    issue_track = ActivityTrack(
        activity_id="issue",
        name="Issue",
        source_file=selected / "issue.json",
        points=(TrackPoint(1, 1),),
        validation_messages=("issue",),
    )
    issue_report = LoadReport(selected, 1, (issue_track,), ())
    monkeypatch.setattr(
        widgets,
        "load_and_prepare_directory",
        lambda *_args, **_kwargs: PreparedLoad(issue_report, ()),
    )
    window.load_path(selected)
    qtbot.waitUntil(lambda: window.report == issue_report)
    assert window.warning_label.text() == "1 track validation issues"

    window.settings.last_track_directory = None
    window.load_last_directory()
    window.settings.last_track_directory = str(tmp_path / "missing")
    window.load_last_directory()
    window.settings.last_track_directory = str(selected)
    window.load_last_directory()
    window.closeEvent(None)


def test_main_window_load_path_is_non_blocking(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    report = LoadReport(tmp_path, 0, (), ())

    def slow_load(*_args: object, **_kwargs: object) -> PreparedLoad:
        started.set()
        assert release.wait(timeout=2)
        return PreparedLoad(report, ())

    monkeypatch.setattr(widgets, "load_and_prepare_directory", slow_load)
    window = MainWindow()
    qtbot.addWidget(window)

    window.load_path(tmp_path)

    assert started.wait(timeout=1)
    assert window.report is None
    assert window.status_label.text().startswith("Loading ")
    release.set()
    qtbot.waitUntil(lambda: window.report == report)


def test_duplicate_load_request_does_not_queue_a_second_job(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    calls = 0
    report = LoadReport(tmp_path, 0, (), ())

    def slow_load(*_args: object, **_kwargs: object) -> PreparedLoad:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return PreparedLoad(report, ())

    monkeypatch.setattr(widgets, "load_and_prepare_directory", slow_load)
    window = MainWindow()
    qtbot.addWidget(window)

    window.load_path(tmp_path)
    assert started.wait(timeout=1)
    window.load_path(tmp_path)

    assert calls == 1
    assert window.status_label.text().startswith("Still loading ")
    release.set()
    qtbot.waitUntil(lambda: window.report == report)


def test_partial_load_progress_installs_tracks_before_completion(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = Event()
    track = synthetic_track()
    report = LoadReport(tmp_path, 1, (track,), ())
    prepared = prepare_tracks((track,))

    def progressive_load(
        _path: Path,
        _loader_workers: int,
        _preparation_workers: int,
        progress: object,
    ) -> PreparedLoad:
        assert callable(progress)
        progress(PreparedLoad(report, prepared))
        assert release.wait(timeout=2)
        return PreparedLoad(report, prepared)

    monkeypatch.setattr(widgets, "load_and_prepare_directory", progressive_load)
    window = MainWindow()
    qtbot.addWidget(window)

    window.load_path(tmp_path)
    qtbot.waitUntil(lambda: len(window.canvas.render_tracks) == 1)

    assert window.report is None
    assert window.status_label.text().startswith("Loading... 1 tracks")
    release.set()
    qtbot.waitUntil(lambda: window.report == report)
    assert len(window.canvas.render_tracks) == 1
