from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .loader import load_directory_parallel
from .models import LoadReport
from .render import RenderTrack, prepare_tracks_parallel


@dataclass(frozen=True, slots=True)
class PreparedLoad:
    report: LoadReport
    render_tracks: tuple[RenderTrack, ...]


def load_and_prepare_directory(
    path: Path,
    loader_workers: int = 1,
    preparation_workers: int = 1,
) -> PreparedLoad:
    report = load_directory_parallel(path, workers=loader_workers)
    return PreparedLoad(
        report=report,
        render_tracks=prepare_tracks_parallel(
            report.tracks,
            workers=preparation_workers,
        ),
    )
