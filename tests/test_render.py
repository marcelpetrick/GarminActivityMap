from pathlib import Path

from activity_map.geo import project_point
from activity_map.models import ActivityTrack, TrackPoint, TrackSegment
from activity_map.render import (
    prepare_tracks,
    split_projected_segments,
    track_label_anchor,
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


def test_track_label_anchor_uses_lower_left_projected_track_corner() -> None:
    track = ActivityTrack(
        activity_id="label",
        name="Morning Ride",
        source_file=Path("label.json"),
        points=(
            TrackPoint(latitude=0.0, longitude=0.0),
            TrackPoint(latitude=0.01, longitude=0.02),
            TrackPoint(latitude=-0.01, longitude=0.01),
        ),
    )
    prepared = prepare_tracks((track,))[0]

    anchor = track_label_anchor(prepared)

    assert anchor is not None
    all_points = [point for segment in prepared.segments for point in segment]
    assert anchor.x == min(point.x for point in all_points)
    assert anchor.y == max(point.y for point in all_points)


def test_split_projected_segments_breaks_flagged_speed_outlier() -> None:
    points = (
        TrackPoint(52.0, 13.0),
        TrackPoint(52.001, 13.001),
        TrackPoint(52.002, 13.002),
        TrackPoint(52.003, 13.003),
    )
    track = ActivityTrack(
        activity_id="speed",
        name="Speed outlier",
        source_file=Path("speed.json"),
        points=points,
        segments=(
            TrackSegment(0, 1, 100, 10, 36, True),
            TrackSegment(1, 2, 100, 1, 360, False, "speed"),
            TrackSegment(2, 3, 100, 10, 36, True),
        ),
    )

    segments = split_projected_segments(track, max_segment_distance_meters=5_000)

    assert len(segments) == 2
    assert all(len(segment) == 2 for segment in segments)
