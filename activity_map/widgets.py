from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
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


class MapCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(720, 420)
        self.setMouseTracking(True)
        self.tracks: tuple[ActivityTrack, ...] = ()
        self.heat_cells: tuple[HeatCell, ...] = ()
        self.viewport = fit_viewport(None, 960, 540)
        self.track_opacity = 0.72
        self.heat_intensity = 0.70
        self._last_drag_pos: QPoint | None = None

    def set_tracks(self, tracks: tuple[ActivityTrack, ...]) -> None:
        self.tracks = tracks
        self.heat_cells = build_heat_grid(all_points(tracks), cell_size=0.006)
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
        self._draw_heat(painter)
        self._draw_tracks(painter)

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

    def _draw_heat(self, painter: QPainter) -> None:
        if not self.heat_cells or self.heat_intensity <= 0:
            return
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for cell in self.heat_cells:
            alpha = int(180 * cell.intensity * self.heat_intensity)
            color = QColor(HEAT)
            color.setAlpha(max(0, min(220, alpha)))
            painter.setBrush(color)
            size = max(2.0, min(18.0, self.viewport.zoom * 0.006))
            screen = self.viewport.world_to_screen(
                project_point(project_point_for_heat(cell.x_index, cell.y_index, 0.006))
            )
            painter.drawEllipse(QPointF(screen.x, screen.y), size, size)
        painter.restore()

    def _draw_tracks(self, painter: QPainter) -> None:
        if not self.tracks or self.track_opacity <= 0:
            return
        painter.save()
        for index, track in enumerate(self.tracks):
            color = QColor(TRACK if index % 2 == 0 else TRACK_ALT)
            color.setAlpha(int(210 * self.track_opacity))
            painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine))
            draw_polyline(
                painter,
                [
                    self.viewport.world_to_screen(project_point(point))
                    for point in track.points
                ],
            )
        painter.restore()


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
        side_layout.addWidget(field_label("Track opacity"))
        side_layout.addWidget(opacity_slider)
        side_layout.addWidget(field_label("Heat intensity"))
        side_layout.addWidget(heat_slider)
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


def all_points(tracks: tuple[ActivityTrack, ...]) -> tuple[TrackPoint, ...]:
    return tuple(point for track in tracks for point in track.points)


def draw_polyline(painter: QPainter, points: list[ScreenPoint]) -> None:
    if len(points) < 2:
        return
    for start, end in zip(points, points[1:], strict=False):
        painter.drawLine(QPointF(start.x, start.y), QPointF(end.x, end.y))


def project_point_for_heat(x_index: int, y_index: int, cell_size: float) -> TrackPoint:
    x = (x_index + 0.5) * cell_size
    y = (y_index + 0.5) * cell_size
    longitude = x * 360.0 - 180.0
    mercator = math_atan_sinh((1.0 - 2.0 * y) * 3.141592653589793)
    latitude = mercator * 180.0 / 3.141592653589793
    return TrackPoint(latitude=latitude, longitude=longitude)


def math_atan_sinh(value: float) -> float:
    import math

    return math.atan(math.sinh(value))


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
"""
