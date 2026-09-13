from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .loader import CancellationCheck, load_directory_parallel, raise_if_cancelled
from .models import ActivityTrack, LoadReport
from .prepared_cache import DatasetFingerprint, PreparedGeometryCache
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
    cancelled: CancellationCheck | None = None,
) -> PreparedLoad:
    raise_if_cancelled(cancelled)
    cache = PreparedGeometryCache()
    fingerprint = safe_fingerprint(cache, path)
    raise_if_cancelled(cancelled)
    if fingerprint is not None:
        cached = cache.load(path, fingerprint)
        raise_if_cancelled(cancelled)
        if cached is not None and safe_fingerprint(cache, path) == fingerprint:
            result = PreparedLoad(*cached)
            if progress is not None:
                progress(result)
            return result

    prepared: list[RenderTrack] = []

    def prepare_progress(
        report: LoadReport,
        track_batch: tuple[ActivityTrack, ...],
    ) -> None:
        raise_if_cancelled(cancelled)
        render_batch = prepare_tracks_parallel(
            track_batch,
            workers=preparation_workers,
        )
        prepared.extend(render_batch)
        raise_if_cancelled(cancelled)
        if progress is not None:
            progress(PreparedLoad(report, render_batch))

    report = load_directory_parallel(
        path,
        workers=loader_workers,
        progress=prepare_progress if progress is not None else None,
        cancelled=cancelled,
    )
    raise_if_cancelled(cancelled)
    if progress is not None:
        result = PreparedLoad(report=report, render_tracks=tuple(prepared))
    else:
        result = PreparedLoad(
            report=report,
            render_tracks=prepare_tracks_parallel(
                report.tracks,
                workers=preparation_workers,
            ),
        )
    raise_if_cancelled(cancelled)
    if fingerprint is not None and safe_fingerprint(cache, path) == fingerprint:
        raise_if_cancelled(cancelled)
        with suppress(OSError, TypeError, ValueError):
            cache.save(path, fingerprint, result.report, result.render_tracks)
    return result


def safe_fingerprint(
    cache: PreparedGeometryCache,
    path: Path,
) -> DatasetFingerprint | None:
    if not path.is_dir():
        return None
    try:
        return cache.fingerprint(path)
    except OSError:
        return None
