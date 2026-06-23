from __future__ import annotations

import argparse
import os
import platform
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ACTIVITY_MAP_DISABLE_TILES", "1")

from PyQt6.QtWidgets import QApplication

from activity_map.geo import ProjectedPoint, ScreenPoint, Viewport, project_point
from activity_map.models import ActivityTrack, TrackPoint
from activity_map.render import prepare_tracks
from activity_map.widgets import MapCanvas


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    scenario: str
    median_ms: float
    p95_ms: float
    maximum_ms: float
    frames_per_second: float
    visible_tracks: int
    path_draw_calls: int
    selected_points: int
    lod_tolerance: float


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark synthetic Garmin map preparation and interaction."
    )
    parser.add_argument("--tracks", type=positive_int, default=1_000)
    parser.add_argument("--points-per-track", type=positive_int, default=300)
    parser.add_argument("--frames", type=positive_int, default=12)
    parser.add_argument("--width", type=positive_int, default=1_200)
    parser.add_argument("--height", type=positive_int, default=760)
    parser.add_argument(
        "--layout",
        choices=("distributed", "overlap"),
        default="distributed",
    )
    return parser.parse_args(argv)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def synthetic_tracks(
    track_count: int,
    points_per_track: int,
    layout: str = "distributed",
) -> tuple[ActivityTrack, ...]:
    tracks: list[ActivityTrack] = []
    for track_index in range(track_count):
        if layout == "overlap":
            base_latitude = 52.50 + (track_index % 10) * 0.00001
            base_longitude = 13.40 + ((track_index // 10) % 10) * 0.00001
            point_step = 0.000002
        else:
            base_latitude = 52.20 + (track_index % 40) * 0.015
            base_longitude = 13.00 + (track_index // 40) * 0.015
            point_step = 0.00002
        points = tuple(
            TrackPoint(
                latitude=base_latitude + point_index * point_step,
                longitude=(
                    base_longitude
                    + point_index * point_step * 1.25
                    + ((point_index % 20) - 10) * 0.000003
                ),
            )
            for point_index in range(points_per_track)
        )
        tracks.append(
            ActivityTrack(
                activity_id=str(track_index),
                name=f"Synthetic track {track_index}",
                source_file=Path(f"synthetic-{track_index}.json"),
                points=points,
            )
        )
    return tuple(tracks)


def timed(operation: Callable[[], object]) -> float:
    started = time.perf_counter()
    operation()
    return (time.perf_counter() - started) * 1_000.0


def measure_frames(
    scenario: str,
    frame_count: int,
    operation: Callable[[], object],
    canvas: MapCanvas,
) -> BenchmarkResult:
    operation()
    samples = [timed(operation) for _ in range(frame_count)]
    median_ms = statistics.median(samples)
    sorted_samples = sorted(samples)
    p95_index = min(len(sorted_samples) - 1, int(len(sorted_samples) * 0.95))
    return BenchmarkResult(
        scenario=scenario,
        median_ms=median_ms,
        p95_ms=sorted_samples[p95_index],
        maximum_ms=max(samples),
        frames_per_second=1_000.0 / median_ms,
        visible_tracks=canvas.last_visible_track_count,
        path_draw_calls=canvas.last_path_draw_calls,
        selected_points=canvas.last_selected_point_count,
        lod_tolerance=canvas.last_lod_tolerance,
    )


def render_at_zoom(canvas: MapCanvas, center: ProjectedPoint, zoom: float) -> None:
    canvas.viewport = Viewport(
        center=center,
        zoom=zoom,
        width=canvas.width(),
        height=canvas.height(),
    )
    canvas.render_to_pixmap()


def run_benchmarks(
    args: argparse.Namespace,
) -> tuple[float, float, list[BenchmarkResult]]:
    application = QApplication.instance() or QApplication([])
    tracks = synthetic_tracks(args.tracks, args.points_per_track, args.layout)

    preparation_ms = timed(lambda: prepare_tracks(tracks))
    canvas = MapCanvas()
    canvas.resize(args.width, args.height)
    set_tracks_ms = timed(lambda: canvas.set_tracks(tracks))
    center = project_point(TrackPoint(52.50, 13.40))

    results = [
        measure_frames(
            "broad zoom (markers)",
            args.frames,
            lambda: render_at_zoom(canvas, center, 8_000.0),
            canvas,
        ),
        measure_frames(
            "intermediate zoom (simplified)",
            args.frames,
            lambda: render_at_zoom(canvas, center, 120_000.0),
            canvas,
        ),
        measure_frames(
            "deep zoom (adaptive LOD)",
            args.frames,
            lambda: render_at_zoom(canvas, center, 1_000_000.0),
            canvas,
        ),
    ]

    canvas.viewport = Viewport(
        center=center,
        zoom=1_000_000.0,
        width=canvas.width(),
        height=canvas.height(),
    )

    def pan_frame() -> None:
        canvas.viewport = canvas.viewport.pan(8.0, 4.0)
        canvas.render_to_pixmap()

    results.append(measure_frames("deep-zoom pan", args.frames, pan_frame, canvas))

    zoom_anchor = ScreenPoint(canvas.width() / 2.0, canvas.height() / 2.0)

    def zoom_frame() -> None:
        canvas.viewport = canvas.viewport.zoom_at(1.01, zoom_anchor)
        canvas.render_to_pixmap()

    results.append(
        measure_frames("deep-zoom wheel zoom", args.frames, zoom_frame, canvas)
    )
    canvas.shutdown_tiles()
    del application
    return preparation_ms, set_tracks_ms, results


def print_report(
    args: argparse.Namespace,
    preparation_ms: float,
    set_tracks_ms: float,
    results: list[BenchmarkResult],
) -> None:
    total_points = args.tracks * args.points_per_track
    print("# Activity map rendering benchmark")
    print()
    print(f"- Platform: {platform.platform()}")
    print(f"- Python: {platform.python_version()}")
    print(f"- Tracks: {args.tracks:,}")
    print(f"- Points per track: {args.points_per_track:,}")
    print(f"- Total source points: {total_points:,}")
    print(f"- Canvas: {args.width} × {args.height}")
    print(f"- Layout: {args.layout}")
    print(f"- Samples per scenario: {args.frames}")
    print(f"- `prepare_tracks`: {preparation_ms:.2f} ms")
    print(f"- `MapCanvas.set_tracks`: {set_tracks_ms:.2f} ms")
    print()
    print(
        "| Scenario | Median | p95 | Maximum | Median FPS | Visible "
        "| Path calls | Points | LOD tolerance |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for result in results:
        print(
            f"| {result.scenario} | {result.median_ms:.2f} ms "
            f"| {result.p95_ms:.2f} ms | {result.maximum_ms:.2f} ms "
            f"| {result.frames_per_second:.1f} | {result.visible_tracks:,} "
            f"| {result.path_draw_calls:,} | {result.selected_points:,} "
            f"| {result.lod_tolerance:g} |"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    preparation_ms, set_tracks_ms, results = run_benchmarks(args)
    print_report(args, preparation_ms, set_tracks_ms, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
