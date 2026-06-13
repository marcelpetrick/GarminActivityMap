import pytest

from activity_map.geo import (
    MAX_ZOOM,
    GeoBounds,
    ProjectedPoint,
    ScreenPoint,
    Viewport,
    choose_scale_bar,
    clamp_zoom,
    coordinate_bounds,
    fit_viewport,
    format_scale_distance,
    haversine_distance_meters,
    latitude_from_projected_y,
    normalize_longitude,
    pixels_for_ground_distance,
    project_point,
    scale_bar_widths_for_distances,
)
from activity_map.models import TrackPoint


def test_project_point_maps_zero_zero_to_world_center() -> None:
    projected = project_point(TrackPoint(latitude=0.0, longitude=0.0))

    assert projected.x == pytest.approx(0.5)
    assert projected.y == pytest.approx(0.5)
    assert latitude_from_projected_y(projected.y) == pytest.approx(0.0)


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


def test_viewport_allows_deep_zoom_without_early_clamp() -> None:
    viewport = Viewport(
        center=ProjectedPoint(0.5, 0.5),
        zoom=1_000_000.0,
        width=800,
        height=500,
    )

    zoomed = viewport.zoom_at(10_000.0, ScreenPoint(400.0, 250.0))

    assert zoomed.zoom == pytest.approx(10_000_000_000.0)
    assert clamp_zoom(MAX_ZOOM * 10.0) == MAX_ZOOM


def test_distance_helpers_support_scale_bar_math() -> None:
    one_km_pixels = pixels_for_ground_distance(
        meters=1_000.0,
        latitude=0.0,
        zoom=40_075.016686,
    )

    assert one_km_pixels == pytest.approx(1.0)
    assert haversine_distance_meters(
        TrackPoint(latitude=0.0, longitude=0.0),
        TrackPoint(latitude=0.0, longitude=1.0),
    ) == pytest.approx(111_195, rel=0.01)
    scale_widths = scale_bar_widths_for_distances(
        distances_meters=(1_000.0, 2_000.0, 5_000.0),
        latitude=0.0,
        zoom=40_075.016686,
        max_width=3.0,
    )

    assert [distance for distance, _ in scale_widths] == [1_000.0, 2_000.0, 5_000.0]
    assert [width for _, width in scale_widths] == pytest.approx([1.0, 2.0, 3.0])
    assert choose_scale_bar(
        latitude=0.0,
        zoom=40_075.016686,
        target_width=2.2,
        max_width=5.0,
    ) == pytest.approx((2_000.0, 2.0))
    assert format_scale_distance(2_000.0) == "2 km"
    assert format_scale_distance(500.0) == "0.5 km"
