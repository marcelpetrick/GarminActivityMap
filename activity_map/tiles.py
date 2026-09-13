from __future__ import annotations

import math
import os
import tempfile
import threading
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
MIN_DOWNLOAD_INTERVAL_SECONDS = 0.2
DOWNLOAD_BURST = 24
MIN_SLEEP_SECONDS = 0.001
TILE_CACHE_DIRECTORY_ENVIRONMENT = "ACTIVITY_MAP_TILE_CACHE_DIR"
MAX_DISK_CACHE_BYTES = 512 * 1024 * 1024
MAX_DISK_CACHE_TILES = 8_192


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
        root: Path | None = None,
        url_template: str = OSM_TILE_URL,
        user_agent: str = OSM_USER_AGENT,
        minimum_cache_seconds: int = MIN_CACHE_SECONDS,
        minimum_download_interval_seconds: float = MIN_DOWNLOAD_INTERVAL_SECONDS,
        download_burst: int = DOWNLOAD_BURST,
        maximum_cache_bytes: int = MAX_DISK_CACHE_BYTES,
        maximum_cache_tiles: int = MAX_DISK_CACHE_TILES,
    ) -> None:
        self.root = (root or default_tile_cache_directory()).expanduser()
        self.url_template = url_template
        self.user_agent = user_agent
        self.minimum_cache_seconds = minimum_cache_seconds
        self.minimum_download_interval_seconds = minimum_download_interval_seconds
        self.download_burst = max(download_burst, 1)
        self.maximum_cache_bytes = max(maximum_cache_bytes, 0)
        self.maximum_cache_tiles = max(maximum_cache_tiles, 0)
        self._download_lock = threading.Lock()
        self._cache_lock = threading.RLock()
        self._cache_entries: dict[Path, tuple[float, int]] | None = None
        self._cache_size_bytes = 0
        self._next_download_at = 0.0

    def tile_path(self, coordinate: TileCoordinate) -> Path:
        return (
            self.root / str(coordinate.zoom) / str(coordinate.x) / f"{coordinate.y}.png"
        )

    def load_cached_tile(self, coordinate: TileCoordinate) -> bytes | None:
        path = self.tile_path(coordinate)
        try:
            return path.read_bytes()
        except OSError:
            return None

    def is_cached_tile_fresh(self, coordinate: TileCoordinate) -> bool:
        try:
            return self._is_fresh(self.tile_path(coordinate))
        except OSError:
            return False

    def discard_tile(self, coordinate: TileCoordinate) -> None:
        path = self.tile_path(coordinate)
        with self._cache_lock:
            path.unlink(missing_ok=True)
            if self._cache_entries is not None:
                removed = self._cache_entries.pop(path, None)
                if removed is not None:
                    self._cache_size_bytes -= removed[1]
            self._remove_empty_parents(path.parent)

    def fetch_tile(self, coordinate: TileCoordinate) -> bytes | None:
        cached = self.load_cached_tile(coordinate)
        path = self.tile_path(coordinate)
        if cached is not None and self.is_cached_tile_fresh(coordinate):
            return cached

        try:
            self._pace_download()
            fetched = self._download_tile(coordinate)
        except OSError, urllib.error.URLError:
            return cached

        if not fetched:
            return cached
        self._store_tile(path, fetched)
        return fetched

    def _store_tile(self, path: Path, data: bytes) -> None:
        with self._cache_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(data)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                temporary_path.replace(path)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()
            self.prune_cache(path)

    def prune_cache(self, updated_path: Path | None = None) -> None:
        with self._cache_lock:
            if self._cache_entries is None or updated_path is None:
                self._index_cache()
            else:
                previous = self._cache_entries.get(updated_path)
                try:
                    metadata = updated_path.stat()
                except OSError:
                    self._cache_entries.pop(updated_path, None)
                    if previous is not None:
                        self._cache_size_bytes -= previous[1]
                else:
                    self._cache_entries[updated_path] = (
                        metadata.st_mtime,
                        metadata.st_size,
                    )
                    self._cache_size_bytes += metadata.st_size - (
                        previous[1] if previous is not None else 0
                    )
            self._evict_oldest_tiles()

    def _index_cache(self) -> None:
        entries: dict[Path, tuple[float, int]] = {}
        for tile_path in self.root.rglob("*.png"):
            try:
                metadata = tile_path.stat()
            except OSError:
                continue
            entries[tile_path] = (metadata.st_mtime, metadata.st_size)
        self._cache_entries = entries
        self._cache_size_bytes = sum(size for _modified, size in entries.values())

    def _evict_oldest_tiles(self) -> None:
        if self._cache_entries is None:
            return
        while (
            self._cache_size_bytes > self.maximum_cache_bytes
            or len(self._cache_entries) > self.maximum_cache_tiles
        ):
            tile_path, (_modified, size) = min(
                self._cache_entries.items(),
                key=lambda item: (item[1][0], item[0]),
            )
            try:
                tile_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                return
            self._cache_entries.pop(tile_path)
            self._cache_size_bytes -= size
            self._remove_empty_parents(tile_path.parent)

    def _remove_empty_parents(self, directory: Path) -> None:
        while directory != self.root:
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent

    def _pace_download(self) -> None:
        if self.minimum_download_interval_seconds <= 0:
            return
        with self._download_lock:
            now = monotonic_seconds()
            burst_credit = (
                self.download_burst - 1
            ) * self.minimum_download_interval_seconds
            scheduled = max(self._next_download_at, now - burst_credit)
            if scheduled - now > MIN_SLEEP_SECONDS:
                sleep_seconds(scheduled - now)
            self._next_download_at = scheduled + self.minimum_download_interval_seconds

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


def monotonic_seconds() -> float:
    return time.monotonic()


def sleep_seconds(delay: float) -> None:
    time.sleep(delay)


def default_tile_cache_directory() -> Path:
    configured = os.environ.get(TILE_CACHE_DIRECTORY_ENVIRONMENT)
    if configured:
        return Path(configured)
    cache_home = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache_home) if cache_home else Path.home() / ".cache"
    return root / "GarminActivityMap" / "map_tiles" / "osm"


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
