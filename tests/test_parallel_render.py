from __future__ import annotations

from pathlib import Path

from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import prepare_tracks, prepare_tracks_parallel


def track(activity_id: str) -> ActivityTrack:
    return ActivityTrack(
        activity_id=activity_id,
        name=activity_id,
        source_file=Path(f"{activity_id}.json"),
        points=(
            TrackPoint(52.0, 13.0),
            TrackPoint(52.001, 13.001),
            TrackPoint(52.002, 13.002),
        ),
    )


def test_parallel_preparation_preserves_serial_order_and_geometry() -> None:
    tracks = tuple(track(str(index)) for index in range(8))

    serial = prepare_tracks(tracks)
    parallel = prepare_tracks_parallel(tracks, workers=2)

    assert parallel == serial


def test_parallel_preparation_handles_empty_and_single_worker_paths() -> None:
    tracks = (track("one"),)

    assert prepare_tracks_parallel((), workers=2) == ()
    assert prepare_tracks_parallel(tracks, workers=1) == prepare_tracks(tracks)
