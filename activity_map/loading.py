from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .loader import load_directory_parallel
from .models import ActivityTrack, LoadReport
from .render import RenderTrack, prepare_tracks_parallel


@dataclass(frozen=True, slots=True)
class PreparedLoad:
    report: LoadReport
    render_tracks: tuple[RenderTrack, ...]


def load_and_prepare_directory(
    path: Path,
    loader_workers: int = 1,
    preparation_workers: int = 1,
    progress: Callable[[PreparedLoad], None] | None = None,
) -> PreparedLoad:
    prepared: list[RenderTrack] = []

    def prepare_progress(
        report: LoadReport,
        track_batch: tuple[ActivityTrack, ...],
    ) -> None:
        render_batch = prepare_tracks_parallel(
            track_batch,
            workers=preparation_workers,
        )
        prepared.extend(render_batch)
        if progress is not None:
            progress(PreparedLoad(report, render_batch))

    report = load_directory_parallel(
        path,
        workers=loader_workers,
        progress=prepare_progress if progress is not None else None,
    )
    if progress is not None:
        return PreparedLoad(report=report, render_tracks=tuple(prepared))
    return PreparedLoad(
        report=report,
        render_tracks=prepare_tracks_parallel(
            report.tracks,
            workers=preparation_workers,
        ),
    )
