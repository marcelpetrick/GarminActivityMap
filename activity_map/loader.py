from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .models import ActivityTrack, LoadReport, LoadWarning, TrackPoint

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


def load_directory(root: Path) -> LoadReport:
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
            track = load_activity_file(file_path)
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


def load_activity_file(file_path: Path) -> ActivityTrack | None:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Activity file must contain a JSON object")

    points = tuple(extract_track_points(payload))
    if not points:
        return None

    return ActivityTrack(
        activity_id=find_activity_id(payload) or file_path.stem,
        name=find_activity_name(payload) or file_path.stem,
        source_file=file_path,
        points=points,
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
        if latitude_index is None or longitude_index is None:
            continue

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            metrics = row.get("metrics")
            if not isinstance(metrics, Sequence):
                continue
            points.extend(parse_metric_row(metrics, latitude_index, longitude_index))
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
    metrics: Sequence[Any], latitude_index: int, longitude_index: int
) -> list[TrackPoint]:
    if latitude_index >= len(metrics) or longitude_index >= len(metrics):
        return []
    point = make_point(metrics[latitude_index], metrics[longitude_index])
    return [] if point is None else [point]


def parse_coordinate_mapping(item: Mapping[str, Any]) -> TrackPoint | None:
    latitude = first_value_for_keys(item, LATITUDE_KEYS)
    longitude = first_value_for_keys(item, LONGITUDE_KEYS)
    if latitude is None or longitude is None:
        return None
    return make_point(latitude, longitude)


def make_point(latitude_value: Any, longitude_value: Any) -> TrackPoint | None:
    latitude = normalize_coordinate(latitude_value, "latitude")
    longitude = normalize_coordinate(longitude_value, "longitude")
    if latitude is None or longitude is None:
        return None
    return TrackPoint(latitude=latitude, longitude=longitude)


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
        index = descriptor.get("metricsIndex") or descriptor.get("index")
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
