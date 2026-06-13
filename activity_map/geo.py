from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .models import TrackPoint

WEB_MERCATOR_LAT_LIMIT = 85.05112878
MIN_ZOOM = 128.0
MAX_ZOOM = 1_000_000_000_000.0
EARTH_CIRCUMFERENCE_METERS = 40_075_016.686


@dataclass(frozen=True, slots=True)
class ProjectedPoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class ScreenPoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class GeoBounds:
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    @property
    def center(self) -> TrackPoint:
        return TrackPoint(
            latitude=(self.min_latitude + self.max_latitude) / 2.0,
            longitude=(self.min_longitude + self.max_longitude) / 2.0,
        )


@dataclass(frozen=True, slots=True)
class Viewport:
    center: ProjectedPoint
    zoom: float
    width: int
    height: int

    def world_to_screen(self, point: ProjectedPoint) -> ScreenPoint:
        return ScreenPoint(
            x=(point.x - self.center.x) * self.zoom + self.width / 2.0,
            y=(point.y - self.center.y) * self.zoom + self.height / 2.0,
        )

    def screen_to_world(self, point: ScreenPoint) -> ProjectedPoint:
        return ProjectedPoint(
            x=(point.x - self.width / 2.0) / self.zoom + self.center.x,
            y=(point.y - self.height / 2.0) / self.zoom + self.center.y,
        )

    def pan(self, delta_x: float, delta_y: float) -> Viewport:
        return Viewport(
            center=ProjectedPoint(
                x=clamp_world(self.center.x - delta_x / self.zoom),
                y=clamp_world(self.center.y - delta_y / self.zoom),
            ),
            zoom=self.zoom,
            width=self.width,
            height=self.height,
        )

    def zoom_at(self, factor: float, anchor: ScreenPoint) -> Viewport:
        new_zoom = clamp_zoom(self.zoom * factor)
        anchor_world = self.screen_to_world(anchor)
        new_center = ProjectedPoint(
            x=anchor_world.x - (anchor.x - self.width / 2.0) / new_zoom,
            y=anchor_world.y - (anchor.y - self.height / 2.0) / new_zoom,
        )
        return Viewport(
            center=ProjectedPoint(
                x=clamp_world(new_center.x),
                y=clamp_world(new_center.y),
            ),
            zoom=new_zoom,
            width=self.width,
            height=self.height,
        )


def project_point(point: TrackPoint) -> ProjectedPoint:
    latitude = clamp(
        point.latitude,
        -WEB_MERCATOR_LAT_LIMIT,
        WEB_MERCATOR_LAT_LIMIT,
    )
    longitude = normalize_longitude(point.longitude)
    latitude_rad = math.radians(latitude)

    x = (longitude + 180.0) / 360.0
    y = (
        1.0
        - math.log(math.tan(latitude_rad) + 1.0 / math.cos(latitude_rad)) / math.pi
    ) / 2.0
    return ProjectedPoint(x=clamp_world(x), y=clamp_world(y))


def latitude_from_projected_y(y: float) -> float:
    mercator = math.pi * (1.0 - 2.0 * clamp_world(y))
    return math.degrees(math.atan(math.sinh(mercator)))


def pixels_for_ground_distance(
    meters: float,
    latitude: float,
    zoom: float,
) -> float:
    latitude_rad = math.radians(
        clamp(latitude, -WEB_MERCATOR_LAT_LIMIT, WEB_MERCATOR_LAT_LIMIT)
    )
    meters_per_world = max(EARTH_CIRCUMFERENCE_METERS * math.cos(latitude_rad), 1.0)
    return meters / meters_per_world * zoom


def scale_bar_widths(
    distances_meters: Iterable[float],
    latitude: float,
    zoom: float,
    max_width: float,
) -> tuple[tuple[float, float], ...]:
    return tuple(
        (
            distance,
            min(pixels_for_ground_distance(distance, latitude, zoom), max_width),
        )
        for distance in distances_meters
    )


def haversine_distance_meters(start: TrackPoint, end: TrackPoint) -> float:
    start_lat = math.radians(start.latitude)
    end_lat = math.radians(end.latitude)
    delta_lat = end_lat - start_lat
    delta_lon = math.radians(end.longitude - start.longitude)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(start_lat) * math.cos(end_lat) * math.sin(delta_lon / 2.0) ** 2
    )
    return (
        6_371_000.0
        * 2.0
        * math.atan2(math.sqrt(haversine), math.sqrt(1.0 - haversine))
    )


def coordinate_bounds(points: Iterable[TrackPoint]) -> GeoBounds | None:
    point_list = list(points)
    if not point_list:
        return None
    return GeoBounds(
        min_latitude=min(point.latitude for point in point_list),
        max_latitude=max(point.latitude for point in point_list),
        min_longitude=min(point.longitude for point in point_list),
        max_longitude=max(point.longitude for point in point_list),
    )


def fit_viewport(
    bounds: GeoBounds | None,
    width: int,
    height: int,
    padding_ratio: float = 0.12,
) -> Viewport:
    if bounds is None:
        return Viewport(
            center=ProjectedPoint(0.5, 0.5),
            zoom=max(MIN_ZOOM, min(width, height)),
            width=width,
            height=height,
        )

    corners = [
        project_point(TrackPoint(bounds.min_latitude, bounds.min_longitude)),
        project_point(TrackPoint(bounds.max_latitude, bounds.max_longitude)),
    ]
    min_x = min(point.x for point in corners)
    max_x = max(point.x for point in corners)
    min_y = min(point.y for point in corners)
    max_y = max(point.y for point in corners)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    padded_width = max(width * (1.0 - padding_ratio * 2.0), 1.0)
    padded_height = max(height * (1.0 - padding_ratio * 2.0), 1.0)

    return Viewport(
        center=ProjectedPoint(
            x=clamp_world((min_x + max_x) / 2.0),
            y=clamp_world((min_y + max_y) / 2.0),
        ),
        zoom=clamp_zoom(min(padded_width / span_x, padded_height / span_y)),
        width=width,
        height=height,
    )


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def clamp_world(value: float) -> float:
    return clamp(value, 0.0, 1.0)


def clamp_zoom(value: float) -> float:
    return clamp(value, MIN_ZOOM, MAX_ZOOM)


def normalize_longitude(longitude: float) -> float:
    normalized = ((longitude + 180.0) % 360.0) - 180.0
    if normalized == -180.0 and longitude > 0:
        return 180.0
    return normalized
