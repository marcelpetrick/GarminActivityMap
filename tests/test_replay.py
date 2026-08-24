from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import prepare_tracks
from activity_map.replay import (
    REPLAY_DURATION_MILLISECONDS,
    REPLAY_TICK_MILLISECONDS,
    replay_day_count,
    revealed_cutoff,
    tracks_until,
)


def dated_track(activity_id: str, day: int | None) -> ActivityTrack:
    stamp = None if day is None else datetime(2026, 6, day, 8, 0, tzinfo=UTC)
    return ActivityTrack(
        activity_id=activity_id,
        name=activity_id,
        source_file=Path(f"{activity_id}.json"),
        points=(
            TrackPoint(52.50, 13.40, stamp),
            TrackPoint(52.51, 13.41, stamp),
            TrackPoint(52.52, 13.42, stamp),
        ),
    )


def test_replay_duration_is_ten_seconds_of_ticks() -> None:
    assert REPLAY_DURATION_MILLISECONDS == 10_000
    assert REPLAY_DURATION_MILLISECONDS % REPLAY_TICK_MILLISECONDS == 0


def test_replay_day_count_is_inclusive() -> None:
    assert replay_day_count(date(2026, 6, 1), date(2026, 6, 10)) == 10
    assert replay_day_count(date(2026, 6, 1), date(2026, 6, 1)) == 1


def test_revealed_cutoff_maps_progress_onto_the_span() -> None:
    start, end = date(2026, 6, 1), date(2026, 6, 10)

    assert revealed_cutoff(start, end, 0.0) is None
    assert revealed_cutoff(start, end, -1.0) is None
    assert revealed_cutoff(start, end, 0.05) is None
    assert revealed_cutoff(start, end, 0.1) == date(2026, 6, 1)
    assert revealed_cutoff(start, end, 0.5) == date(2026, 6, 5)
    assert revealed_cutoff(start, end, 0.99) == date(2026, 6, 9)
    assert revealed_cutoff(start, end, 1.0) == end
    assert revealed_cutoff(start, end, 2.0) == end


def test_revealed_cutoff_handles_a_single_day_span() -> None:
    day = date(2026, 6, 2)

    assert revealed_cutoff(day, day, 0.0) is None
    assert revealed_cutoff(day, day, 0.5) is None
    assert revealed_cutoff(day, day, 1.0) == day


def test_tracks_until_reveals_chronologically_within_the_allowed_set() -> None:
    tracks = prepare_tracks(
        (
            dated_track("june-2", 2),
            dated_track("june-9", 9),
            dated_track("june-20", 20),
            dated_track("undated", None),
        )
    )

    assert tracks_until(tracks, None) == frozenset()
    assert tracks_until(tracks, date(2026, 6, 1)) == frozenset()
    assert tracks_until(tracks, date(2026, 6, 9)) == frozenset({0, 1})
    assert tracks_until(tracks, date(2026, 6, 20)) == frozenset({0, 1, 2})
    assert tracks_until(tracks, date(2026, 6, 20), frozenset({1, 2})) == frozenset(
        {1, 2}
    )
