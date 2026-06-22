from __future__ import annotations

import math
from dataclasses import dataclass

from .geo import ProjectedPoint, haversine_distance_meters, project_point
from .models import ActivityTrack, TrackPoint


@dataclass(frozen=True, slots=True)
class RenderTrack:
    activity_id: str
    name: str
    segments: tuple[tuple[ProjectedPoint, ...], ...]
    simplified_segments: tuple[tuple[ProjectedPoint, ...], ...]
    marker: ProjectedPoint


MAX_CONTINUOUS_SEGMENT_METERS = 5_000.0
MIN_RENDERED_TRACK_POINTS = 3
MARKER_MAX_ZOOM = 8_000.0
SIMPLIFIED_MAX_ZOOM = 120_000.0
SIMPLIFICATION_TOLERANCE = 0.00002


@dataclass(frozen=True, slots=True)
class RenderGeometry:
    polylines: tuple[tuple[ProjectedPoint, ...], ...]
    markers: tuple[ProjectedPoint, ...] = ()


def prepare_tracks(
    tracks: tuple[ActivityTrack, ...],
    max_segment_distance_meters: float = MAX_CONTINUOUS_SEGMENT_METERS,
) -> tuple[RenderTrack, ...]:
    return tuple(
        prepare_track(track, max_segment_distance_meters)
        for track in tracks
        if len(track.points) >= MIN_RENDERED_TRACK_POINTS
    )


def prepare_track(
    track: ActivityTrack,
    max_segment_distance_meters: float,
) -> RenderTrack:
    segments = split_projected_segments(track, max_segment_distance_meters)
    simplified = tuple(
        simplify_polyline(segment, SIMPLIFICATION_TOLERANCE) for segment in segments
    )
    marker = project_point(
        TrackPoint(
            latitude=sum(point.latitude for point in track.points) / len(track.points),
            longitude=(
                sum(point.longitude for point in track.points) / len(track.points)
            ),
        )
    )
    return RenderTrack(
        activity_id=track.activity_id,
        name=track.name,
        segments=segments,
        simplified_segments=simplified,
        marker=marker,
    )


def geometry_for_zoom(track: RenderTrack, zoom: float) -> RenderGeometry:
    if zoom <= MARKER_MAX_ZOOM:
        return RenderGeometry(polylines=(), markers=(track.marker,))
    if zoom <= SIMPLIFIED_MAX_ZOOM:
        return RenderGeometry(polylines=track.simplified_segments)
    return RenderGeometry(polylines=track.segments)


def simplify_polyline(
    points: tuple[ProjectedPoint, ...],
    tolerance: float,
) -> tuple[ProjectedPoint, ...]:
    if len(points) <= 2:
        return points
    start = points[0]
    end = points[-1]
    furthest_index = 0
    furthest_distance = 0.0
    for index, point in enumerate(points[1:-1], start=1):
        distance = perpendicular_distance(point, start, end)
        if distance > furthest_distance:
            furthest_index = index
            furthest_distance = distance
    if furthest_distance <= tolerance:
        return (start, end)
    left = simplify_polyline(points[: furthest_index + 1], tolerance)
    right = simplify_polyline(points[furthest_index:], tolerance)
    return left[:-1] + right


def perpendicular_distance(
    point: ProjectedPoint,
    start: ProjectedPoint,
    end: ProjectedPoint,
) -> float:
    delta_x = end.x - start.x
    delta_y = end.y - start.y
    if delta_x == 0 and delta_y == 0:
        return math.hypot(point.x - start.x, point.y - start.y)
    numerator = abs(
        delta_y * point.x - delta_x * point.y + end.x * start.y - end.y * start.x
    )
    return numerator / math.hypot(delta_x, delta_y)


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
        if previous is not None and (
            index in invalid_end_indexes
            or haversine_distance_meters(previous, point) > max_segment_distance_meters
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
