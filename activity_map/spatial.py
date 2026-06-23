from __future__ import annotations

import math
from dataclasses import dataclass

from .geo import ScreenPoint, Viewport
from .render import ProjectedBounds, RenderTrack

DEFAULT_GRID_SIZE = 256


@dataclass(frozen=True, slots=True)
class TrackSpatialIndex:
    tracks: tuple[RenderTrack, ...]
    cells: dict[tuple[int, int], tuple[int, ...]]
    grid_size: int = DEFAULT_GRID_SIZE

    @classmethod
    def build(
        cls,
        tracks: tuple[RenderTrack, ...],
        grid_size: int = DEFAULT_GRID_SIZE,
    ) -> TrackSpatialIndex:
        pending: dict[tuple[int, int], list[int]] = {}
        for track_index, track in enumerate(tracks):
            min_x, max_x, min_y, max_y = bounds_cells(track.bounds, grid_size)
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    pending.setdefault((x, y), []).append(track_index)
        return cls(
            tracks=tracks,
            cells={cell: tuple(indexes) for cell, indexes in pending.items()},
            grid_size=grid_size,
        )

    def query(self, bounds: ProjectedBounds) -> tuple[int, ...]:
        min_x, max_x, min_y, max_y = bounds_cells(bounds, self.grid_size)
        candidates: set[int] = set()
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                candidates.update(self.cells.get((x, y), ()))
        return tuple(
            index
            for index in sorted(candidates)
            if self.tracks[index].bounds.intersects(bounds)
        )


def viewport_bounds(viewport: Viewport, margin_pixels: float = 4.0) -> ProjectedBounds:
    top_left = viewport.screen_to_world(ScreenPoint(-margin_pixels, -margin_pixels))
    bottom_right = viewport.screen_to_world(
        ScreenPoint(
            viewport.width + margin_pixels,
            viewport.height + margin_pixels,
        )
    )
    return ProjectedBounds(
        min_x=min(top_left.x, bottom_right.x),
        max_x=max(top_left.x, bottom_right.x),
        min_y=min(top_left.y, bottom_right.y),
        max_y=max(top_left.y, bottom_right.y),
    )


def bounds_cells(
    bounds: ProjectedBounds,
    grid_size: int,
) -> tuple[int, int, int, int]:
    return (
        cell_coordinate(bounds.min_x, grid_size),
        cell_coordinate(bounds.max_x, grid_size),
        cell_coordinate(bounds.min_y, grid_size),
        cell_coordinate(bounds.max_y, grid_size),
    )


def cell_coordinate(value: float, grid_size: int) -> int:
    return max(0, min(grid_size - 1, math.floor(value * grid_size)))
