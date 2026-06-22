from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .geo import haversine_distance_meters
from .models import ActivityTrack, LoadReport, LoadWarning, TrackPoint, TrackSegment

LATITUDE_KEYS = frozenset(
    {
        "lat",
        "latitude",
        "positionLat",
        "positionLatitude",
        "startLatitude",
        "endLatitude",
    }
)
LONGITUDE_KEYS = frozenset(
    {
        "lon",
        "lng",
        "longitude",
        "positionLong",
        "positionLon",
        "positionLongitude",
        "startLongitude",
        "endLongitude",
    }
)
LATITUDE_METRIC_KEYS = frozenset({"directLatitude", "enhancedLatitude", "latitude"})
LONGITUDE_METRIC_KEYS = frozenset(
    {"directLongitude", "enhancedLongitude", "longitude"}
)
SEMICIRCLE_FACTOR = 180.0 / 2**31
MIN_SEMICIRCLE_ABS = 1_000_000.0
TIMESTAMP_KEYS = (
    "timestamp",
    "time",
    "startTimeGMT",
    "startTimeLocal",
    "calendarEventInfo",
)
TIMESTAMP_METRIC_KEYS = frozenset(
    {"directTimestamp", "timestamp", "activityTimestamp"}
)
DEFAULT_MAX_SEGMENT_SPEED_KMH = 30.0


def load_directory(
    root: Path,
    max_speed_kmh: float = DEFAULT_MAX_SEGMENT_SPEED_KMH,
) -> LoadReport:
    warnings: list[LoadWarning] = []
    tracks: list[ActivityTrack] = []
    files_read = 0

    if not root.exists():
        return LoadReport(
            root=root,
            files_read=0,
            tracks=(),
            warnings=(LoadWarning(root, "Directory does not exist"),),
        )

    for file_path in sorted(root.rglob("*.json")):
        if file_path.name == "manifest.json":
            continue
        files_read += 1
        try:
            track = load_activity_file(file_path, max_speed_kmh=max_speed_kmh)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(LoadWarning(file_path, str(exc)))
            continue

        if track is None:
            warnings.append(LoadWarning(file_path, "No track points found"))
            continue
        tracks.append(track)

    return LoadReport(
        root=root,
        files_read=files_read,
        tracks=tuple(tracks),
        warnings=tuple(warnings),
    )


def load_activity_file(
    file_path: Path,
    max_speed_kmh: float = DEFAULT_MAX_SEGMENT_SPEED_KMH,
) -> ActivityTrack | None:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Activity file must contain a JSON object")

    points = tuple(extract_track_points(payload))
    if not points:
        return None

    segments, validation_messages = validate_segments(points, max_speed_kmh)
    return ActivityTrack(
        activity_id=find_activity_id(payload) or file_path.stem,
        name=find_activity_name(payload) or file_path.stem,
        source_file=file_path,
        points=points,
        segments=segments,
        validation_messages=validation_messages,
    )


def extract_track_points(payload: Mapping[str, Any]) -> list[TrackPoint]:
    points: list[TrackPoint] = []

    points.extend(extract_polyline_points(payload))
    points.extend(extract_metric_points(payload))

    if not points:
        points.extend(extract_coordinate_dicts(payload))

    return deduplicate_adjacent(points)


def extract_polyline_points(payload: Mapping[str, Any]) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for container in walk_mappings(payload):
        polyline = container.get("polyline")
        if isinstance(polyline, Sequence) and not isinstance(polyline, str | bytes):
            points.extend(point for point in parse_point_sequence(polyline) if point)
    return points


def extract_metric_points(payload: Mapping[str, Any]) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for container in walk_mappings(payload):
        descriptors = container.get("metricDescriptors")
        rows = container.get("activityDetailMetrics")
        if not isinstance(descriptors, Sequence) or not isinstance(rows, Sequence):
            continue

        latitude_index = find_metric_index(descriptors, LATITUDE_METRIC_KEYS)
        longitude_index = find_metric_index(descriptors, LONGITUDE_METRIC_KEYS)
        timestamp_index = find_metric_index(descriptors, TIMESTAMP_METRIC_KEYS)
        if latitude_index is None or longitude_index is None:
            continue

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            metrics = row.get("metrics")
            if not isinstance(metrics, Sequence):
                continue
            points.extend(
                parse_metric_row(
                    metrics,
                    latitude_index,
                    longitude_index,
                    timestamp_index,
                )
            )
    return points


def extract_coordinate_dicts(payload: Mapping[str, Any]) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for item in walk_mappings(payload):
        point = parse_coordinate_mapping(item)
        if point is not None:
            points.append(point)
    return points


def parse_point_sequence(values: Sequence[Any]) -> Iterator[TrackPoint | None]:
    for item in values:
        if isinstance(item, Mapping):
            yield parse_coordinate_mapping(item)
        elif (
            isinstance(item, Sequence)
            and not isinstance(item, str | bytes)
            and len(item) >= 2
        ):
            yield make_point(item[0], item[1])


