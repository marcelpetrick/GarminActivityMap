from __future__ import annotations

from dataclasses import dataclass

from .geo import ProjectedPoint, project_point
from .heat import HeatCell
from .models import ActivityTrack


@dataclass(frozen=True, slots=True)
class RenderTrack:
    activity_id: str
    name: str
    points: tuple[ProjectedPoint, ...]


@dataclass(frozen=True, slots=True)
class RenderHeatCell:
    center: ProjectedPoint
    count: int
    intensity: float


def prepare_tracks(tracks: tuple[ActivityTrack, ...]) -> tuple[RenderTrack, ...]:
    return tuple(
        RenderTrack(
            activity_id=track.activity_id,
            name=track.name,
            points=tuple(project_point(point) for point in track.points),
        )
        for track in tracks
    )


def prepare_heat_cells(
    heat_cells: tuple[HeatCell, ...], cell_size: float
) -> tuple[RenderHeatCell, ...]:
    return tuple(
        RenderHeatCell(
            center=ProjectedPoint(
                x=(cell.x_index + 0.5) * cell_size,
                y=(cell.y_index + 0.5) * cell_size,
            ),
            count=cell.count,
            intensity=cell.intensity,
        )
        for cell in heat_cells
    )
