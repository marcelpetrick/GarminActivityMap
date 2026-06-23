from __future__ import annotations

from pathlib import Path

import pytest

from activity_map.geo import ProjectedPoint, Viewport
from activity_map.models import ActivityTrack, TrackPoint
from activity_map.qt_render import (
    polyline_path,
    prepare_retained_paths,
    viewport_transform,
)
from activity_map.render import prepare_tracks


def test_polyline_path_retains_segment_breaks() -> None:
    path = polyline_path(
        (
            (ProjectedPoint(0.1, 0.2), ProjectedPoint(0.2, 0.3)),
            (ProjectedPoint(0.7, 0.8), ProjectedPoint(0.8, 0.9)),
        )
    )

    assert path.elementCount() == 4
    assert path.elementAt(0).isMoveTo()
    assert path.elementAt(1).isLineTo()
    assert path.elementAt(2).isMoveTo()
    assert path.elementAt(3).isLineTo()


def test_prepare_retained_paths_builds_both_zoom_tiers() -> None:
    track = ActivityTrack(
        activity_id="retained",
        name="Retained",
        source_file=Path("retained.json"),
        points=tuple(
            TrackPoint(52.0 + index * 0.0001, 13.0 + index * 0.0001)
            for index in range(20)
        ),
    )
    prepared = prepare_tracks((track,))

    retained = prepare_retained_paths(prepared)

    assert len(retained) == 1
    assert retained[0].simplified.elementCount() < retained[0].detailed.elementCount()


def test_viewport_transform_matches_world_to_screen() -> None:
    viewport = Viewport(
        center=ProjectedPoint(0.5, 0.4),
        zoom=10_000.0,
        width=1_200,
        height=760,
    )
    point = ProjectedPoint(0.51, 0.39)

    transformed = viewport_transform(viewport).map(point.x, point.y)
    expected = viewport.world_to_screen(point)

    assert transformed[0] == pytest.approx(expected.x)
    assert transformed[1] == pytest.approx(expected.y)
