from __future__ import annotations

import json
from pathlib import Path

import pytest

import activity_map.loading as loading
from activity_map.loader import load_directory, load_directory_parallel
from activity_map.loading import PreparedLoad, load_and_prepare_directory
from activity_map.prepared_cache import PreparedGeometryCache


@pytest.fixture(autouse=True)
def isolated_prepared_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ACTIVITY_MAP_PREPARED_CACHE_DIR",
        str(tmp_path / "prepared-cache"),
    )


def write_track(path: Path, activity_id: int) -> None:
    path.write_text(
        json.dumps(
            {
                "activityId": activity_id,
                "polyline": [
                    {"lat": 52.0, "lon": 13.0},
                    {"lat": 52.001, "lon": 13.001},
                    {"lat": 52.002, "lon": 13.002},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_parallel_loader_matches_sequential_loader(tmp_path: Path) -> None:
    for activity_id in range(8):
        write_track(tmp_path / f"{activity_id}.json", activity_id)

    sequential = load_directory(tmp_path)
    parallel = load_directory_parallel(tmp_path, workers=3)

    assert parallel == sequential


def test_load_and_prepare_directory_returns_complete_snapshot(tmp_path: Path) -> None:
    write_track(tmp_path / "one.json", 1)

    result = load_and_prepare_directory(
        tmp_path,
        loader_workers=2,
        preparation_workers=1,
    )

    assert len(result.report.tracks) == 1
    assert len(result.render_tracks) == 1


def test_load_and_prepare_directory_publishes_incremental_batches(
    tmp_path: Path,
) -> None:
    for activity_id in range(3):
        write_track(tmp_path / f"{activity_id}.json", activity_id)
    updates: list[PreparedLoad] = []

    result = load_and_prepare_directory(tmp_path, progress=updates.append)

    assert len(result.report.tracks) == 3
    assert sum(len(update.render_tracks) for update in updates) == 3
    assert updates[-1].report.tracks == result.report.tracks


def test_load_and_prepare_directory_reuses_prepared_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_track(tmp_path / "one.json", 1)
    expected = load_and_prepare_directory(tmp_path)
    monkeypatch.setattr(
        loading,
        "load_directory_parallel",
        lambda *_args, **_kwargs: pytest.fail("loader should not run"),
    )
    updates: list[PreparedLoad] = []

    cached = load_and_prepare_directory(tmp_path, progress=updates.append)

    assert cached == expected
    assert updates == [expected]


def test_prepared_cache_invalidates_changed_dataset(tmp_path: Path) -> None:
    source = tmp_path / "one.json"
    write_track(source, 1)
    first = load_and_prepare_directory(tmp_path)
    write_track(source, 2)

    second = load_and_prepare_directory(tmp_path)

    assert first.report.tracks[0].activity_id == "1"
    assert second.report.tracks[0].activity_id == "2"


def test_prepared_cache_ignores_corrupt_and_disabled_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_track(tmp_path / "one.json", 1)
    cache = PreparedGeometryCache(tmp_path / "cache")
    fingerprint = cache.fingerprint(tmp_path)
    cache.root.mkdir()
    cache.cache_path(tmp_path).write_text("{broken", encoding="utf-8")

    assert cache.load(tmp_path, fingerprint) is None

    monkeypatch.setenv("ACTIVITY_MAP_DISABLE_PREPARED_CACHE", "1")
    assert cache.load(tmp_path, fingerprint) is None
