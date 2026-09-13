from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .geo import ProjectedPoint
from .loader import ACTIVITY_SPEED_LIMITS_KMH, DEFAULT_MAX_SEGMENT_SPEED_KMH
from .models import (
    ActivityTrack,
    LoadReport,
    LoadWarning,
    TrackBounds,
    TrackPoint,
    TrackSegment,
)
from .render import (
    LOD_TOLERANCES,
    MAX_CONTINUOUS_SEGMENT_METERS,
    MIN_RENDERED_TRACK_POINTS,
    SIMPLIFICATION_TOLERANCE,
    ProjectedBounds,
    RenderLevel,
    RenderTrack,
)

CACHE_SCHEMA_VERSION = 3
CACHE_DIRECTORY_ENVIRONMENT = "ACTIVITY_MAP_PREPARED_CACHE_DIR"
CACHE_DISABLED_ENVIRONMENT = "ACTIVITY_MAP_DISABLE_PREPARED_CACHE"

DatasetFingerprint = tuple[tuple[str, int, int], ...]
CachedPreparedLoad = tuple[LoadReport, tuple[RenderTrack, ...]]


class PreparedGeometryCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_cache_directory()).expanduser().resolve()

    @property
    def enabled(self) -> bool:
        return os.environ.get(CACHE_DISABLED_ENVIRONMENT) != "1"

    def fingerprint(self, dataset: Path) -> DatasetFingerprint:
        return tuple(
            (
                file_path.relative_to(dataset).as_posix(),
                metadata.st_size,
                metadata.st_mtime_ns,
            )
            for file_path in activity_files(dataset)
            if not file_path.is_relative_to(self.root)
            for metadata in (file_path.stat(),)
        )

    def load(
        self,
        dataset: Path,
        fingerprint: DatasetFingerprint,
    ) -> CachedPreparedLoad | None:
        if not self.enabled:
            return None
        try:
            value = json.loads(self.cache_path(dataset).read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema") != CACHE_SCHEMA_VERSION
                or value.get("parameters") != geometry_signature()
                or decode_fingerprint(value.get("fingerprint")) != fingerprint
            ):
                return None
            return decode_snapshot(dataset, value)
        except KeyError, OSError, TypeError, ValueError, json.JSONDecodeError:
            return None

    def save(
        self,
        dataset: Path,
        fingerprint: DatasetFingerprint,
        report: LoadReport,
        render_tracks: tuple[RenderTrack, ...],
    ) -> None:
        if not self.enabled:
            return
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = self.cache_path(dataset)
        payload = encode_snapshot(dataset, fingerprint, report, render_tracks)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{destination.name}.",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, separators=(",", ":"))
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o600)
            temporary_path.replace(destination)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        self.discard_outdated_snapshots(dataset)

    def cache_path(self, dataset: Path) -> Path:
        return self.root / f"{dataset_identity(dataset)}-{geometry_signature()}.json"

    def discard_outdated_snapshots(self, dataset: Path) -> None:
        current = self.cache_path(dataset)
        for path in self.root.glob(f"{dataset_identity(dataset)}-*.json"):
            if path != current:
                path.unlink(missing_ok=True)


def dataset_identity(dataset: Path) -> str:
    return hashlib.sha256(str(dataset.resolve()).encode("utf-8")).hexdigest()


def geometry_signature() -> str:
    parameters = {
        "schema": CACHE_SCHEMA_VERSION,
        "lod_tolerances": list(LOD_TOLERANCES),
        "simplification_tolerance": SIMPLIFICATION_TOLERANCE,
        "max_continuous_segment_meters": MAX_CONTINUOUS_SEGMENT_METERS,
        "min_rendered_track_points": MIN_RENDERED_TRACK_POINTS,
        "max_segment_speed_kmh": DEFAULT_MAX_SEGMENT_SPEED_KMH,
        "activity_speed_limits_kmh": ACTIVITY_SPEED_LIMITS_KMH,
    }
    encoded = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def default_cache_directory() -> Path:
    configured = os.environ.get(CACHE_DIRECTORY_ENVIRONMENT)
    if configured:
        return Path(configured)
    cache_home = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache_home) if cache_home else Path.home() / ".cache"
    return root / "GarminActivityMap" / "prepared"


def activity_files(dataset: Path) -> tuple[Path, ...]:
    return tuple(
        file_path
        for file_path in sorted(dataset.rglob("*.json"))
        if file_path.name != "manifest.json"
    )


def encode_snapshot(
    dataset: Path,
    fingerprint: DatasetFingerprint,
    report: LoadReport,
    render_tracks: tuple[RenderTrack, ...],
) -> dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "parameters": geometry_signature(),
        "fingerprint": fingerprint,
        "files_read": report.files_read,
        "warnings": [
            [relative_source(dataset, warning.source_file), warning.message]
            for warning in report.warnings
        ],
        "tracks": [encode_activity_track(dataset, track) for track in report.tracks],
        "render_tracks": [encode_render_track(track) for track in render_tracks],
    }


def decode_snapshot(
    dataset: Path,
    value: dict[str, Any],
) -> CachedPreparedLoad:
    warnings = tuple(
        decode_warning(dataset, require_list(item))
        for item in require_list(value["warnings"])
    )
    report = LoadReport(
        root=dataset,
        files_read=int(value["files_read"]),
        tracks=tuple(
            decode_activity_track(dataset, require_dict(item))
            for item in require_list(value["tracks"])
        ),
        warnings=warnings,
    )
    render_tracks = tuple(
        decode_render_track(require_dict(item))
        for item in require_list(value["render_tracks"])
    )
    return report, render_tracks