def parse_metric_row(
    metrics: Sequence[Any],
    latitude_index: int,
    longitude_index: int,
    timestamp_index: int | None = None,
) -> list[TrackPoint]:
    if latitude_index >= len(metrics) or longitude_index >= len(metrics):
        return []
    timestamp = (
        metrics[timestamp_index]
        if timestamp_index is not None and timestamp_index < len(metrics)
        else None
    )
    point = make_point(
        metrics[latitude_index],
        metrics[longitude_index],
        timestamp,
    )
    return [] if point is None else [point]


def parse_coordinate_mapping(item: Mapping[str, Any]) -> TrackPoint | None:
    latitude = first_value_for_keys(item, LATITUDE_KEYS)
    longitude = first_value_for_keys(item, LONGITUDE_KEYS)
    if latitude is None or longitude is None:
        return None
    return make_point(latitude, longitude, first_value_for_keys(item, TIMESTAMP_KEYS))


def make_point(
    latitude_value: Any,
    longitude_value: Any,
    timestamp_value: Any = None,
) -> TrackPoint | None:
    latitude = normalize_coordinate(latitude_value, "latitude")
    longitude = normalize_coordinate(longitude_value, "longitude")
    if latitude is None or longitude is None:
        return None
    return TrackPoint(
        latitude=latitude,
        longitude=longitude,
        timestamp=parse_timestamp(timestamp_value),
    )


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        seconds = float(value)
        if abs(seconds) > 10_000_000_000:
            seconds /= 1_000.0
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def validate_segments(
    points: Sequence[TrackPoint],
    max_speed_kmh: float = DEFAULT_MAX_SEGMENT_SPEED_KMH,
) -> tuple[tuple[TrackSegment, ...], tuple[str, ...]]:
    segments: list[TrackSegment] = []
    messages: list[str] = []
    missing_timestamps = 0
    for index, (start, end) in enumerate(zip(points, points[1:], strict=False)):
        distance = haversine_distance_meters(start, end)
        duration: float | None = None
        speed: float | None = None
        valid = True
        reason: str | None = None
        if start.timestamp is None or end.timestamp is None:
            missing_timestamps += 1
        else:
            duration = (end.timestamp - start.timestamp).total_seconds()
            if duration <= 0:
                valid = False
                reason = "timestamps are duplicated or out of order"
            else:
                speed = distance / duration * 3.6
                if speed > max_speed_kmh:
                    valid = False
                    reason = (
                        f"implied speed {speed:.1f} km/h exceeds "
                        f"{max_speed_kmh:g} km/h"
                    )
        if reason is not None:
            messages.append(f"Segment {index}-{index + 1}: {reason}")
        segments.append(
            TrackSegment(
                start_index=index,
                end_index=index + 1,
                distance_meters=distance,
                duration_seconds=duration,
                speed_kmh=speed,
                valid=valid,
                reason=reason,
            )
        )
    if missing_timestamps:
        messages.append(
            f"{missing_timestamps} segment(s) could not be speed-checked "
            "because timestamps are missing"
        )
    return tuple(segments), tuple(messages)


def normalize_coordinate(value: Any, axis: str) -> float | None:
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(coordinate):
        return None

    limit = 90.0 if axis == "latitude" else 180.0
    if abs(coordinate) <= limit:
        return coordinate

    semicircle_coordinate = coordinate * SEMICIRCLE_FACTOR
    if abs(coordinate) >= MIN_SEMICIRCLE_ABS and abs(semicircle_coordinate) <= limit:
        return semicircle_coordinate

    return None


def find_metric_index(
    descriptors: Sequence[Any], accepted_keys: frozenset[str]
) -> int | None:
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            continue
        key = descriptor.get("key") or descriptor.get("metricKey")
        index = descriptor.get("metricsIndex")
        if index is None:
            index = descriptor.get("index")
        if key in accepted_keys and isinstance(index, int):
            return index
    return None


def find_activity_id(payload: Mapping[str, Any]) -> str | None:
    for container in walk_mappings(payload):
        for key in ("activityId", "activity_id", "id"):
            value = container.get(key)
            if value:
                return str(value)
    return None


def find_activity_name(payload: Mapping[str, Any]) -> str | None:
    for container in walk_mappings(payload):
        for key in ("activityName", "name", "activityTitle"):
            value = container.get(key)
            if value:
                return str(value)
    return None


def first_value_for_keys(item: Mapping[str, Any], keys: Iterable[str]) -> Any | None:
    for key in keys:
        if key in item:
            return item[key]
    return None


def walk_mappings(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from walk_mappings(child)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for child in value:
            yield from walk_mappings(child)


def deduplicate_adjacent(points: Iterable[TrackPoint]) -> list[TrackPoint]:
    deduplicated: list[TrackPoint] = []
    for point in points:
        if deduplicated and deduplicated[-1] == point:
            continue
        deduplicated.append(point)
    return deduplicated
