from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import Future
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event

import pytest
from PyQt6.QtCore import QBuffer, QByteArray, QDate, QIODevice, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QColorDialog, QFileDialog
from pytestqt.qtbot import QtBot

import activity_map.widgets as widgets
from activity_map.geo import ProjectedPoint, ScreenPoint, Viewport
from activity_map.loader import LoadCancelled
from activity_map.loading import PreparedLoad
from activity_map.models import (
    ActivityTrack,
    LoadReport,
    LoadWarning,
    TrackPoint,
)
from activity_map.render import ProjectedBounds, prepare_tracks
from activity_map.replay import (
    REPLAY_DURATION_MILLISECONDS,
    REPLAY_TICK_MILLISECONDS,
)
from activity_map.settings import SettingsStore
from activity_map.spatial import TrackSpatialIndex
from activity_map.tiles import MIN_CACHE_SECONDS, TileCoordinate
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


def test_appended_batches_keep_a_user_adjusted_viewport(qtbot: QtBot) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 500)
    first = ActivityTrack(
        activity_id="first",
        name="First",
        source_file=Path("first.json"),
        points=(
            TrackPoint(52.50, 13.40),
            TrackPoint(52.51, 13.41),
            TrackPoint(52.52, 13.42),
        ),
    )
    second = ActivityTrack(
        activity_id="second",
        name="Second",
        source_file=Path("second.json"),
        points=(
            TrackPoint(-33.80, 151.20),
            TrackPoint(-33.81, 151.21),
            TrackPoint(-33.82, 151.22),
        ),
    )
    canvas.set_prepared_tracks((first,), prepare_tracks((first,)))
    fitted = canvas.viewport

    canvas.append_prepared_tracks((second,), prepare_tracks((second,)))
    assert canvas.viewport != fitted

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
            QPointF(140, 130),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseReleaseEvent(
        mouse_event(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(140, 130),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    panned = canvas.viewport
    assert canvas.viewport_adjusted_by_user

    third = ActivityTrack(
        activity_id="third",
        name="Third",
        source_file=Path("third.json"),
        points=(
            TrackPoint(48.85, 2.35),
            TrackPoint(48.86, 2.36),
            TrackPoint(48.87, 2.37),
        ),
    )
    canvas.append_prepared_tracks((third,), prepare_tracks((third,)))
    assert canvas.viewport == panned
    assert len(canvas.render_tracks) == 3

    canvas.reset_view()
    assert not canvas.viewport_adjusted_by_user
    assert canvas.viewport != panned


class CountingSpatialIndex:
    def __init__(self, index: TrackSpatialIndex) -> None:
        self.index = index
        self.queries: list[ProjectedBounds] = []

    def query(self, bounds: ProjectedBounds) -> tuple[int, ...]:
        self.queries.append(bounds)
        return self.index.query(bounds)


def test_empty_canvas_paints_without_querying_the_spatial_index(
    qtbot: QtBot,
) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    counting = CountingSpatialIndex(canvas.spatial_index)
    canvas.spatial_index = counting  # type: ignore[assignment]

    canvas.render_to_pixmap()
    assert counting.queries == []
    assert canvas.visible_track_count == 0

    track = synthetic_track()
    canvas.set_prepared_tracks((track,), prepare_tracks((track,)))
    counting = CountingSpatialIndex(canvas.spatial_index)
    canvas.spatial_index = counting  # type: ignore[assignment]
    canvas.track_names_visible = True

    canvas.render_to_pixmap()
    assert len(counting.queries) == 1
    assert canvas.visible_track_count == 1


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


def test_canvas_bounds_in_memory_tile_pixmaps(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    monkeypatch.setattr(widgets, "MAX_MEMORY_TILE_PIXMAPS", 2)
    coordinates = [TileCoordinate(2, x, 0) for x in range(3)]

    for coordinate in coordinates:
        canvas._store_tile(coordinate, png_bytes())

    assert list(canvas.tile_pixmaps) == coordinates[1:]

    monkeypatch.setattr(widgets, "MAX_TILE_STATE_ENTRIES", 2)
    for coordinate in coordinates:
        canvas._remember_tile_state(canvas.unusable_tiles, coordinate)
    assert list(canvas.unusable_tiles) == coordinates[1:]


def test_canvas_displays_stale_tile_while_requesting_one_refresh(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    canvas.tile_cache.root = tmp_path
    canvas.set_tile_layer_enabled(True)
    coordinate = TileCoordinate(0, 0, 0)
    path = canvas.tile_cache.tile_path(coordinate)
    path.parent.mkdir(parents=True)
    path.write_bytes(png_bytes())
    stale_time = time.time() - MIN_CACHE_SECONDS - 60
    os.utime(path, (stale_time, stale_time))
    requested: list[TileCoordinate] = []
    monkeypatch.setattr(widgets, "visible_tiles", lambda _: (coordinate,))
    monkeypatch.setattr(canvas, "_request_tile", requested.append)

    canvas.render_to_pixmap()
    canvas.render_to_pixmap()

    assert coordinate in canvas.tile_pixmaps
    assert requested == [coordinate]


def test_unreadable_tiles_are_discarded_and_not_requested_again(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    canvas.tile_cache.root = tmp_path
    coordinate = TileCoordinate(2, 1, 1)
    path = canvas.tile_cache.tile_path(coordinate)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"truncated")

    assert canvas._tile_pixmap(coordinate) is None
    assert not path.exists()

    submitted: list[TileCoordinate] = []

    class RecordingExecutor:
        def submit(self, operation: object, selected: TileCoordinate) -> Future[bytes]:
            submitted.append(selected)
            future: Future[bytes] = Future()
            future.set_result(b"still not an image")
            return future

    canvas.tile_executor.shutdown(wait=False, cancel_futures=True)
    canvas.tile_executor = RecordingExecutor()  # type: ignore[assignment]
    canvas._request_tile(coordinate)
    assert submitted == [coordinate]
    assert coordinate in canvas.unusable_tiles
    assert coordinate not in canvas.pending_tiles

    canvas._request_tile(coordinate)
    assert submitted == [coordinate]


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


def test_reload_keeps_previous_tracks_visible_until_new_data_arrives(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = Event()
    previous = synthetic_track()
    replacement = ActivityTrack(
        activity_id="replacement",
        name="Replacement Track",
        source_file=Path("replacement.json"),
        points=(
            TrackPoint(48.85, 2.35),
            TrackPoint(48.86, 2.36),
            TrackPoint(48.87, 2.37),
        ),
    )
    report = LoadReport(tmp_path, 1, (replacement,), ())
    prepared = prepare_tracks((replacement,))

    def blocking_load(
        _path: Path,
        _loader_workers: int,
        _preparation_workers: int,
        _progress: object,
        _cancelled: object,
    ) -> PreparedLoad:
        assert release.wait(timeout=5)
        return PreparedLoad(report, prepared)

    monkeypatch.setattr(widgets, "load_and_prepare_directory", blocking_load)
    window = MainWindow()
    qtbot.addWidget(window)
    window.canvas.set_prepared_tracks((previous,), prepare_tracks((previous,)))

    window.load_path(tmp_path)

    assert [track.activity_id for track in window.canvas.render_tracks] == [
        "interactive"
    ]
    assert window.status_label.text().startswith("Loading ")

    release.set()
    qtbot.waitUntil(lambda: window.report == report)
    assert [track.activity_id for track in window.canvas.render_tracks] == [
        "replacement"
    ]


def test_synchronous_loads_replace_the_previous_dataset(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = synthetic_track()
    second = ActivityTrack(
        activity_id="second",
        name="Second Track",
        source_file=Path("second.json"),
        points=(
            TrackPoint(-33.80, 151.20),
            TrackPoint(-33.81, 151.21),
            TrackPoint(-33.82, 151.22),
        ),
    )
    loads = iter(
        (
            PreparedLoad(
                LoadReport(tmp_path, 1, (first,), ()), prepare_tracks((first,))
            ),
            PreparedLoad(
                LoadReport(tmp_path, 1, (second,), ()), prepare_tracks((second,))
            ),
        )
    )
    monkeypatch.setattr(
        widgets,
        "load_and_prepare_directory",
        lambda _path: next(loads),
    )
    window = MainWindow()
    qtbot.addWidget(window)

    window.load_path_sync(tmp_path)
    assert [track.activity_id for track in window.canvas.render_tracks] == [
        "interactive"
    ]

    window.load_path_sync(tmp_path)
    assert [track.activity_id for track in window.canvas.render_tracks] == ["second"]


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
        _cancelled: object,
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


def test_new_directory_cancels_the_running_load(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_started = Event()
    first_cancelled = Event()
    second_report = LoadReport(second, 0, (), ())

    def cooperative_load(
        path: Path,
        _loader_workers: int,
        _preparation_workers: int,
        _progress: object,
        cancelled: Callable[[], bool],
    ) -> PreparedLoad:
        if path == first:
            first_started.set()
            while not cancelled():
                time.sleep(0.001)
            first_cancelled.set()
            raise LoadCancelled("superseded")
        return PreparedLoad(second_report, ())

    monkeypatch.setattr(widgets, "load_and_prepare_directory", cooperative_load)
    window = MainWindow()
    qtbot.addWidget(window)

    window.load_path(first)
    assert first_started.wait(timeout=1)
    window.load_path(second)

    qtbot.waitUntil(first_cancelled.is_set)
    qtbot.waitUntil(lambda: window.report == second_report)


def dated_activity(activity_id: str, day: int | None) -> ActivityTrack:
    stamp = None if day is None else datetime(2026, 6, day, 7, 0, tzinfo=UTC)
    return ActivityTrack(
        activity_id=activity_id,
        name=activity_id,
        source_file=Path(f"{activity_id}.json"),
        points=(
            TrackPoint(52.50 + day * 0.01 if day else 52.50, 13.40, stamp),
            TrackPoint(52.51 + day * 0.01 if day else 52.51, 13.41, stamp),
            TrackPoint(52.52 + day * 0.01 if day else 52.52, 13.42, stamp),
        ),
    )


def dated_window(qtbot: QtBot) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    tracks = (
        dated_activity("june-2", 2),
        dated_activity("june-9", 9),
        dated_activity("june-20", 20),
        dated_activity("undated", None),
    )
    window.canvas.set_prepared_tracks(tracks, prepare_tracks(tracks))
    return window


def test_typed_dates_filter_the_rendered_tracks(qtbot: QtBot) -> None:
    window = dated_window(qtbot)
    assert window.canvas.filtered_track_count == 4

    window.start_date_field.setText("2026-06-02")
    window.end_date_field.setText("2026-06-09")
    window.apply_date_filter()

    assert window.canvas.filtered_track_count == 2
    assert window.canvas.date_filter_start == date(2026, 6, 2)
    assert window.canvas.date_filter_end == date(2026, 6, 9)
    assert "2 of 4 tracks in range" in window.date_filter_label.text()
    assert window.settings.date_filter_start == "2026-06-02"
    assert window.settings.date_filter_end == "2026-06-09"

    window.canvas.resize(400, 300)
    window.canvas.render_to_pixmap()
    assert window.canvas.visible_track_count == 2


def test_open_ended_and_cleared_date_filters(qtbot: QtBot) -> None:
    window = dated_window(qtbot)

    window.start_date_field.setText("2026-06-09")
    window.apply_date_filter()
    assert window.canvas.filtered_track_count == 2

    window.start_date_field.clear()
    window.end_date_field.setText("2026-06-02")
    window.apply_date_filter()
    assert window.canvas.filtered_track_count == 1

    window.clear_date_filter()
    assert window.canvas.filtered_indexes is None
    assert window.canvas.filtered_track_count == 4
    assert window.settings.date_filter_start is None
    assert "All 4 tracks shown" in window.date_filter_label.text()


def test_invalid_date_text_is_reported_and_does_not_filter(qtbot: QtBot) -> None:
    window = dated_window(qtbot)

    window.start_date_field.setText("02.06.2026")
    window.apply_date_filter()

    assert window.canvas.filtered_indexes is None
    assert "earliest" in window.date_filter_label.text()
    assert "YYYY-MM-DD" in window.date_filter_label.text()
    assert window.start_date_field.styleSheet() != ""

    window.start_date_field.setText("2026-06-09")
    window.apply_date_filter()
    assert window.start_date_field.styleSheet() == ""
    assert window.canvas.filtered_track_count == 2


def test_inverted_range_reports_that_nothing_matches(qtbot: QtBot) -> None:
    window = dated_window(qtbot)

    window.start_date_field.setText("2026-06-20")
    window.end_date_field.setText("2026-06-02")
    window.apply_date_filter()

    assert window.canvas.filtered_track_count == 0
    assert "earliest date is after the latest date" in window.date_filter_label.text()


def test_calendar_picker_writes_a_date_into_the_field(qtbot: QtBot) -> None:
    window = dated_window(qtbot)

    window.pick_start_date()
    assert window._active_calendar_widget is not None
    window._active_calendar_widget.clicked.emit(QDate(2026, 6, 9))

    assert window.start_date_field.text() == "2026-06-09"
    assert window.canvas.date_filter_start == date(2026, 6, 9)
    assert window._active_calendar is None

    window.pick_end_date()
    assert window._active_calendar_widget is not None
    window._active_calendar_widget.clicked.emit(QDate(2026, 6, 20))
    assert window.end_date_field.text() == "2026-06-20"
    assert window.canvas.filtered_track_count == 2


def test_persisted_date_filter_is_restored_on_the_next_start(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    first = MainWindow(store)
    qtbot.addWidget(first)
    first.start_date_field.setText("2026-06-09")
    first.apply_date_filter()

    second = MainWindow(SettingsStore(tmp_path / "settings.json"))
    qtbot.addWidget(second)

    assert second.start_date_field.text() == "2026-06-09"
    assert second.canvas.date_filter_start == date(2026, 6, 9)


def test_replay_reveals_tracks_chronologically(qtbot: QtBot) -> None:
    window = dated_window(qtbot)
    window.canvas.resize(400, 300)

    window.start_replay()
    assert window.replay_timer.isActive()
    assert window.replay_button.text() == "Stop replay"
    assert window.canvas.replay_active
    assert window.canvas.replay_cutoff is None
    window.canvas.render_to_pixmap()
    assert window.canvas.visible_track_count == 0
    assert "0%" in window.replay_label.text()

    window.apply_replay_progress(0.5)
    assert window.canvas.replay_cutoff == date(2026, 6, 10)
    window.canvas.render_to_pixmap()
    assert window.canvas.visible_track_count == 2
    assert "2026-06-10" in window.replay_label.text()

    window.apply_replay_progress(1.0)
    assert window.canvas.replay_cutoff == date(2026, 6, 20)
    window.canvas.render_to_pixmap()
    assert window.canvas.visible_track_count == 3

    window.stop_replay()
    assert not window.replay_timer.isActive()
    assert not window.canvas.replay_active
    assert window.replay_button.text() == "Replay over time"
    window.canvas.render_to_pixmap()
    assert window.canvas.visible_track_count == 4


def test_replay_ticks_finish_after_the_configured_duration(qtbot: QtBot) -> None:
    window = dated_window(qtbot)
    window.start_replay()
    ticks = REPLAY_DURATION_MILLISECONDS // REPLAY_TICK_MILLISECONDS

    for _ in range(ticks - 1):
        window.advance_replay()
    assert window.replay_timer.isActive()
    assert window.canvas.replay_active

    window.advance_replay()

    assert not window.replay_timer.isActive()
    assert not window.canvas.replay_active


def test_replay_toggles_and_respects_an_active_date_filter(qtbot: QtBot) -> None:
    window = dated_window(qtbot)
    window.canvas.resize(400, 300)
    window.start_date_field.setText("2026-06-09")
    window.apply_date_filter()

    window.toggle_replay()
    window.apply_replay_progress(0.5)
    window.canvas.render_to_pixmap()

    assert window.canvas.visible_track_count == 1
    assert "2026-06-09" in window.replay_label.text()

    window.toggle_replay()
    assert not window.replay_timer.isActive()
    window.canvas.render_to_pixmap()
    assert window.canvas.visible_track_count == 2


def test_replay_without_dated_tracks_reports_and_does_not_start(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    undated = (dated_activity("undated", None),)
    window.canvas.set_prepared_tracks(undated, prepare_tracks(undated))

    window.start_replay()

    assert not window.replay_timer.isActive()
    assert not window.canvas.replay_active
    assert window.replay_label.text() == "No dated tracks to replay."


def test_loading_a_directory_stops_a_running_replay(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = dated_window(qtbot)
    window.start_replay()
    report = LoadReport(tmp_path, 0, (), ())
    monkeypatch.setattr(
        widgets,
        "load_and_prepare_directory",
        lambda *_args, **_kwargs: PreparedLoad(report, ()),
    )

    window.load_path(tmp_path)

    assert not window.replay_timer.isActive()
    assert not window.canvas.replay_active
