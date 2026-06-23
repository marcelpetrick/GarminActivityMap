from __future__ import annotations

from pathlib import Path

import pytest

from activity_map.geo import ProjectedPoint, Viewport
from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import ProjectedBounds, prepare_tracks
from activity_map.spatial import TrackSpatialIndex, viewport_bounds


def make_track(activity_id: str, latitude: float, longitude: float) -> ActivityTrack:
    return ActivityTrack(
        activity_id=activity_id,
        name=activity_id,
        source_file=Path(f"{activity_id}.json"),
        points=(
            TrackPoint(latitude, longitude),
            TrackPoint(latitude + 0.001, longitude + 0.001),
            TrackPoint(latitude + 0.002, longitude + 0.002),
        ),
    )


def test_spatial_index_returns_only_intersecting_tracks() -> None:
    tracks = prepare_tracks(
        (
            make_track("berlin", 52.5, 13.4),
            make_track("sydney", -33.8, 151.2),
        )
    )
    index = TrackSpatialIndex.build(tracks, grid_size=32)

    visible = index.query(tracks[0].bounds)

    assert visible == (0,)


def test_spatial_index_deduplicates_tracks_spanning_multiple_cells() -> None:
    tracks = prepare_tracks((make_track("wide", 40.0, -20.0),))
    index = TrackSpatialIndex.build(tracks, grid_size=256)

    visible = index.query(ProjectedBounds(0.0, 1.0, 0.0, 1.0))

    assert visible == (0,)


def test_viewport_bounds_includes_configured_screen_margin() -> None:
    viewport = Viewport(ProjectedPoint(0.5, 0.5), 1_000.0, 800, 600)

    bounds = viewport_bounds(viewport, margin_pixels=10.0)

    assert bounds.min_x == pytest.approx(0.09)
    assert bounds.max_x == pytest.approx(0.91)
    assert bounds.min_y == pytest.approx(0.19)
    assert bounds.max_y == pytest.approx(0.81)
