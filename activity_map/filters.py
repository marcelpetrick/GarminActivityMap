from __future__ import annotations

from datetime import date, datetime

from .render import RenderTrack

DATE_FORMAT = "%Y-%m-%d"


def parse_date_text(text: str) -> date | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return datetime.strptime(stripped, DATE_FORMAT).date()
    except ValueError:
        return None


def is_valid_date_text(text: str) -> bool:
    return not text.strip() or parse_date_text(text) is not None


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def track_date_span(tracks: tuple[RenderTrack, ...]) -> tuple[date, date] | None:
    dates = [track.start_date for track in tracks if track.start_date is not None]
    if not dates:
        return None
    return min(dates), max(dates)


def undated_track_count(tracks: tuple[RenderTrack, ...]) -> int:
    return sum(1 for track in tracks if track.start_date is None)


def tracks_in_range(
    tracks: tuple[RenderTrack, ...],
    start: date | None,
    end: date | None,
) -> frozenset[int]:
    if start is None and end is None:
        return frozenset(range(len(tracks)))
    return frozenset(
        index
        for index, track in enumerate(tracks)
        if track.start_date is not None
        and (start is None or track.start_date >= start)
        and (end is None or track.start_date <= end)
    )
