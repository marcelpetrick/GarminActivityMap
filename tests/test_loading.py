from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from threading import Event

import pytest

import activity_map.loading as loading
import activity_map.prepared_cache as prepared_cache
from activity_map.loader import LoadCancelled, load_directory, load_directory_parallel
from activity_map.loading import PreparedLoad, load_and_prepare_directory
from activity_map.prepared_cache import PreparedGeometryCache, dataset_identity


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


def test_parallel_loader_stops_between_batches_when_cancelled(tmp_path: Path) -> None:
    for activity_id in range(3):
        write_track(tmp_path / f"{activity_id}.json", activity_id)
    cancellation = Event()

    def cancel_after_first_batch(
        _report: object,
        _tracks: object,
    ) -> None:
        cancellation.set()

    with pytest.raises(LoadCancelled, match="cancelled"):
        load_directory_parallel(
            tmp_path,
            workers=1,
            progress=cancel_after_first_batch,
            progress_batch_size=1,
            cancelled=cancellation.is_set,
        )


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


def test_export_control_files_do_not_invalidate_prepared_cache(tmp_path: Path) -> None:
    write_track(tmp_path / "one.json", 1)
    cache = PreparedGeometryCache(tmp_path / "cache")
    original = cache.fingerprint(tmp_path)

    (tmp_path / "export-state.json").write_text(
        json.dumps({"pending": 1}), encoding="utf-8"
    )

    assert cache.fingerprint(tmp_path) == original
    assert load_directory(tmp_path).files_read == 1


def test_prepared_cache_ignores_corrupt_and_disabled_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_track(tmp_path / "one.json", 1)
    cache = PreparedGeometryCache(tmp_path / "cache")
    fingerprint = cache.fingerprint(tmp_path)
    cache.root.mkdir()
    cache.cache_path(tmp_path).write_bytes(b"broken")

    assert cache.load(tmp_path, fingerprint) is None

    monkeypatch.setenv("ACTIVITY_MAP_DISABLE_PREPARED_CACHE", "1")
    assert cache.load(tmp_path, fingerprint) is None


def test_prepared_cache_uses_compact_binary_snapshot(tmp_path: Path) -> None:
    write_track(tmp_path / "one.json", 1)

    load_and_prepare_directory(tmp_path)

    snapshot = PreparedGeometryCache().cache_path(tmp_path)
    assert snapshot.suffix == ".bin"
    assert snapshot.read_bytes()[:1] != b"{"


def test_prepared_cache_invalidates_changed_geometry_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    write_track(dataset / "one.json", 1)
    load_and_prepare_directory(dataset)

    monkeypatch.setattr(prepared_cache, "LOD_TOLERANCES", (0.001, 0.0005))
    cache = PreparedGeometryCache()
    fingerprint = cache.fingerprint(dataset)

    assert cache.load(dataset, fingerprint) is None

    reloaded: list[Path] = []

    def recording_loader(path: Path, **_kwargs: object) -> object:
        reloaded.append(path)
        return load_directory(path)

    monkeypatch.setattr(loading, "load_directory_parallel", recording_loader)
    load_and_prepare_directory(dataset)

    assert reloaded == [dataset]
    snapshots = sorted(
        path.name for path in cache.root.glob(f"{dataset_identity(dataset)}-*.bin")
    )
    assert len(snapshots) == 1


def test_missing_directory_report_is_not_cached(tmp_path: Path) -> None:
    dataset = tmp_path / "later"

    missing = load_and_prepare_directory(dataset)
    dataset.mkdir()
    available = load_and_prepare_directory(dataset)

    assert missing.report.warnings
    assert available.report.warnings == ()


def test_prepared_cache_round_trips_activity_start_dates(tmp_path: Path) -> None:
    dataset = tmp_path / "dated"
    dataset.mkdir()
    (dataset / "one.json").write_text(
        json.dumps(
            {
                "activityId": 7,
                "polyline": [
                    {"lat": 52.0, "lon": 13.0, "time": "2026-06-02T06:00:00Z"},
                    {"lat": 52.001, "lon": 13.001, "time": "2026-06-02T06:01:00Z"},
                    {"lat": 52.002, "lon": 13.002, "time": "2026-06-02T06:02:00Z"},
                ],
            }
        ),
        encoding="utf-8",
    )

    prepared = load_and_prepare_directory(dataset)
    cached = load_and_prepare_directory(dataset)

    assert prepared.render_tracks[0].start_date == date(2026, 6, 2)
    assert cached.render_tracks == prepared.render_tracks
