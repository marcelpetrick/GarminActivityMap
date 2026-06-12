from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TrackPoint:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class ActivityTrack:
    activity_id: str
    name: str
    source_file: Path
    points: tuple[TrackPoint, ...]


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
