from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PyQt6.QtGui import QPainterPath, QTransform

from .geo import ProjectedPoint, Viewport, project_point
from .models import TrackPoint
from .render import RenderTrack


@dataclass(frozen=True, slots=True)
class RetainedTrackPaths:
    levels: tuple[QPainterPath, ...]

    @property
    def simplified(self) -> QPainterPath:
        return self.levels[1]

    @property
    def detailed(self) -> QPainterPath:
        return self.levels[-1]


@dataclass(frozen=True, slots=True)
class BackdropPaths:
    grid: QPainterPath
    equator: QPainterPath


def prepare_retained_paths(
    tracks: tuple[RenderTrack, ...],
) -> tuple[RetainedTrackPaths, ...]:
    return tuple(
        RetainedTrackPaths(
            levels=tuple(polyline_path(level.segments) for level in track.levels),
        )
        for track in tracks
    )


def polyline_path(
    segments: tuple[tuple[ProjectedPoint, ...], ...],
) -> QPainterPath:
    path = QPainterPath()
    for segment in segments:
        if len(segment) < 2:
            continue
        path.moveTo(segment[0].x, segment[0].y)
        for point in segment[1:]:
            path.lineTo(point.x, point.y)
    return path


def viewport_transform(viewport: Viewport) -> QTransform:
    return QTransform(
        viewport.zoom,
        0.0,
        0.0,
        viewport.zoom,
        viewport.width / 2.0 - viewport.center.x * viewport.zoom,
        viewport.height / 2.0 - viewport.center.y * viewport.zoom,
    )


@lru_cache(maxsize=1)
def prepare_backdrop_paths() -> BackdropPaths:
    grid_segments: list[tuple[ProjectedPoint, ...]] = []
    for longitude in range(-180, 181, 30):
        grid_segments.append(
            tuple(
                project_point(TrackPoint(latitude, longitude))
                for latitude in range(-75, 76, 5)
            )
        )
    for latitude in (-60, -30, 30, 60):
        grid_segments.append(
            tuple(
                project_point(TrackPoint(latitude, longitude))
                for longitude in range(-180, 181, 5)
            )
        )
    equator = tuple(
        project_point(TrackPoint(0.0, longitude)) for longitude in range(-180, 181, 5)
    )
    return BackdropPaths(
        grid=polyline_path(tuple(grid_segments)),
        equator=polyline_path((equator,)),
    )