def decode_warning(dataset: Path, value: list[Any]) -> LoadWarning:
    if len(value) != 2:
        raise ValueError("warning must contain a source and message")
    return LoadWarning(source_path(dataset, str(value[0])), str(value[1]))


def encode_activity_track(dataset: Path, track: ActivityTrack) -> dict[str, Any]:
    return {
        "id": track.activity_id,
        "name": track.name,
        "source": relative_source(dataset, track.source_file),
        "points": [
            [
                point.latitude,
                point.longitude,
                point.timestamp.isoformat() if point.timestamp is not None else None,
                point.altitude_meters,
            ]
            for point in track.points
        ],
        "segments": [
            [
                segment.start_index,
                segment.end_index,
                segment.distance_meters,
                segment.duration_seconds,
                segment.speed_kmh,
                segment.valid,
                segment.reason,
            ]
            for segment in track.segments
        ],
        "validation": track.validation_messages,
        "distance": track.total_distance_meters,
        "duration": track.duration_seconds,
        "bounds": encode_track_bounds(track.bounds),
    }


def decode_activity_track(dataset: Path, value: dict[str, Any]) -> ActivityTrack:
    return ActivityTrack(
        activity_id=str(value["id"]),
        name=str(value["name"]),
        source_file=source_path(dataset, str(value["source"])),
        points=tuple(
            TrackPoint(
                latitude=float(item[0]),
                longitude=float(item[1]),
                timestamp=(
                    datetime.fromisoformat(item[2]) if item[2] is not None else None
                ),
                altitude_meters=(float(item[3]) if item[3] is not None else None),
            )
            for item in map(require_list, require_list(value["points"]))
        ),
        segments=tuple(
            TrackSegment(
                start_index=int(item[0]),
                end_index=int(item[1]),
                distance_meters=float(item[2]),
                duration_seconds=float(item[3]) if item[3] is not None else None,
                speed_kmh=float(item[4]) if item[4] is not None else None,
                valid=bool(item[5]),
                reason=str(item[6]) if item[6] is not None else None,
            )
            for item in map(require_list, require_list(value["segments"]))
        ),
        validation_messages=tuple(
            str(item) for item in require_list(value["validation"])
        ),
        total_distance_meters=float(value["distance"]),
        duration_seconds=(
            float(value["duration"]) if value["duration"] is not None else None
        ),
        bounds=decode_track_bounds(value["bounds"]),
    )


def encode_render_track(track: RenderTrack) -> dict[str, Any]:
    return {
        "id": track.activity_id,
        "name": track.name,
        "marker": [track.marker.x, track.marker.y],
        "anchor": (
            [track.label_anchor.x, track.label_anchor.y]
            if track.label_anchor is not None
            else None
        ),
        "start": (
            track.start_date.isoformat() if track.start_date is not None else None
        ),
        "bounds": [
            track.bounds.min_x,
            track.bounds.max_x,
            track.bounds.min_y,
            track.bounds.max_y,
        ],
        "levels": [
            [
                level.tolerance_world,
                [
                    [[point.x, point.y] for point in segment]
                    for segment in level.segments
                ],
                level.point_count,
            ]
            for level in track.levels
        ],
    }


def decode_render_track(value: dict[str, Any]) -> RenderTrack:
    levels = tuple(
        RenderLevel(
            tolerance_world=float(item[0]),
            segments=decode_projected_segments(item[1]),
            point_count=int(item[2]),
        )
        for item in map(require_list, require_list(value["levels"]))
    )
    marker = require_list(value["marker"])
    anchor_value = value["anchor"]
    bounds = require_list(value["bounds"])
    segments = levels[-1].segments
    simplified = next(
        level.segments
        for level in levels
        if level.tolerance_world == SIMPLIFICATION_TOLERANCE
    )
    return RenderTrack(
        activity_id=str(value["id"]),
        name=str(value["name"]),
        segments=segments,
        simplified_segments=simplified,
        marker=projected_point(marker),
        label_anchor=(
            projected_point(require_list(anchor_value))
            if anchor_value is not None
            else None
        ),
        bounds=ProjectedBounds(
            min_x=float(bounds[0]),
            max_x=float(bounds[1]),
            min_y=float(bounds[2]),
            max_y=float(bounds[3]),
        ),
        levels=levels,
        start_date=decode_start_date(value["start"]),
    )


def decode_start_date(value: Any) -> date | None:
    return None if value is None else date.fromisoformat(str(value))


def decode_projected_segments(
    value: Any,
) -> tuple[tuple[ProjectedPoint, ...], ...]:
    return tuple(
        tuple(projected_point(require_list(point)) for point in require_list(segment))
        for segment in require_list(value)
    )


def projected_point(value: list[Any]) -> ProjectedPoint:
    return ProjectedPoint(float(value[0]), float(value[1]))


def encode_track_bounds(bounds: TrackBounds | None) -> list[float] | None:
    if bounds is None:
        return None
    return [
        bounds.min_latitude,
        bounds.max_latitude,
        bounds.min_longitude,
        bounds.max_longitude,
    ]


def decode_track_bounds(value: Any) -> TrackBounds | None:
    if value is None:
        return None
    bounds = require_list(value)
    return TrackBounds(*(float(item) for item in bounds))


def decode_fingerprint(value: Any) -> DatasetFingerprint:
    return tuple(
        (str(item[0]), int(item[1]), int(item[2]))
        for item in map(require_list, require_list(value))
    )


def relative_source(dataset: Path, source: Path) -> str:
    try:
        return source.relative_to(dataset).as_posix()
    except ValueError:
        return str(source)


def source_path(dataset: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else dataset / path


def require_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected object")
    return value


def require_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("expected array")
    return value
