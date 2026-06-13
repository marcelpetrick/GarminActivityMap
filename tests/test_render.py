from pathlib import Path

from activity_map.geo import project_point
from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import (
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
