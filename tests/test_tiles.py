import os
import time
from pathlib import Path

import pytest

import activity_map.tiles as tiles
from activity_map.geo import ProjectedPoint, Viewport
from activity_map.tiles import (
    MAX_TILE_ZOOM,
    MIN_CACHE_SECONDS,
    TILE_CACHE_DIRECTORY_ENVIRONMENT,
    TileCache,
    TileCoordinate,
    default_tile_cache_directory,
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
        minimum_download_interval_seconds: float = 0.0,
        download_burst: int = 1,
    ) -> None:
        super().__init__(
            root=root,
            minimum_download_interval_seconds=minimum_download_interval_seconds,
            download_burst=download_burst,
        )
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
    assert (
        viewport_tile_zoom(
            Viewport(ProjectedPoint(0.5, 0.5), zoom=256.0, width=512, height=512)
        )
        == 0
    )
    assert (
        viewport_tile_zoom(
            Viewport(ProjectedPoint(0.5, 0.5), zoom=4096.0, width=512, height=512)
        )
        == 4
    )


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


def test_tile_cache_writes_leave_no_partial_files(tmp_path: Path) -> None:
    coordinate = TileCoordinate(zoom=3, x=2, y=5)
    cache = StubTileCache(root=tmp_path, result=b"tile-bytes")

    assert cache.fetch_tile(coordinate) == b"tile-bytes"
    path = cache.tile_path(coordinate)
    assert path.read_bytes() == b"tile-bytes"
    assert sorted(entry.name for entry in path.parent.iterdir()) == [path.name]


def test_discard_tile_removes_unreadable_cache_entry(tmp_path: Path) -> None:
    coordinate = TileCoordinate(zoom=1, x=1, y=1)
    cache = StubTileCache(root=tmp_path)
    path = cache.tile_path(coordinate)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"truncated")

    cache.discard_tile(coordinate)

    assert not path.exists()
    cache.discard_tile(coordinate)


def test_default_tile_cache_directory_is_outside_the_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TILE_CACHE_DIRECTORY_ENVIRONMENT, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert default_tile_cache_directory() == (
        tmp_path / "cache" / "GarminActivityMap" / "map_tiles" / "osm"
    )

    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    assert default_tile_cache_directory() == (
        tmp_path / "home" / ".cache" / "GarminActivityMap" / "map_tiles" / "osm"
    )

    monkeypatch.setenv(TILE_CACHE_DIRECTORY_ENVIRONMENT, str(tmp_path / "configured"))
    assert default_tile_cache_directory() == tmp_path / "configured"
    assert TileCache().root == tmp_path / "configured"


def test_downloads_are_paced_but_cached_tiles_are_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    slept: list[float] = []

    def fake_monotonic() -> float:
        return clock[0]

    def fake_sleep(delay: float) -> None:
        slept.append(delay)
        clock[0] += delay

    monkeypatch.setattr(tiles, "monotonic_seconds", fake_monotonic)
    monkeypatch.setattr(tiles, "sleep_seconds", fake_sleep)
    cache = StubTileCache(
        root=tmp_path,
        result=b"tile",
        minimum_download_interval_seconds=0.2,
        download_burst=3,
    )

    for x in range(3):
        cache.fetch_tile(TileCoordinate(zoom=2, x=x, y=0))
    assert slept == []

    cache.fetch_tile(TileCoordinate(zoom=2, x=3, y=0))
    assert slept == [pytest.approx(0.2)]

    cache.fetch_tile(TileCoordinate(zoom=2, x=4, y=0))
    assert slept == [pytest.approx(0.2), pytest.approx(0.2)]

    clock[0] += 5.0
    cache.fetch_tile(TileCoordinate(zoom=2, x=5, y=0))
    assert len(slept) == 2

    cache.fetch_tile(TileCoordinate(zoom=2, x=0, y=0))
    assert cache.downloads == 6
    assert len(slept) == 2


def test_cache_rejects_unexpected_download_assertion(tmp_path: Path) -> None:
    cache = StubTileCache(root=tmp_path)
    coordinate = TileCoordinate(zoom=1, x=1, y=1)

    with pytest.raises(AssertionError, match="unexpected download"):
        cache.fetch_tile(coordinate)
