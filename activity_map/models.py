from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TrackPoint:
    latitude: float
    longitude: float
    timestamp: datetime | None = None
    altitude_meters: float | None = None


@dataclass(frozen=True, slots=True)
class TrackBounds:
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    @property
    def width(self) -> float:
        return self.max_longitude - self.min_longitude

    @property
    def height(self) -> float:
        return self.max_latitude - self.min_latitude


@dataclass(frozen=True, slots=True)
class TrackSegment:
    start_index: int
    end_index: int
    distance_meters: float
    duration_seconds: float | None
    speed_kmh: float | None
    valid: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityTrack:
    activity_id: str
    name: str
    source_file: Path
    points: tuple[TrackPoint, ...]
    segments: tuple[TrackSegment, ...] = ()
    validation_messages: tuple[str, ...] = ()
    total_distance_meters: float = 0.0
    duration_seconds: float | None = None
    bounds: TrackBounds | None = None


@dataclass(frozen=True, slots=True)
class LoadWarning:
    source_file: Path
    message: str


@dataclass(frozen=True, slots=True)
class LoadReport:
    root: Path
    files_read: int
    tracks: tuple[ActivityTrack, ...]
    warnings: tuple[LoadWarning, ...]

    @property
    def files_skipped(self) -> int:
        return len(self.warnings)

    @property
    def point_count(self) -> int:
        return sum(len(track.points) for track in self.tracks)

    @property
    def validation_issue_count(self) -> int:
        return sum(len(track.validation_messages) for track in self.tracks)
