import json
from datetime import UTC, datetime
from pathlib import Path

from activity_map.loader import (
    extract_track_points,
    load_activity_file,
    load_directory,
    normalize_coordinate,
    parse_timestamp,
    validate_segments,
)
from activity_map.models import TrackPoint


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_activity_file_extracts_geo_polyline_points(tmp_path: Path) -> None:
    activity_file = tmp_path / "101.json"
    write_json(
        activity_file,
        {
            "summary": {"activityId": 101, "activityName": "Morning Run"},
            "details": {
                "geoPolylineDTO": {
                    "polyline": [
                        {"lat": 52.5, "lon": 13.4},
                        {"latitude": 52.51, "longitude": 13.41},
                    ]
                }
            },
        },
    )

    track = load_activity_file(activity_file)

    assert track is not None
    assert track.activity_id == "101"
    assert track.name == "Morning Run"
    assert track.points == (
        TrackPoint(latitude=52.5, longitude=13.4),
        TrackPoint(latitude=52.51, longitude=13.41),
    )


def test_extract_track_points_supports_metric_descriptors() -> None:
    points = extract_track_points(
        {
            "details": {
                "metricDescriptors": [
                    {"key": "timerDuration", "metricsIndex": 0},
                    {"key": "directLatitude", "metricsIndex": 1},
                    {"key": "directLongitude", "metricsIndex": 2},
                ],
                "activityDetailMetrics": [
                    {"metrics": [0, 52.5, 13.4]},
                    {"metrics": [1, 52.6, 13.5]},
                ],
            }
        }
    )

    assert points == [
        TrackPoint(latitude=52.5, longitude=13.4),
        TrackPoint(latitude=52.6, longitude=13.5),
    ]


def test_extract_track_points_falls_back_to_coordinate_dicts() -> None:
    points = extract_track_points(
        {
            "details": {
                "samples": [
                    {"positionLat": 52.5, "positionLong": 13.4},
                    {"positionLat": "invalid", "positionLong": 13.5},
                    {"positionLat": 95.0, "positionLong": 13.5},
                    {"positionLat": 52.6, "positionLong": 13.6},
                ]
            }
        }
    )

    assert points == [
        TrackPoint(latitude=52.5, longitude=13.4),
        TrackPoint(latitude=52.6, longitude=13.6),
    ]


def test_extract_track_points_converts_semicircle_coordinates() -> None:
    points = extract_track_points(
        {
            "details": {
                "geoPolylineDTO": {
                    "polyline": [
                        {
                            "positionLat": 626349397,
                            "positionLong": 159891478,
                        }
                    ]
                }
            }
        }
    )

    assert len(points) == 1
    assert round(points[0].latitude, 2) == 52.5
    assert round(points[0].longitude, 2) == 13.4


def test_load_directory_skips_manifest_and_reports_bad_files(tmp_path: Path) -> None:
    write_json(tmp_path / "manifest.json", {"files": ["ignored"]})
    write_json(
        tmp_path / "valid.json",
        {
            "summary": {"activityId": "valid"},
            "details": {"geoPolylineDTO": {"polyline": [[52.5, 13.4]]}},
        },
    )
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    write_json(tmp_path / "empty.json", {"summary": {"activityId": "empty"}})

    report = load_directory(tmp_path)

    assert report.files_read == 3
    assert report.files_skipped == 2
    assert report.point_count == 1
    assert [track.activity_id for track in report.tracks] == ["valid"]
    assert {warning.source_file.name for warning in report.warnings} == {
        "bad.json",
        "empty.json",
    }


def test_load_directory_reports_missing_directory(tmp_path: Path) -> None:
    report = load_directory(tmp_path / "missing")

    assert report.files_read == 0
    assert report.tracks == ()
    assert report.files_skipped == 1
    assert report.warnings[0].message == "Directory does not exist"


def test_load_activity_file_rejects_non_object_json(tmp_path: Path) -> None:
    activity_file = tmp_path / "list.json"
    write_json(activity_file, [])

    try:
        load_activity_file(activity_file)
    except ValueError as exc:
        assert str(exc) == "Activity file must contain a JSON object"
    else:
        raise AssertionError("Expected ValueError")


def test_normalize_coordinate_rejects_invalid_values() -> None:
    assert normalize_coordinate(None, "latitude") is None
    assert normalize_coordinate("nan", "latitude") is None
    assert normalize_coordinate(200, "longitude") is None


def test_timestamped_segments_flag_impossible_speed_without_changing_source(
    tmp_path: Path,
) -> None:
    activity_file = tmp_path / "spike.json"
    payload = {
        "summary": {"activityId": 9},
        "details": {
            "geoPolylineDTO": {
                "polyline": [
                    {
                        "lat": 52.5,
                        "lon": 13.4,
                        "timestamp": "2026-06-22T08:00:00Z",
                    },
                    {
                        "lat": 53.5,
                        "lon": 14.4,
                        "timestamp": "2026-06-22T08:00:01Z",
                    },
                    {
                        "lat": 53.5001,
                        "lon": 14.4001,
                        "timestamp": "2026-06-22T08:01:01Z",
                    },
                ]
            }
        },
    }
    write_json(activity_file, payload)

    track = load_activity_file(activity_file)

    assert track is not None
    assert track.segments[0].valid is False
    assert track.segments[0].speed_kmh is not None
    assert track.segments[0].speed_kmh > 30
    assert "implied speed" in track.validation_messages[0]
    assert json.loads(activity_file.read_text()) == payload


def test_segment_validation_detects_duplicate_and_missing_timestamps() -> None:
    points = (
        TrackPoint(52.0, 13.0, datetime(2026, 6, 22, tzinfo=UTC)),
        TrackPoint(52.001, 13.001, datetime(2026, 6, 22, tzinfo=UTC)),
        TrackPoint(52.002, 13.002),
    )

    segments, messages = validate_segments(points)

    assert segments[0].valid is False
    assert "duplicated or out of order" in (segments[0].reason or "")
    assert segments[1].valid is True
    assert any("timestamps are missing" in message for message in messages)


def test_parse_timestamp_supports_iso_and_epoch_milliseconds() -> None:
    assert parse_timestamp("2026-06-22T08:00:00Z") == datetime(
        2026, 6, 22, 8, tzinfo=UTC
    )
    assert parse_timestamp(1_750_579_200_000) == datetime.fromtimestamp(
        1_750_579_200, tz=UTC
    )
    assert parse_timestamp("invalid") is None
