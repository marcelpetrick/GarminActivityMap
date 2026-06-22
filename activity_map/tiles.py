from __future__ import annotations

import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from . import __version__
from .geo import ProjectedPoint, ScreenPoint, Viewport

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = "Map data (c) OpenStreetMap contributors"
OSM_USER_AGENT = (
    f"GarminVisualizeAllActivities/{__version__} (contact: mail@marcelpetrick.it)"
)
TILE_SIZE = 256
MIN_TILE_ZOOM = 0
MAX_TILE_ZOOM = 18
MIN_CACHE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class TileCoordinate:
    zoom: int
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class TileBounds:
    top_left: ProjectedPoint
    bottom_right: ProjectedPoint


class TileCache:
    def __init__(
        self,
        root: Path = Path("data/map_tiles/osm"),
        url_template: str = OSM_TILE_URL,
        user_agent: str = OSM_USER_AGENT,
        minimum_cache_seconds: int = MIN_CACHE_SECONDS,
    ) -> None:
        self.root = root
        self.url_template = url_template
        self.user_agent = user_agent
        self.minimum_cache_seconds = minimum_cache_seconds

    def tile_path(self, coordinate: TileCoordinate) -> Path:
        return (
            self.root / str(coordinate.zoom) / str(coordinate.x) / f"{coordinate.y}.png"
        )

    def load_cached_tile(self, coordinate: TileCoordinate) -> bytes | None:
        path = self.tile_path(coordinate)
        if not path.exists():
            return None
        return path.read_bytes()

    def fetch_tile(self, coordinate: TileCoordinate) -> bytes | None:
        cached = self.load_cached_tile(coordinate)
        path = self.tile_path(coordinate)
        if cached is not None and self._is_fresh(path):
            return cached

        try:
            fetched = self._download_tile(coordinate)
        except (OSError, urllib.error.URLError):
            return cached

        if not fetched:
            return cached
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetched)
        return fetched

    def _is_fresh(self, path: Path) -> bool:
        age_seconds = time.time() - path.stat().st_mtime
        return age_seconds < self.minimum_cache_seconds

    def _download_tile(self, coordinate: TileCoordinate) -> bytes:
        request = urllib.request.Request(
            self.url_template.format(
                z=coordinate.zoom,
                x=coordinate.x,
                y=coordinate.y,
            ),
            headers={"User-Agent": self.user_agent},
        )
        with urllib.request.urlopen(request, timeout=8.0) as response:
            return cast(bytes, response.read())


def viewport_tile_zoom(viewport: Viewport) -> int:
    raw_zoom = round(math.log2(max(viewport.zoom, 1.0) / TILE_SIZE))
    return max(MIN_TILE_ZOOM, min(MAX_TILE_ZOOM, raw_zoom))


def visible_tiles(viewport: Viewport) -> tuple[TileCoordinate, ...]:
    zoom = viewport_tile_zoom(viewport)
    tile_count = 2**zoom
    top_left = viewport.screen_to_world(ScreenPoint(0.0, 0.0))
    bottom_right = viewport.screen_to_world(
        ScreenPoint(float(viewport.width), float(viewport.height))
    )
    min_x = max(0, math.floor(min(top_left.x, bottom_right.x) * tile_count))
    max_x = min(
        tile_count - 1,
        math.floor(max(top_left.x, bottom_right.x) * tile_count),
    )
    min_y = max(0, math.floor(min(top_left.y, bottom_right.y) * tile_count))
    max_y = min(
        tile_count - 1,
        math.floor(max(top_left.y, bottom_right.y) * tile_count),
    )

    return tuple(
        TileCoordinate(zoom=zoom, x=x, y=y)
        for x in range(min_x, max_x + 1)
        for y in range(min_y, max_y + 1)
    )


def tile_bounds(coordinate: TileCoordinate) -> TileBounds:
    tile_count = 2**coordinate.zoom
    return TileBounds(
        top_left=ProjectedPoint(
            x=coordinate.x / tile_count,
            y=coordinate.y / tile_count,
        ),
        bottom_right=ProjectedPoint(
            x=(coordinate.x + 1) / tile_count,
            y=(coordinate.y + 1) / tile_count,
        ),
    )
