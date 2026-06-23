from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from activity_map.loader import load_directory, load_directory_parallel
from activity_map.render import prepare_tracks_parallel


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark synthetic activity file loading and preparation."
    )
    parser.add_argument("--tracks", type=int, default=1_000)
    parser.add_argument("--points-per-track", type=int, default=300)
    parser.add_argument("--samples", type=int, default=3)
    return parser.parse_args(argv)


def write_dataset(root: Path, tracks: int, points_per_track: int) -> None:
    for track_index in range(tracks):
        points = [
            {
                "lat": 52.5 + point_index * 0.000002,
                "lon": 13.4 + point_index * 0.0000025,
            }
            for point_index in range(points_per_track)
        ]
        (root / f"{track_index:06d}.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "activityId": track_index,
                        "activityName": f"Synthetic {track_index}",
                    },
                    "details": {"geoPolylineDTO": {"polyline": points}},
                }
            ),
            encoding="utf-8",
        )


def measure(operation: Callable[[], object], samples: int) -> float:
    timings = []
    for _ in range(samples):
        started = time.perf_counter()
        operation()
        timings.append((time.perf_counter() - started) * 1_000.0)
    return statistics.median(timings)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="activity-map-benchmark-") as directory:
        root = Path(directory)
        write_dataset(root, args.tracks, args.points_per_track)
        serial_report = load_directory(root)
        serial_load = measure(lambda: load_directory(root), args.samples)
        parallel_load = measure(
            lambda: load_directory_parallel(root, workers=4),
            args.samples,
        )
        serial_prepare = measure(
            lambda: prepare_tracks_parallel(serial_report.tracks, workers=1),
            args.samples,
        )
        process_prepare = measure(
            lambda: prepare_tracks_parallel(serial_report.tracks, workers=4),
            args.samples,
        )

    print("# Activity loading benchmark")
    print()
    print(f"- Tracks: {args.tracks:,}")
    print(f"- Points per track: {args.points_per_track:,}")
    print(f"- Samples: {args.samples}")
    print()
    print("| Operation | Median |")
    print("|---|---:|")
    print(f"| Sequential file loading | {serial_load:.2f} ms |")
    print(f"| Four-thread file loading | {parallel_load:.2f} ms |")
    print(f"| Sequential render preparation | {serial_prepare:.2f} ms |")
    print(f"| Four-process render preparation | {process_prepare:.2f} ms |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
