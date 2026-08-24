from __future__ import annotations

from datetime import date, timedelta

from .render import RenderTrack

REPLAY_DURATION_MILLISECONDS = 10_000
REPLAY_TICK_MILLISECONDS = 50


def replay_day_count(start: date, end: date) -> int:
    return (end - start).days + 1


def revealed_cutoff(start: date, end: date, progress: float) -> date | None:
    days = replay_day_count(start, end)
    clamped = min(max(progress, 0.0), 1.0)
    revealed = min(int(clamped * days), days)
    if revealed <= 0:
        return None
    return start + timedelta(days=revealed - 1)


def tracks_until(
    tracks: tuple[RenderTrack, ...],
    cutoff: date | None,
    allowed: frozenset[int] | None = None,
) -> frozenset[int]:
    if cutoff is None:
        return frozenset()
    return frozenset(
        index
        for index, track in enumerate(tracks)
        if track.start_date is not None
        and track.start_date <= cutoff
        and (allowed is None or index in allowed)
    )
