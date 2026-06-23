from __future__ import annotations

import json
from pathlib import Path

from activity_map.loader import load_directory, load_directory_parallel
from activity_map.loading import PreparedLoad, load_and_prepare_directory


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
