from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ACTIVITY_MAP_DISABLE_TILES", "1")

from PyQt6.QtWidgets import QApplication

from activity_map.loader import load_directory_parallel
from activity_map.render import prepare_tracks_parallel
from activity_map.widgets import MapCanvas


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark loading 1,000 synthetic tracks through first display."
    )
    parser.add_argument("--tracks", type=positive_int, default=1_000)
    parser.add_argument("--points-per-track", type=positive_int, default=300)
    parser.add_argument("--samples", type=positive_int, default=3)
    parser.add_argument("--loader-workers", type=positive_int, default=1)
    parser.add_argument("--prepare-workers", type=positive_int, default=1)
    parser.add_argument("--width", type=positive_int, default=1_200)
    parser.add_argument("--height", type=positive_int, default=760)
    parser.add_argument(
        "--max-load-to-display-ms",
        type=float,
        help="Exit non-zero when the sum of median stage timings exceeds this limit.",
    )
    return parser.parse_args(argv)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


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
    application = QApplication.instance() or QApplication([])
    canvas = MapCanvas()
    canvas.resize(args.width, args.height)
    with tempfile.TemporaryDirectory(prefix="activity-map-benchmark-") as directory:
        root = Path(directory)
        dataset_write = measure(
            lambda: write_dataset(root, args.tracks, args.points_per_track),
            1,
        )

        reports = []
        load_ms = measure(
            lambda: reports.append(
                load_directory_parallel(root, workers=args.loader_workers)
            ),
            args.samples,
        )
        report = reports[-1]

        prepared_results = []
        prepare_ms = measure(
            lambda: prepared_results.append(
                prepare_tracks_parallel(
                    report.tracks,
                    workers=args.prepare_workers,
                )
            ),
            args.samples,
        )
        prepared = prepared_results[-1]

        set_tracks_ms = measure(
            lambda: canvas.set_prepared_tracks(report.tracks, prepared),
            args.samples,
        )
        first_display_ms = measure(canvas.render_to_pixmap, args.samples)

    load_to_display_ms = load_ms + prepare_ms + set_tracks_ms + first_display_ms
    print("# Activity load-to-display benchmark")
    print()
    print(f"- Platform: {platform.platform()}")
    print(f"- Python: {platform.python_version()}")
    print(f"- Tracks: {args.tracks:,}")
    print(f"- Points per track: {args.points_per_track:,}")
    print(f"- Total source points: {args.tracks * args.points_per_track:,}")
    print(f"- Samples: {args.samples}")
    print(f"- Loader workers: {args.loader_workers}")
    print(f"- Preparation workers: {args.prepare_workers}")
    print(f"- Canvas: {args.width} × {args.height}")
    print()
    print("| Operation | Median |")
    print("|---|---:|")
    print(f"| Synthetic dataset generation (excluded) | {dataset_write:.2f} ms |")
    print(f"| File loading and validation | {load_ms:.2f} ms |")
    print(f"| Render preparation | {prepare_ms:.2f} ms |")
    print(f"| Canvas indexing and retained paths | {set_tracks_ms:.2f} ms |")
    print(f"| First offscreen display | {first_display_ms:.2f} ms |")
    print(f"| **Load to first display** | **{load_to_display_ms:.2f} ms** |")

    canvas.shutdown_tiles()
    del application
    limit = args.max_load_to_display_ms
    if limit is not None and load_to_display_ms > limit:
        print()
        print(
            f"FAIL: {load_to_display_ms:.2f} ms exceeds "
            f"{limit:.2f} ms load-to-display limit"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
