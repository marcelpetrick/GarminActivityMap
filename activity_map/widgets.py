from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
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

from .geo import (
    ScreenPoint,
    Viewport,
    coordinate_bounds,
    fit_viewport,
    project_point,
)
from .heat import HeatCell, build_heat_grid
from .loader import load_directory
from .models import ActivityTrack, LoadReport, TrackPoint
from .render import RenderHeatCell, RenderTrack, prepare_heat_cells, prepare_tracks
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
TRACK_ALT = QColor(255, 195, 65, 130)
HEAT = QColor(255, 70, 145, 110)
TEXT = "#e8f1ff"
MUTED = "#8da2bd"
HEAT_CELL_SIZE = 0.006


class TileSignals(QObject):
    loaded = pyqtSignal(object, bytes)


class MapCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(720, 420)
        self.setMouseTracking(True)
        self.tracks: tuple[ActivityTrack, ...] = ()
        self.render_tracks: tuple[RenderTrack, ...] = ()
        self.heat_cells: tuple[HeatCell, ...] = ()
        self.render_heat_cells: tuple[RenderHeatCell, ...] = ()
        self.viewport = fit_viewport(None, 960, 540)
        self.track_opacity = 0.72
        self.heat_intensity = 0.70
        self.tile_opacity = 0.82
        self.tile_layer_enabled = os.environ.get("ACTIVITY_MAP_DISABLE_TILES") != "1"
        self.tile_cache = TileCache()
        self.tile_pixmaps: dict[TileCoordinate, QPixmap] = {}
        self.pending_tiles: set[TileCoordinate] = set()
        self.tile_executor = ThreadPoolExecutor(max_workers=4)
        self.tile_signals = TileSignals()
        self.tile_signals.loaded.connect(self._store_tile)
        self._last_drag_pos: QPoint | None = None

    def set_tracks(self, tracks: tuple[ActivityTrack, ...]) -> None:
        self.tracks = tracks
        self.render_tracks = prepare_tracks(tracks)
        self.heat_cells = build_heat_grid(all_points(tracks), cell_size=HEAT_CELL_SIZE)
        self.render_heat_cells = prepare_heat_cells(self.heat_cells, HEAT_CELL_SIZE)
        self.reset_view()

    def reset_view(self) -> None:
        self.viewport = fit_viewport(
            coordinate_bounds(all_points(self.tracks)),
            max(self.width(), 1),
            max(self.height(), 1),
        )
        self.update()

    def set_track_opacity(self, value: int) -> None:
        self.track_opacity = value / 100.0
        self.update()

    def set_heat_intensity(self, value: int) -> None:
        self.heat_intensity = value / 100.0
        self.update()

    def set_tile_layer_enabled(self, enabled: bool) -> None:
        self.tile_layer_enabled = enabled
        self.update()

    def set_tile_opacity(self, value: int) -> None:
        self.tile_opacity = value / 100.0
        self.update()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
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

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None:
            return
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        position = event.position()
        self.viewport = self.viewport.zoom_at(
            factor,
            ScreenPoint(position.x(), position.y()),
        )
        self.update()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(max(self.height(), 1)))
        gradient.setColorAt(0.0, QColor("#08111f"))
        gradient.setColorAt(1.0, QColor("#0d1f2c"))
        painter.fillRect(self.rect(), gradient)
        self._draw_backdrop(painter)
        self._draw_tiles(painter)
        self._draw_heat(painter)
        self._draw_tracks(painter)
        self._draw_attribution(painter)

    def render_to_pixmap(self) -> QPixmap:
        pixmap = QPixmap(self.size())
        pixmap.fill(BACKGROUND)
        self.render(pixmap)
        return pixmap

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

    def _draw_heat(self, painter: QPainter) -> None:
        if not self.render_heat_cells or self.heat_intensity <= 0:
            return
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for cell in self.render_heat_cells:
            alpha = int(180 * cell.intensity * self.heat_intensity)
            color = QColor(HEAT)
            color.setAlpha(max(0, min(220, alpha)))
            painter.setBrush(color)
            size = max(2.0, min(18.0, self.viewport.zoom * HEAT_CELL_SIZE))
            screen = self.viewport.world_to_screen(cell.center)
            painter.drawEllipse(QPointF(screen.x, screen.y), size, size)
        painter.restore()

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
        for index, track in enumerate(self.render_tracks):
            color = QColor(TRACK if index % 2 == 0 else TRACK_ALT)
            color.setAlpha(int(210 * self.track_opacity))
            painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine))
            draw_polyline(
                painter,
                [self.viewport.world_to_screen(point) for point in track.points],
            )
        painter.restore()

    def shutdown_tiles(self) -> None:
        self.tile_executor.shutdown(wait=False, cancel_futures=True)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Garmin Activity Map")
        self.resize(1200, 760)
        self.report: LoadReport | None = None

        self.canvas = MapCanvas()
        self.status_label = QLabel("No directory loaded")
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)

        choose_button = QPushButton("Open Directory")
        choose_button.clicked.connect(self.choose_directory)
        reset_button = QPushButton("Reset View")
        reset_button.clicked.connect(self.canvas.reset_view)

        opacity_slider = QSlider(Qt.Orientation.Horizontal)
        opacity_slider.setRange(0, 100)
        opacity_slider.setValue(72)
        opacity_slider.valueChanged.connect(self.canvas.set_track_opacity)

        heat_slider = QSlider(Qt.Orientation.Horizontal)
        heat_slider.setRange(0, 100)
        heat_slider.setValue(70)
        heat_slider.valueChanged.connect(self.canvas.set_heat_intensity)

        map_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        map_opacity_slider.setRange(0, 100)
        map_opacity_slider.setValue(82)
        map_opacity_slider.valueChanged.connect(self.canvas.set_tile_opacity)

        map_layer_checkbox = QCheckBox("OpenStreetMap layer")
        map_layer_checkbox.setChecked(self.canvas.tile_layer_enabled)
        map_layer_checkbox.toggled.connect(self.canvas.set_tile_layer_enabled)

        side_panel = QFrame()
        side_panel.setObjectName("sidePanel")
        side_panel.setFixedWidth(300)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(18, 18, 18, 18)
        side_layout.setSpacing(14)
        side_layout.addWidget(title_label("Activity Map"))
        side_layout.addWidget(subtitle_label("Local Garmin heat explorer"))
        side_layout.addSpacing(10)
        side_layout.addWidget(choose_button)
        side_layout.addWidget(reset_button)
        side_layout.addSpacing(12)
        side_layout.addWidget(field_label("Legend"))
        side_layout.addWidget(legend_row(TRACK, "Track lines alternate cyan"))
        side_layout.addWidget(legend_row(TRACK_ALT, "Track lines alternate amber"))
        side_layout.addWidget(legend_row(HEAT, "Pink/red dots show heat density"))
        side_layout.addSpacing(12)
        side_layout.addWidget(field_label("Track opacity"))
        side_layout.addWidget(opacity_slider)
        side_layout.addWidget(field_label("Heat intensity"))
        side_layout.addWidget(heat_slider)
        side_layout.addWidget(field_label("Map opacity"))
        side_layout.addWidget(map_opacity_slider)
        side_layout.addWidget(map_layer_checkbox)
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

    def choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Open Garmin export directory",
            str(Path.cwd()),
        )
        if directory:
            self.load_path(Path(directory))

    def load_path(self, path: Path) -> None:
        self.report = load_directory(path)
        self.canvas.set_tracks(self.report.tracks)
        self.status_label.setText(
            f"{len(self.report.tracks)} tracks, "
            f"{self.report.point_count} points, "
            f"{self.report.files_read} files scanned"
        )
        if self.report.warnings:
            self.warning_label.setText(
                f"{len(self.report.warnings)} files skipped or incomplete"
            )
        else:
            self.warning_label.setText("No warnings")

    def closeEvent(self, event: QCloseEvent | None) -> None:
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


def legend_row(color: QColor, text: str) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    swatch = QFrame()
    swatch.setFixedSize(14, 14)
    swatch.setStyleSheet(
        f"background: {color.name()}; border-radius: 7px; border: 1px solid #d7e8ff;"
    )

    label = QLabel(text)
    label.setObjectName("legendLabel")
    layout.addWidget(swatch)
    layout.addWidget(label, 1)
    return row


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
    margin: -5px 0;
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
