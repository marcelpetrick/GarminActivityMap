from __future__ import annotations

from dataclasses import dataclass

from .geo import ProjectedPoint, haversine_distance_meters, project_point
from .heat import HeatCell
from .models import ActivityTrack


@dataclass(frozen=True, slots=True)
class RenderTrack:
    activity_id: str
    name: str
    segments: tuple[tuple[ProjectedPoint, ...], ...]


@dataclass(frozen=True, slots=True)
class RenderHeatCell:
    center: ProjectedPoint
    count: int
    intensity: float


MAX_CONTINUOUS_SEGMENT_METERS = 5_000.0
MIN_RENDERED_TRACK_POINTS = 3


def prepare_tracks(
    tracks: tuple[ActivityTrack, ...],
    max_segment_distance_meters: float = MAX_CONTINUOUS_SEGMENT_METERS,
) -> tuple[RenderTrack, ...]:
    return tuple(
        RenderTrack(
            activity_id=track.activity_id,
            name=track.name,
            segments=split_projected_segments(track, max_segment_distance_meters),
        )
        for track in tracks
        if len(track.points) >= MIN_RENDERED_TRACK_POINTS
    )


def split_projected_segments(
    track: ActivityTrack,
    max_segment_distance_meters: float,
) -> tuple[tuple[ProjectedPoint, ...], ...]:
    segments: list[tuple[ProjectedPoint, ...]] = []
    current: list[ProjectedPoint] = []
    previous = None

    for point in track.points:
        if (
            previous is not None
            and haversine_distance_meters(previous, point) > max_segment_distance_meters
        ):
            if len(current) >= 2:
                segments.append(tuple(current))
            current = []

        current.append(project_point(point))
        previous = point

    if len(current) >= 2:
        segments.append(tuple(current))
    return tuple(segments)


def prepare_heat_cells(
    heat_cells: tuple[HeatCell, ...], cell_size: float
) -> tuple[RenderHeatCell, ...]:
    return tuple(
        RenderHeatCell(
            center=ProjectedPoint(
                x=(cell.x_index + 0.5) * cell_size,
                y=(cell.y_index + 0.5) * cell_size,
            ),
            count=cell.count,
            intensity=cell.intensity,
        )
        for cell in heat_cells
    )
