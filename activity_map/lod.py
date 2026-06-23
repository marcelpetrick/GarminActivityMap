from __future__ import annotations

from dataclasses import dataclass

from .render import RenderTrack

TARGET_ERROR_PIXELS = 3.0
DEFAULT_VERTEX_BUDGET = 100_000


@dataclass(frozen=True, slots=True)
class LodSelection:
    level_index: int
    tolerance_world: float
    point_count: int


def select_lod(
    tracks: tuple[RenderTrack, ...],
    visible_indexes: tuple[int, ...],
    zoom: float,
    vertex_budget: int = DEFAULT_VERTEX_BUDGET,
    target_error_pixels: float = TARGET_ERROR_PIXELS,
) -> LodSelection:
    if not visible_indexes:
        return LodSelection(
            0, tracks[0].levels[0].tolerance_world if tracks else 0.0, 0
        )

    levels = tracks[visible_indexes[0]].levels
    target_tolerance = target_error_pixels / zoom
    level_index = next(
        (
            index
            for index, level in enumerate(levels)
            if level.tolerance_world <= target_tolerance
        ),
        len(levels) - 1,
    )
    point_count = selected_point_count(tracks, visible_indexes, level_index)
    while level_index > 0 and point_count > vertex_budget:
        level_index -= 1
        point_count = selected_point_count(tracks, visible_indexes, level_index)
    return LodSelection(
        level_index=level_index,
        tolerance_world=levels[level_index].tolerance_world,
        point_count=point_count,
    )


def selected_point_count(
    tracks: tuple[RenderTrack, ...],
    visible_indexes: tuple[int, ...],
    level_index: int,
) -> int:
    return sum(
        tracks[index].levels[level_index].point_count for index in visible_indexes
    )
