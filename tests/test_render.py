from pathlib import Path

import pytest

from activity_map.geo import project_point
from activity_map.heat import HeatCell
from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import (
    prepare_heat_cells,
    prepare_tracks,
    split_projected_segments,
)


def test_prepare_tracks_projects_track_points_once() -> None:
    track = ActivityTrack(
        activity_id="1",
        name="Synthetic",
        source_file=Path("synthetic.json"),
        points=(
            TrackPoint(latitude=0.0, longitude=0.0),
            TrackPoint(latitude=0.01, longitude=0.01),
            TrackPoint(latitude=0.02, longitude=0.02),
        ),
    )

    prepared = prepare_tracks((track,))

    assert len(prepared) == 1
    assert prepared[0].activity_id == "1"
    assert prepared[0].name == "Synthetic"
    assert prepared[0].segments == (
        (
            project_point(TrackPoint(latitude=0.0, longitude=0.0)),
            project_point(TrackPoint(latitude=0.01, longitude=0.01)),
            project_point(TrackPoint(latitude=0.02, longitude=0.02)),
        ),
    )


def test_prepare_tracks_ignores_two_point_summary_only_tracks() -> None:
    track = ActivityTrack(
        activity_id="summary",
        name="Summary",
        source_file=Path("summary.json"),
        points=(
            TrackPoint(latitude=52.0, longitude=13.0),
            TrackPoint(latitude=53.0, longitude=14.0),
        ),
    )

    assert prepare_tracks((track,)) == ()


def test_split_projected_segments_breaks_large_gps_jumps() -> None:
    track = ActivityTrack(
        activity_id="jump",
        name="Jump",
        source_file=Path("jump.json"),
        points=(
            TrackPoint(latitude=52.0, longitude=13.0),
            TrackPoint(latitude=52.001, longitude=13.001),
            TrackPoint(latitude=60.0, longitude=20.0),
            TrackPoint(latitude=60.001, longitude=20.001),
        ),
    )

    segments = split_projected_segments(track, max_segment_distance_meters=5_000)

    assert len(segments) == 2
    assert all(len(segment) == 2 for segment in segments)


def test_prepare_heat_cells_projects_grid_centers() -> None:
    prepared = prepare_heat_cells(
        (
            HeatCell(x_index=10, y_index=20, count=4, intensity=1.0),
            HeatCell(x_index=11, y_index=20, count=2, intensity=0.5),
        ),
        cell_size=0.01,
    )

    assert prepared[0].center.x == pytest.approx(0.105)
    assert prepared[0].center.y == pytest.approx(0.205)
    assert prepared[0].count == 4
    assert prepared[0].intensity == 1.0
    assert prepared[1].center.x == pytest.approx(0.115)
    assert prepared[1].center.y == pytest.approx(0.205)
