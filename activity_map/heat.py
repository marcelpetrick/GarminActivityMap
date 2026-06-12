from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .geo import project_point
from .models import TrackPoint


@dataclass(frozen=True, slots=True)
class HeatCell:
    x_index: int
    y_index: int
    count: int
    intensity: float


def build_heat_grid(
    points: Iterable[TrackPoint], cell_size: float = 0.01
) -> tuple[HeatCell, ...]:
    if cell_size <= 0:
        raise ValueError("cell_size must be greater than zero")

    counts: Counter[tuple[int, int]] = Counter()
    for point in points:
        projected = project_point(point)
        counts[(int(projected.x / cell_size), int(projected.y / cell_size))] += 1

    if not counts:
        return ()

    max_count = max(counts.values())
    return tuple(
        HeatCell(
            x_index=x_index,
            y_index=y_index,
            count=count,
            intensity=count / max_count,
        )
        for (x_index, y_index), count in sorted(counts.items())
    )
