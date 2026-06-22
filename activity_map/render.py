from __future__ import annotations

from dataclasses import dataclass

from .geo import ProjectedPoint, haversine_distance_meters, project_point
from .models import ActivityTrack


@dataclass(frozen=True, slots=True)
class RenderTrack:
    activity_id: str
    name: str
    segments: tuple[tuple[ProjectedPoint, ...], ...]


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

    invalid_end_indexes = {
        segment.end_index for segment in track.segments if not segment.valid
    }
    for index, point in enumerate(track.points):
        if (
            previous is not None
            and (
                index in invalid_end_indexes
                or haversine_distance_meters(previous, point)
                > max_segment_distance_meters
            )
        ):
            if len(current) >= 2:
                segments.append(tuple(current))
            current = []

        current.append(project_point(point))
        previous = point

    if len(current) >= 2:
        segments.append(tuple(current))
    return tuple(segments)


def track_label_anchor(track: RenderTrack) -> ProjectedPoint | None:
    points = [point for segment in track.segments for point in segment]
    if not points:
        return None
    return ProjectedPoint(
        x=min(point.x for point in points),
        y=max(point.y for point in points),
    )
