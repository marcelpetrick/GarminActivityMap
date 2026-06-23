from __future__ import annotations

import math
from pathlib import Path

from activity_map.lod import select_lod
from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import prepare_tracks


def dense_track(activity_id: str) -> ActivityTrack:
    return ActivityTrack(
        activity_id=activity_id,
        name=activity_id,
        source_file=Path(f"{activity_id}.json"),
        points=tuple(
            TrackPoint(
                52.5 + index * 0.000002,
                13.4 + index * 0.0000025 + ((index % 20) - 10) * 0.000003,
            )
            for index in range(300)
        ),
    )


def curved_track(activity_id: str) -> ActivityTrack:
    return ActivityTrack(
        activity_id=activity_id,
        name=activity_id,
        source_file=Path(f"{activity_id}.json"),
        points=tuple(
            TrackPoint(
                52.5 + index * 0.00001,
                13.4 + index * 0.00001 + math.sin(index / 4.0) * 0.002,
            )
            for index in range(300)
        ),
    )


def test_lod_uses_finer_geometry_as_zoom_increases() -> None:
    tracks = prepare_tracks((dense_track("one"),))

    intermediate = select_lod(tracks, (0,), zoom=120_000.0)
    detailed = select_lod(tracks, (0,), zoom=2_000_000.0)

    assert detailed.level_index > intermediate.level_index
    assert detailed.tolerance_world < intermediate.tolerance_world


def test_lod_coarsens_geometry_to_respect_vertex_budget() -> None:
    tracks = prepare_tracks(tuple(curved_track(str(index)) for index in range(20)))
    visible = tuple(range(len(tracks)))

    unrestricted = select_lod(
        tracks, visible, zoom=1_000_000.0, vertex_budget=1_000_000
    )
    restricted = select_lod(tracks, visible, zoom=1_000_000.0, vertex_budget=100)

    assert restricted.level_index < unrestricted.level_index
    assert restricted.point_count <= unrestricted.point_count


def test_lod_handles_empty_visibility() -> None:
    assert select_lod((), (), zoom=1_000.0).point_count == 0
