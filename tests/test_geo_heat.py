import pytest

from activity_map.geo import (
    GeoBounds,
    ProjectedPoint,
    ScreenPoint,
    Viewport,
    coordinate_bounds,
    fit_viewport,
    normalize_longitude,
    project_point,
)
from activity_map.heat import build_heat_grid
from activity_map.models import TrackPoint


def test_project_point_maps_zero_zero_to_world_center() -> None:
    projected = project_point(TrackPoint(latitude=0.0, longitude=0.0))

    assert projected.x == pytest.approx(0.5)
    assert projected.y == pytest.approx(0.5)


def test_project_point_clamps_latitude_and_normalizes_longitude() -> None:
    projected = project_point(TrackPoint(latitude=120.0, longitude=190.0))

    assert 0.0 <= projected.x <= 1.0
    assert 0.0 <= projected.y <= 1.0
    assert normalize_longitude(190.0) == -170.0
    assert normalize_longitude(180.0) == 180.0


def test_coordinate_bounds_returns_expected_extents() -> None:
    bounds = coordinate_bounds(
        [
            TrackPoint(latitude=52.5, longitude=13.4),
            TrackPoint(latitude=48.1, longitude=11.5),
        ]
    )

    assert bounds == GeoBounds(
        min_latitude=48.1,
        max_latitude=52.5,
        min_longitude=11.5,
        max_longitude=13.4,
    )
    assert coordinate_bounds([]) is None


def test_fit_viewport_defaults_to_world_when_no_bounds() -> None:
    viewport = fit_viewport(None, width=800, height=500)

    assert viewport.center == ProjectedPoint(0.5, 0.5)
    assert viewport.zoom >= 128


def test_fit_viewport_centers_bounds_in_screen() -> None:
    bounds = GeoBounds(
        min_latitude=48.0,
        max_latitude=49.0,
        min_longitude=11.0,
        max_longitude=12.0,
    )

    viewport = fit_viewport(bounds, width=800, height=500)
    center_screen = viewport.world_to_screen(project_point(bounds.center))

    assert center_screen.x == pytest.approx(400.0, abs=2.0)
    assert center_screen.y == pytest.approx(250.0, abs=2.0)


def test_viewport_pan_and_zoom_at_preserve_anchor_world_position() -> None:
    viewport = Viewport(
        center=ProjectedPoint(0.5, 0.5),
        zoom=500.0,
        width=800,
        height=500,
    )
    anchor = ScreenPoint(600.0, 300.0)
    before = viewport.screen_to_world(anchor)

    zoomed = viewport.zoom_at(2.0, anchor)
    after = zoomed.screen_to_world(anchor)
    panned = zoomed.pan(20.0, -10.0)

    assert after.x == pytest.approx(before.x)
    assert after.y == pytest.approx(before.y)
    assert panned.center.x < zoomed.center.x
    assert panned.center.y > zoomed.center.y


def test_build_heat_grid_counts_and_normalizes_cells() -> None:
    cells = build_heat_grid(
        [
            TrackPoint(latitude=0.0, longitude=0.0),
            TrackPoint(latitude=0.0, longitude=0.0),
            TrackPoint(latitude=10.0, longitude=10.0),
        ],
        cell_size=0.05,
    )

    assert len(cells) == 2
    assert max(cell.count for cell in cells) == 2
    assert max(cell.intensity for cell in cells) == 1.0
    assert min(cell.intensity for cell in cells) == 0.5


def test_build_heat_grid_rejects_invalid_cell_size() -> None:
    with pytest.raises(ValueError, match="cell_size"):
        build_heat_grid([TrackPoint(latitude=0.0, longitude=0.0)], cell_size=0.0)


def test_build_heat_grid_returns_empty_tuple_for_no_points() -> None:
    assert build_heat_grid([]) == ()
