from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QPainterPath, QTransform

from .geo import ProjectedPoint, Viewport
from .render import RenderTrack


@dataclass(frozen=True, slots=True)
class RetainedTrackPaths:
    simplified: QPainterPath
    detailed: QPainterPath


def prepare_retained_paths(
    tracks: tuple[RenderTrack, ...],
) -> tuple[RetainedTrackPaths, ...]:
    return tuple(
        RetainedTrackPaths(
            simplified=polyline_path(track.simplified_segments),
            detailed=polyline_path(track.segments),
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
