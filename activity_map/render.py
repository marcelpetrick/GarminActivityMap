from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date

from .geo import ProjectedPoint, haversine_distance_meters, project_point
from .models import ActivityTrack, TrackPoint


@dataclass(frozen=True, slots=True)
class ProjectedBounds:
    min_x: float
    max_x: float
    min_y: float
    max_y: float

    def intersects(self, other: ProjectedBounds) -> bool:
        return not (
            self.max_x < other.min_x
            or self.min_x > other.max_x
            or self.max_y < other.min_y
            or self.min_y > other.max_y
        )


@dataclass(frozen=True, slots=True)
class RenderLevel:
    tolerance_world: float
    segments: tuple[tuple[ProjectedPoint, ...], ...]
    point_count: int


@dataclass(frozen=True, slots=True)
class RenderTrack:
    activity_id: str
    name: str
    segments: tuple[tuple[ProjectedPoint, ...], ...]
    simplified_segments: tuple[tuple[ProjectedPoint, ...], ...]
    marker: ProjectedPoint
    label_anchor: ProjectedPoint | None
    bounds: ProjectedBounds
    levels: tuple[RenderLevel, ...]
    start_date: date | None = None


MAX_CONTINUOUS_SEGMENT_METERS = 5_000.0
MIN_RENDERED_TRACK_POINTS = 3
MARKER_MAX_ZOOM = 8_000.0
SIMPLIFIED_MAX_ZOOM = 120_000.0
SIMPLIFICATION_TOLERANCE = 0.00002
LOD_TOLERANCES = (0.00008, SIMPLIFICATION_TOLERANCE, 0.000005, 0.000001)


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


def prepare_tracks_parallel(
    tracks: tuple[ActivityTrack, ...],
    max_segment_distance_meters: float = MAX_CONTINUOUS_SEGMENT_METERS,
    workers: int | None = None,
) -> tuple[RenderTrack, ...]:
    eligible = tuple(
        track for track in tracks if len(track.points) >= MIN_RENDERED_TRACK_POINTS
    )
    if not eligible:
        return ()
    worker_count = workers or min(max(os.cpu_count() or 1, 1), 4)
    worker_count = min(max(worker_count, 1), len(eligible))
    if worker_count == 1:
        return prepare_tracks(eligible, max_segment_distance_meters)
    chunk_size = math.ceil(len(eligible) / worker_count)
    chunks = tuple(
        (eligible[start : start + chunk_size], max_segment_distance_meters)
        for start in range(0, len(eligible), chunk_size)
    )
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        prepared_chunks = executor.map(prepare_track_chunk, chunks)
        return tuple(track for chunk in prepared_chunks for track in chunk)


def prepare_track_chunk(
    work: tuple[tuple[ActivityTrack, ...], float],
) -> tuple[RenderTrack, ...]:
    tracks, max_segment_distance_meters = work
    return tuple(prepare_track(track, max_segment_distance_meters) for track in tracks)


def prepare_track(
    track: ActivityTrack,
    max_segment_distance_meters: float,
) -> RenderTrack:
    segments = split_projected_segments(track, max_segment_distance_meters)
    levels = prepare_levels(segments)
    simplified = next(
        level.segments
        for level in levels
        if level.tolerance_world == SIMPLIFICATION_TOLERANCE
    )
    latitude_sum = 0.0
    longitude_sum = 0.0
    for point in track.points:
        latitude_sum += point.latitude
        longitude_sum += point.longitude
    marker = project_point(
        TrackPoint(
            latitude=latitude_sum / len(track.points),
            longitude=longitude_sum / len(track.points),
        )
    )
    bounds = projected_bounds(segments)
    if bounds is None:
        bounds = ProjectedBounds(marker.x, marker.x, marker.y, marker.y)
        label_anchor = None
    else:
        label_anchor = ProjectedPoint(bounds.min_x, bounds.max_y)
    return RenderTrack(
        activity_id=track.activity_id,
        name=track.name,
        segments=segments,
        simplified_segments=simplified,
        marker=marker,
        label_anchor=label_anchor,
        bounds=bounds,
        levels=levels,
        start_date=activity_start_date(track),
    )


def activity_start_date(track: ActivityTrack) -> date | None:
    timestamp = track.start_timestamp
    return None if timestamp is None else timestamp.date()


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
    retained_indexes = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        start_index, end_index = pending.pop()
        start = points[start_index]
        end = points[end_index]
        furthest_index = start_index
        furthest_distance = 0.0
        for index in range(start_index + 1, end_index):
            distance = perpendicular_distance(points[index], start, end)
            if distance > furthest_distance:
                furthest_index = index
                furthest_distance = distance
        if furthest_distance <= tolerance:
            continue
        retained_indexes.add(furthest_index)
        pending.append((start_index, furthest_index))
        pending.append((furthest_index, end_index))
    return tuple(points[index] for index in sorted(retained_indexes))


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

    validated_segments = len(track.segments) == max(len(track.points) - 1, 0)
    break_end_indexes = (
        {
            segment.end_index
            for segment in track.segments
            if not segment.valid
            or segment.distance_meters > max_segment_distance_meters
        }
        if validated_segments
        else set()
    )
    for index, point in enumerate(track.points):
        if previous is not None and (
            index in break_end_indexes
            or (
                not validated_segments
                and haversine_distance_meters(previous, point)
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
    return track.label_anchor


def projected_bounds(
    segments: tuple[tuple[ProjectedPoint, ...], ...],
) -> ProjectedBounds | None:
    points = (point for segment in segments for point in segment)
    first = next(points, None)
    if first is None:
        return None
    min_x = max_x = first.x
    min_y = max_y = first.y
    for point in points:
        min_x = min(min_x, point.x)
        max_x = max(max_x, point.x)
        min_y = min(min_y, point.y)
        max_y = max(max_y, point.y)
    return ProjectedBounds(
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
    )


def prepare_levels(
    segments: tuple[tuple[ProjectedPoint, ...], ...],
) -> tuple[RenderLevel, ...]:
    finest_tolerance = min(LOD_TOLERANCES)
    finest_segments = tuple(
        simplify_polyline(segment, finest_tolerance) for segment in segments
    )
    levels: list[RenderLevel] = []
    for tolerance in LOD_TOLERANCES:
        level_segments = (
            finest_segments
            if tolerance == finest_tolerance
            else tuple(
                simplify_polyline(segment, tolerance) for segment in finest_segments
            )
        )
        levels.append(
            RenderLevel(
                tolerance_world=tolerance,
                segments=level_segments,
                point_count=sum(len(segment) for segment in level_segments),
            )
        )
    levels.append(
        RenderLevel(
            tolerance_world=0.0,
            segments=segments,
            point_count=sum(len(segment) for segment in segments),
        )
    )
    return tuple(levels)


def combined_projected_bounds(
    tracks: tuple[RenderTrack, ...],
) -> ProjectedBounds | None:
    if not tracks:
        return None
    return ProjectedBounds(
        min_x=min(track.bounds.min_x for track in tracks),
        max_x=max(track.bounds.max_x for track in tracks),
        min_y=min(track.bounds.min_y for track in tracks),
        max_y=max(track.bounds.max_y for track in tracks),
    )
