from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QTransform,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .geo import (
    ScreenPoint,
    Viewport,
    choose_scale_bar,
    coordinate_bounds,
    fit_viewport,
    format_scale_distance,
    latitude_from_projected_y,
    project_point,
)
from .loading import PreparedLoad, load_and_prepare_directory
from .lod import select_lod
from .models import ActivityTrack, LoadReport, TrackPoint
from .qt_render import RetainedTrackPaths, prepare_retained_paths, viewport_transform
from .render import (
    MARKER_MAX_ZOOM,
    RenderTrack,
    geometry_for_zoom,
    prepare_tracks,
    track_label_anchor,
)
from .settings import SettingsStore
from .spatial import TrackSpatialIndex, viewport_bounds
from .tiles import (
    OSM_ATTRIBUTION,
    TileCache,
    TileCoordinate,
    tile_bounds,
    visible_tiles,
)

BACKGROUND = QColor("#08111f")
PANEL = QColor("#101827")
GRID = QColor(55, 85, 120, 90)
GRID_MAJOR = QColor(78, 125, 170, 135)
LAND = QColor(22, 45, 59, 180)
TRACK = QColor(45, 220, 255, 150)
TEXT = "#e8f1ff"
MUTED = "#8da2bd"
GESTURE_SETTLE_MILLISECONDS = 60


class TileSignals(QObject):
    loaded = pyqtSignal(object, bytes)


class LoadSignals(QObject):
    completed = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)


class MapCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(720, 420)
        self.setMouseTracking(True)
        self.tracks: tuple[ActivityTrack, ...] = ()
        self.render_tracks: tuple[RenderTrack, ...] = ()
        self.retained_track_paths: tuple[RetainedTrackPaths, ...] = ()
        self.spatial_index = TrackSpatialIndex.build(())
        self.last_visible_track_count = 0
        self.last_path_draw_calls = 0
        self.last_selected_point_count = 0
        self.last_lod_tolerance = 0.0
        self.viewport = fit_viewport(None, 960, 540)
        self.track_color = QColor(TRACK)
        self.track_opacity = 0.72
        self.track_names_visible = False
        self.tile_opacity = 0.82
        self.tile_layer_enabled = os.environ.get("ACTIVITY_MAP_DISABLE_TILES") != "1"
        self.tile_cache = TileCache()
        self.tile_pixmaps: dict[TileCoordinate, QPixmap] = {}
        self.pending_tiles: set[TileCoordinate] = set()
        self.tile_executor = ThreadPoolExecutor(max_workers=4)
        self.tile_signals = TileSignals()
        self.tile_signals.loaded.connect(self._store_tile)
        self._last_drag_pos: QPoint | None = None
        self._gesture_pixmap: QPixmap | None = None
        self._gesture_viewport: Viewport | None = None
        self._gesture_timer = QTimer(self)
        self._gesture_timer.setSingleShot(True)
        self._gesture_timer.timeout.connect(self.finish_gesture)

    def set_tracks(self, tracks: tuple[ActivityTrack, ...]) -> None:
        self.set_prepared_tracks(tracks, prepare_tracks(tracks))

    def set_prepared_tracks(
        self,
        tracks: tuple[ActivityTrack, ...],
        render_tracks: tuple[RenderTrack, ...],
    ) -> None:
        self.finish_gesture()
        self.tracks = tracks
        self.render_tracks = render_tracks
        self.retained_track_paths = prepare_retained_paths(self.render_tracks)
        self.spatial_index = TrackSpatialIndex.build(self.render_tracks)
        self.reset_view()

    def reset_view(self) -> None:
        self.finish_gesture()
        self.viewport = fit_viewport(
            coordinate_bounds(all_points(self.tracks)),
            max(self.width(), 1),
            max(self.height(), 1),
        )
        self.update()

    def set_track_opacity(self, value: int) -> None:
        self.finish_gesture()
        self.track_opacity = value / 100.0
        self.update()

    def set_track_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self.finish_gesture()
        self.track_color = QColor(color)
        self.update()

    def set_track_names_visible(self, visible: bool) -> None:
        self.finish_gesture()
        self.track_names_visible = visible
        self.update()

    def set_tile_layer_enabled(self, enabled: bool) -> None:
        self.finish_gesture()
        self.tile_layer_enabled = enabled
        self.update()

    def set_tile_opacity(self, value: int) -> None:
        self.finish_gesture()
        self.tile_opacity = value / 100.0
        self.update()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        self.finish_gesture()
        self.viewport = Viewport(
            center=self.viewport.center,
            zoom=self.viewport.zoom,
            width=max(self.width(), 1),
            height=max(self.height(), 1),
        )
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.begin_gesture()
            self._last_drag_pos = event.position().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._last_drag_pos is None:
            return
        current = event.position().toPoint()
        delta = current - self._last_drag_pos
        self._last_drag_pos = current
        self.viewport = self.viewport.pan(delta.x(), delta.y())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_drag_pos = None
            self.finish_gesture()

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None:
            return
        self.begin_gesture()
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        position = event.position()
        self.viewport = self.viewport.zoom_at(
            factor,
            ScreenPoint(position.x(), position.y()),
        )
        self._gesture_timer.start(GESTURE_SETTLE_MILLISECONDS)
        self.update()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(max(self.height(), 1)))
        gradient.setColorAt(0.0, QColor("#08111f"))
        gradient.setColorAt(1.0, QColor("#0d1f2c"))
        painter.fillRect(self.rect(), gradient)
        if self._draw_gesture_cache(painter):
            return
        self._draw_backdrop(painter)
        self._draw_tiles(painter)
        self._draw_tracks(painter)
        self._draw_track_names(painter)
        self._draw_scale_bar(painter)
        self._draw_attribution(painter)

    def render_to_pixmap(self) -> QPixmap:
        pixmap = QPixmap(self.size())
        pixmap.fill(BACKGROUND)
        self.render(pixmap)
        return pixmap

    def begin_gesture(self) -> None:
        if self._gesture_pixmap is not None:
            return
        self._gesture_viewport = self.viewport
        self._gesture_pixmap = self.render_to_pixmap()

    def finish_gesture(self) -> None:
        self._gesture_timer.stop()
        self._gesture_pixmap = None
        self._gesture_viewport = None
        self.update()

    def _draw_gesture_cache(self, painter: QPainter) -> bool:
        if self._gesture_pixmap is None or self._gesture_viewport is None:
            return False
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setWorldTransform(
            gesture_transform(self._gesture_viewport, self.viewport)
        )
        painter.drawPixmap(0, 0, self._gesture_pixmap)
        painter.restore()
        return True

    def _draw_backdrop(self, painter: QPainter) -> None:
        painter.save()
        painter.setPen(QPen(GRID, 1))
        for longitude in range(-180, 181, 30):
            points = [
                self.viewport.world_to_screen(project_point(TrackPoint(lat, longitude)))
                for lat in range(-75, 76, 5)
            ]
            draw_polyline(painter, points)

        for latitude in range(-60, 61, 30):
            painter.setPen(QPen(GRID_MAJOR if latitude == 0 else GRID, 1))
            points = [
                self.viewport.world_to_screen(project_point(TrackPoint(latitude, lon)))
                for lon in range(-180, 181, 5)
            ]
            draw_polyline(painter, points)

        painter.setBrush(LAND)
        painter.setPen(Qt.PenStyle.NoPen)
        for rect in rough_land_rects():
            top_left = self.viewport.world_to_screen(
                project_point(TrackPoint(rect[1], rect[0]))
            )
            bottom_right = self.viewport.world_to_screen(
                project_point(TrackPoint(rect[3], rect[2]))
            )
            painter.drawRoundedRect(
                QRectF(
                    QPointF(top_left.x, top_left.y),
                    QPointF(bottom_right.x, bottom_right.y),
                ).normalized(),
                8,
                8,
            )
        painter.restore()

    def _draw_tiles(self, painter: QPainter) -> None:
        if not self.tile_layer_enabled:
            return
        painter.save()
        painter.setOpacity(self.tile_opacity)
        for coordinate in visible_tiles(self.viewport):
            pixmap = self._tile_pixmap(coordinate)
            if pixmap is None:
                self._request_tile(coordinate)
                continue
            bounds = tile_bounds(coordinate)
            top_left = self.viewport.world_to_screen(bounds.top_left)
            bottom_right = self.viewport.world_to_screen(bounds.bottom_right)
            painter.drawPixmap(
                QRectF(
                    QPointF(top_left.x, top_left.y),
                    QPointF(bottom_right.x, bottom_right.y),
                ).normalized(),
                pixmap,
                QRectF(pixmap.rect()),
            )
        painter.restore()

    def _tile_pixmap(self, coordinate: TileCoordinate) -> QPixmap | None:
        pixmap = self.tile_pixmaps.get(coordinate)
        if pixmap is not None:
            return pixmap
        cached = self.tile_cache.load_cached_tile(coordinate)
        if cached is None:
            return None
        loaded = QPixmap()
        if not loaded.loadFromData(cached):
            return None
        self.tile_pixmaps[coordinate] = loaded
        return loaded

    def _request_tile(self, coordinate: TileCoordinate) -> None:
        if coordinate in self.pending_tiles:
            return
        self.pending_tiles.add(coordinate)
        future = self.tile_executor.submit(self.tile_cache.fetch_tile, coordinate)
        future.add_done_callback(self._tile_result_callback(coordinate))

    def _tile_result_callback(
        self,
        coordinate: TileCoordinate,
    ) -> Callable[[Future[bytes | None]], None]:
        def callback(future: Future[bytes | None]) -> None:
            self._emit_tile_result(coordinate, future)

        return callback

    def _emit_tile_result(
        self,
        coordinate: TileCoordinate,
        future: Future[bytes | None],
    ) -> None:
        try:
            data = future.result()
        except OSError:
            data = None
        if data is not None:
            self.tile_signals.loaded.emit(coordinate, data)
        else:
            self.pending_tiles.discard(coordinate)

    def _store_tile(self, coordinate: TileCoordinate, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.tile_pixmaps[coordinate] = pixmap
        self.pending_tiles.discard(coordinate)
        self.update()

    def _draw_attribution(self, painter: QPainter) -> None:
        if not self.tile_layer_enabled:
            return
        painter.save()
        painter.setFont(QFont("Sans Serif", 8))
        painter.setPen(QColor(20, 28, 38, 210))
        painter.drawText(
            self.rect().adjusted(0, 0, -8, -8),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
            OSM_ATTRIBUTION,
        )
        painter.restore()

    def _draw_tracks(self, painter: QPainter) -> None:
        if not self.render_tracks or self.track_opacity <= 0:
            return
        painter.save()
        color = QColor(self.track_color)
        color.setAlpha(int(210 * self.track_opacity))
        pen = QPen(color, 2.2, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        visible_indexes = self.spatial_index.query(viewport_bounds(self.viewport))
        self.last_visible_track_count = len(visible_indexes)
        self.last_path_draw_calls = 0
        if self.viewport.zoom > MARKER_MAX_ZOOM:
            painter.setWorldTransform(viewport_transform(self.viewport))
            selection = select_lod(
                self.render_tracks,
                visible_indexes,
                self.viewport.zoom,
            )
            self.last_selected_point_count = selection.point_count
            self.last_lod_tolerance = selection.tolerance_world
            for index in visible_indexes:
                paths = self.retained_track_paths[index]
                painter.drawPath(paths.levels[selection.level_index])
                self.last_path_draw_calls += 1
        else:
            self.last_selected_point_count = len(visible_indexes)
            self.last_lod_tolerance = 0.0
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            for index in visible_indexes:
                track = self.render_tracks[index]
                geometry = geometry_for_zoom(track, self.viewport.zoom)
                for marker in geometry.markers:
                    screen = self.viewport.world_to_screen(marker)
                    painter.drawEllipse(QPointF(screen.x, screen.y), 3.0, 3.0)
        painter.restore()

    def _draw_track_names(self, painter: QPainter) -> None:
        if not self.track_names_visible or not self.render_tracks:
            return
        painter.save()
        label_font = QFont("Sans Serif", 8)
        painter.setFont(label_font)
        metrics = QFontMetrics(label_font)
        visible_indexes = self.spatial_index.query(viewport_bounds(self.viewport))
        for index in visible_indexes:
            track = self.render_tracks[index]
            anchor = track_label_anchor(track)
            if anchor is None:
                continue
            screen = self.viewport.world_to_screen(anchor)
            text_rect = QRectF(screen.x + 4.0, screen.y - 18.0, 180.0, 16.0)
            label = metrics.elidedText(
                track.name,
                Qt.TextElideMode.ElideRight,
                int(text_rect.width()),
            )
            painter.setPen(QPen(QColor(8, 17, 31, 230), 3))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(QColor("#f7fbff"))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
        painter.restore()

    def _draw_scale_bar(self, painter: QPainter) -> None:
        latitude = latitude_from_projected_y(self.viewport.center.y)
        distance, width = choose_scale_bar(
            latitude,
            self.viewport.zoom,
            target_width=max(self.width() * 0.18, 100.0),
            max_width=self.width() * 0.36,
        )

        margin = 18.0
        bottom = self.height() - margin - 8.0
        right = self.width() - margin
        draw_width = max(width, 28.0)
        left = right - draw_width
        label = format_scale_distance(distance)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setFont(QFont("Sans Serif", 9))
        painter.setPen(QPen(QColor(8, 17, 31, 220), 5))
        painter.drawLine(QPointF(left, bottom), QPointF(right, bottom))
        painter.drawLine(QPointF(left, bottom - 8), QPointF(left, bottom + 1))
        painter.drawLine(QPointF(right, bottom - 8), QPointF(right, bottom + 1))

        painter.setPen(QPen(QColor("#e8f1ff"), 2))
        painter.drawLine(QPointF(left, bottom), QPointF(right, bottom))
        painter.drawLine(QPointF(left, bottom - 8), QPointF(left, bottom + 1))
        painter.drawLine(QPointF(right, bottom - 8), QPointF(right, bottom + 1))
        painter.drawText(
            QRectF(left, bottom - 25.0, draw_width, 16.0),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
        painter.restore()

    def shutdown_tiles(self) -> None:
        self.tile_executor.shutdown(wait=False, cancel_futures=True)


class MainWindow(QMainWindow):
    def __init__(self, settings_store: SettingsStore | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"Garmin Activity Map {__version__}")
        self.resize(1200, 760)
        self.report: LoadReport | None = None
        self.load_executor = ThreadPoolExecutor(max_workers=1)
        self.load_signals = LoadSignals()
        self.load_signals.completed.connect(self._apply_load_result)
        self.load_signals.failed.connect(self._apply_load_failure)
        self._load_generation = 0
        self.settings_store = settings_store or SettingsStore()
        self.settings = self.settings_store.load()
        self.settings.last_run_timestamp = (
            datetime.now(UTC).replace(microsecond=0).isoformat()
        )

        self.canvas = MapCanvas()
        self.apply_canvas_settings()
        self.status_label = QLabel("No directory loaded")
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)

        choose_button = QPushButton("Open Directory")
        choose_button.clicked.connect(self.choose_directory)
        reset_button = QPushButton("Reset View")
        reset_button.clicked.connect(self.canvas.reset_view)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("trackOpacitySlider")
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setMinimumHeight(24)
        self.opacity_slider.setValue(self.settings.track_opacity)
        self.opacity_slider.valueChanged.connect(self.set_track_opacity)

        self.track_names_checkbox = QCheckBox("Show track names")
        self.track_names_checkbox.setChecked(self.settings.show_track_names)
        self.track_names_checkbox.toggled.connect(self.set_track_names_visible)

        self.track_color_button = QPushButton("Track Color")
        self.track_color_button.clicked.connect(self.choose_track_color)
        self.update_track_color_button()

        self.map_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.map_opacity_slider.setObjectName("mapOpacitySlider")
        self.map_opacity_slider.setRange(0, 100)
        self.map_opacity_slider.setMinimumHeight(24)
        self.map_opacity_slider.setValue(self.settings.map_opacity)
        self.map_opacity_slider.valueChanged.connect(self.set_map_opacity)

        self.map_layer_checkbox = QCheckBox("OpenStreetMap layer")
        self.map_layer_checkbox.setChecked(self.canvas.tile_layer_enabled)
        self.map_layer_checkbox.toggled.connect(self.set_map_layer_enabled)

        side_panel = QFrame()
        side_panel.setObjectName("sidePanel")
        side_panel.setFixedWidth(300)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(18, 18, 18, 18)
        side_layout.setSpacing(14)
        side_layout.addWidget(title_label("Activity Map"))
        side_layout.addWidget(subtitle_label("Local Garmin track explorer"))
        side_layout.addSpacing(10)
        side_layout.addWidget(choose_button)
        side_layout.addWidget(reset_button)
        side_layout.addSpacing(12)
        side_layout.addWidget(field_label("Legend"))
        legend, self.track_legend_swatch = legend_row(
            self.canvas.track_color,
            "Activity track lines",
        )
        side_layout.addWidget(legend)
        side_layout.addSpacing(12)
        side_layout.addWidget(field_label("Track color"))
        side_layout.addWidget(self.track_color_button)
        side_layout.addWidget(field_label("Track opacity"))
        side_layout.addWidget(self.opacity_slider)
        side_layout.addWidget(self.track_names_checkbox)
        side_layout.addWidget(field_label("Map opacity"))
        side_layout.addWidget(self.map_opacity_slider)
        side_layout.addWidget(self.map_layer_checkbox)
        side_layout.addSpacing(12)
        side_layout.addWidget(field_label("Load status"))
        side_layout.addWidget(self.status_label)
        side_layout.addWidget(self.warning_label)
        side_layout.addStretch(1)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(side_panel)
        layout.addWidget(self.canvas, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(APP_STYLES)
        self.save_settings()

    def choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Open Garmin export directory",
            str(Path.cwd()),
        )
        if directory:
            self.load_path(Path(directory))

    def choose_track_color(self) -> None:
        color = QColorDialog.getColor(
            self.canvas.track_color,
            self,
            "Choose track color",
        )
        if color.isValid():
            self.canvas.set_track_color(color)
            self.update_track_color_button()
            self.settings.track_color = color.name()
            self.save_settings()

    def update_track_color_button(self) -> None:
        color = self.canvas.track_color.name()
        self.track_color_button.setStyleSheet(
            f"background: {color}; color: #08111f; font-weight: 700;"
        )
        if hasattr(self, "track_legend_swatch"):
            update_legend_swatch(self.track_legend_swatch, self.canvas.track_color)

    def load_path(self, path: Path) -> None:
        self._load_generation += 1
        generation = self._load_generation
        self.status_label.setText(f"Loading {path}...")
        self.warning_label.setText("")
        future = self.load_executor.submit(load_and_prepare_directory, path)
        future.add_done_callback(self._load_result_callback(generation))

    def load_path_sync(self, path: Path) -> None:
        self._load_generation += 1
        result = load_and_prepare_directory(path)
        self._apply_load_result(self._load_generation, result)

    def _load_result_callback(
        self,
        generation: int,
    ) -> Callable[[Future[PreparedLoad]], None]:
        def callback(future: Future[PreparedLoad]) -> None:
            try:
                result = future.result()
            except Exception as exc:
                self.load_signals.failed.emit(generation, str(exc))
                return
            self.load_signals.completed.emit(generation, result)

        return callback

    def _apply_load_result(self, generation: int, result: PreparedLoad) -> None:
        if generation != self._load_generation:
            return
        self.report = result.report
        self.canvas.set_prepared_tracks(self.report.tracks, result.render_tracks)
        self.status_label.setText(
            f"{len(self.report.tracks)} tracks, "
            f"{self.report.point_count} points, "
            f"{self.report.files_read} files scanned"
        )
        if self.report.warnings:
            self.warning_label.setText(
                f"{len(self.report.warnings)} files skipped or incomplete; "
                f"{self.report.validation_issue_count} track validation issues"
            )
        elif self.report.validation_issue_count:
            self.warning_label.setText(
                f"{self.report.validation_issue_count} track validation issues"
            )
        else:
            self.warning_label.setText("No warnings")
        self.settings.last_track_directory = str(self.report.root)
        self.save_settings()

    def _apply_load_failure(self, generation: int, message: str) -> None:
        if generation != self._load_generation:
            return
        self.status_label.setText("Load failed")
        self.warning_label.setText(message)

    def load_last_directory(self) -> None:
        if self.settings.last_track_directory is None:
            return
        path = Path(self.settings.last_track_directory)
        if path.exists():
            self.load_path(path)

    def apply_canvas_settings(self) -> None:
        self.canvas.set_track_color(QColor(self.settings.track_color))
        self.canvas.set_track_opacity(self.settings.track_opacity)
        self.canvas.set_track_names_visible(self.settings.show_track_names)
        self.canvas.set_tile_opacity(self.settings.map_opacity)
        self.canvas.set_tile_layer_enabled(
            self.canvas.tile_layer_enabled and self.settings.map_layer_enabled
        )

    def set_track_opacity(self, value: int) -> None:
        self.canvas.set_track_opacity(value)
        self.settings.track_opacity = value
        self.save_settings()

    def set_track_names_visible(self, visible: bool) -> None:
        self.canvas.set_track_names_visible(visible)
        self.settings.show_track_names = visible
        self.save_settings()

    def set_map_opacity(self, value: int) -> None:
        self.canvas.set_tile_opacity(value)
        self.settings.map_opacity = value
        self.save_settings()

    def set_map_layer_enabled(self, enabled: bool) -> None:
        self.canvas.set_tile_layer_enabled(enabled)
        self.settings.map_layer_enabled = enabled
        self.save_settings()

    def save_settings(self) -> None:
        self.settings_store.save(self.settings)

    def closeEvent(self, event: QCloseEvent | None) -> None:
        self._load_generation += 1
        self.load_executor.shutdown(wait=False, cancel_futures=True)
        self.canvas.shutdown_tiles()
        if event is not None:
            super().closeEvent(event)


def all_points(tracks: tuple[ActivityTrack, ...]) -> tuple[TrackPoint, ...]:
    return tuple(point for track in tracks for point in track.points)


def draw_polyline(painter: QPainter, points: list[ScreenPoint]) -> None:
    if len(points) < 2:
        return
    for start, end in zip(points, points[1:], strict=False):
        painter.drawLine(QPointF(start.x, start.y), QPointF(end.x, end.y))


def gesture_transform(source: Viewport, target: Viewport) -> QTransform:
    scale = target.zoom / source.zoom
    return QTransform(
        scale,
        0.0,
        0.0,
        scale,
        (source.center.x - target.center.x) * target.zoom
        + target.width / 2.0
        - source.width / 2.0 * scale,
        (source.center.y - target.center.y) * target.zoom
        + target.height / 2.0
        - source.height / 2.0 * scale,
    )


def rough_land_rects() -> tuple[tuple[float, float, float, float], ...]:
    return (
        (-168, 15, -52, 72),
        (-82, -56, -34, 13),
        (-10, 35, 40, 70),
        (-20, -35, 52, 35),
        (35, 5, 150, 72),
        (110, -45, 155, -10),
    )


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("title")
    return label


def subtitle_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("subtitle")
    return label


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    return label


def legend_row(color: QColor, text: str) -> tuple[QWidget, QFrame]:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    swatch = QFrame()
    swatch.setFixedSize(14, 14)
    update_legend_swatch(swatch, color)

    label = QLabel(text)
    label.setObjectName("legendLabel")
    layout.addWidget(swatch)
    layout.addWidget(label, 1)
    return row, swatch


def update_legend_swatch(swatch: QFrame, color: QColor) -> None:
    swatch.setStyleSheet(
        f"background: {color.name()}; border-radius: 7px; border: 1px solid #d7e8ff;"
    )


APP_STYLES = f"""
QMainWindow {{
    background: {BACKGROUND.name()};
}}
QFrame#sidePanel {{
    background: {PANEL.name()};
    border-right: 1px solid #26364c;
}}
QLabel {{
    color: {TEXT};
    font-size: 13px;
}}
QLabel#title {{
    font-size: 24px;
    font-weight: 700;
}}
QLabel#subtitle {{
    color: {MUTED};
    font-size: 13px;
}}
QLabel#fieldLabel {{
    color: {MUTED};
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
}}
QLabel#legendLabel {{
    color: {MUTED};
    font-size: 12px;
}}
QPushButton {{
    background: #1d9bd1;
    border: 0;
    border-radius: 6px;
    color: white;
    font-weight: 700;
    min-height: 34px;
    padding: 6px 10px;
}}
QPushButton:hover {{
    background: #27afe9;
}}
QSlider::groove:horizontal {{
    background: #26364c;
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: #ffc342;
    width: 16px;
    margin: -4px 0;
    border-radius: 8px;
}}
QCheckBox {{
    color: {TEXT};
    font-size: 13px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
}}
"""
