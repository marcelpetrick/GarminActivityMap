import os
import time
from pathlib import Path

import pytest

from activity_map.geo import ProjectedPoint, Viewport
from activity_map.tiles import (
    MAX_TILE_ZOOM,
    MIN_CACHE_SECONDS,
    TileCache,
    TileCoordinate,
    tile_bounds,
    viewport_tile_zoom,
    visible_tiles,
)


class StubTileCache(TileCache):
    def __init__(
        self,
        root: Path,
        result: bytes | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(root=root)
        self.result = result
        self.error = error
        self.downloads = 0

    def _download_tile(self, coordinate: TileCoordinate) -> bytes:
        self.downloads += 1
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError(f"unexpected download: {coordinate}")
        return self.result


def test_viewport_tile_zoom_scales_with_map_zoom() -> None:
    assert viewport_tile_zoom(
        Viewport(ProjectedPoint(0.5, 0.5), zoom=256.0, width=512, height=512)
    ) == 0
    assert viewport_tile_zoom(
        Viewport(ProjectedPoint(0.5, 0.5), zoom=4096.0, width=512, height=512)
    ) == 4


def test_viewport_tile_zoom_caps_provider_requests_at_tile_limit() -> None:
    assert (
        viewport_tile_zoom(
            Viewport(
                ProjectedPoint(0.5, 0.5),
                zoom=1_000_000_000_000.0,
                width=512,
                height=512,
            )
        )
        == MAX_TILE_ZOOM
    )


def test_visible_tiles_returns_tiles_for_current_viewport() -> None:
    viewport = Viewport(
        center=ProjectedPoint(0.5, 0.5),
        zoom=512.0,
        width=512,
        height=512,
    )

    tiles = visible_tiles(viewport)

    assert TileCoordinate(zoom=1, x=0, y=0) in tiles
    assert TileCoordinate(zoom=1, x=1, y=1) in tiles
    assert len(tiles) == 4


def test_tile_bounds_returns_world_extent() -> None:
    bounds = tile_bounds(TileCoordinate(zoom=2, x=1, y=2))

    assert bounds.top_left == ProjectedPoint(0.25, 0.5)
    assert bounds.bottom_right == ProjectedPoint(0.5, 0.75)


def test_tile_cache_reuses_fresh_disk_tile(tmp_path: Path) -> None:
    coordinate = TileCoordinate(zoom=1, x=1, y=1)
    cache = StubTileCache(root=tmp_path)
    path = cache.tile_path(coordinate)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"cached")

    assert cache.fetch_tile(coordinate) == b"cached"
    assert cache.downloads == 0


def test_tile_cache_refreshes_stale_tile(tmp_path: Path) -> None:
    coordinate = TileCoordinate(zoom=1, x=1, y=1)
    cache = StubTileCache(root=tmp_path, result=b"new")
    path = cache.tile_path(coordinate)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old")
    stale_time = time.time() - MIN_CACHE_SECONDS - 60
    os.utime(path, (stale_time, stale_time))

    assert cache.fetch_tile(coordinate) == b"new"
    assert path.read_bytes() == b"new"
    assert cache.downloads == 1


def test_tile_cache_returns_stale_tile_when_download_fails(tmp_path: Path) -> None:
    coordinate = TileCoordinate(zoom=1, x=1, y=1)
    cache = StubTileCache(root=tmp_path, error=OSError("offline"))
    path = cache.tile_path(coordinate)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old")
    stale_time = time.time() - MIN_CACHE_SECONDS - 60
    os.utime(path, (stale_time, stale_time))

    assert cache.fetch_tile(coordinate) == b"old"
    assert cache.downloads == 1


def test_tile_cache_returns_none_when_tile_is_missing_and_download_fails(
    tmp_path: Path,
) -> None:
    coordinate = TileCoordinate(zoom=1, x=1, y=1)
    cache = StubTileCache(root=tmp_path, error=OSError("offline"))

    assert cache.fetch_tile(coordinate) is None
    assert cache.downloads == 1


def test_cache_rejects_unexpected_download_assertion(tmp_path: Path) -> None:
    cache = StubTileCache(root=tmp_path)
    coordinate = TileCoordinate(zoom=1, x=1, y=1)

    with pytest.raises(AssertionError, match="unexpected download"):
        cache.fetch_tile(coordinate)
