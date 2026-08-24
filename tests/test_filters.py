from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from activity_map.filters import (
    format_date,
    is_valid_date_text,
    parse_date_text,
    track_date_span,
    tracks_in_range,
    undated_track_count,
)
from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import activity_start_date, prepare_tracks


def dated_track(activity_id: str, day: int | None) -> ActivityTrack:
    timestamp = None if day is None else datetime(2026, 6, day, 7, 30, tzinfo=UTC)
    return ActivityTrack(
        activity_id=activity_id,
        name=activity_id,
        source_file=Path(f"{activity_id}.json"),
        points=(
            TrackPoint(52.50, 13.40, timestamp),
            TrackPoint(52.51, 13.41, timestamp),
            TrackPoint(52.52, 13.42, timestamp),
        ),
    )


def test_parse_date_text_accepts_only_iso_dates() -> None:
    assert parse_date_text("2026-06-02") == date(2026, 6, 2)
    assert parse_date_text("  2026-06-02  ") == date(2026, 6, 2)
    assert parse_date_text("") is None
    assert parse_date_text("   ") is None
    assert parse_date_text("02.06.2026") is None
    assert parse_date_text("2026-13-02") is None
    assert parse_date_text("2026-06-02T10:00") is None
    assert format_date(date(2026, 6, 2)) == "2026-06-02"


def test_is_valid_date_text_treats_empty_as_valid() -> None:
    assert is_valid_date_text("")
    assert is_valid_date_text("  ")
    assert is_valid_date_text("2026-06-02")
    assert not is_valid_date_text("yesterday")


def test_activity_start_date_uses_the_first_available_timestamp() -> None:
    track = ActivityTrack(
        activity_id="mixed",
        name="Mixed",
        source_file=Path("mixed.json"),
        points=(
            TrackPoint(52.50, 13.40),
            TrackPoint(52.51, 13.41, datetime(2026, 7, 4, 6, 0, tzinfo=UTC)),
            TrackPoint(52.52, 13.42, datetime(2026, 7, 4, 6, 5, tzinfo=UTC)),
        ),
    )

    assert activity_start_date(track) == date(2026, 7, 4)
    assert activity_start_date(dated_track("undated", None)) is None


def test_track_date_span_and_undated_count() -> None:
    tracks = prepare_tracks(
        (
            dated_track("june-2", 2),
            dated_track("june-20", 20),
            dated_track("june-9", 9),
            dated_track("undated", None),
        )
    )

    assert track_date_span(tracks) == (date(2026, 6, 2), date(2026, 6, 20))
    assert undated_track_count(tracks) == 1
    assert track_date_span(prepare_tracks((dated_track("undated", None),))) is None


def test_tracks_in_range_selects_inclusive_bounds() -> None:
    tracks = prepare_tracks(
        (
            dated_track("june-2", 2),
            dated_track("june-9", 9),
            dated_track("june-20", 20),
            dated_track("undated", None),
        )
    )

    assert tracks_in_range(tracks, None, None) == frozenset({0, 1, 2, 3})
    assert tracks_in_range(tracks, date(2026, 6, 2), date(2026, 6, 9)) == frozenset(
        {0, 1}
    )
    assert tracks_in_range(tracks, date(2026, 6, 9), None) == frozenset({1, 2})
    assert tracks_in_range(tracks, None, date(2026, 6, 2)) == frozenset({0})
    assert tracks_in_range(tracks, date(2026, 7, 1), None) == frozenset()
