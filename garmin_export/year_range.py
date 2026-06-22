from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .cli import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    ExportConfig,
    ExportResult,
    GarminClient,
    build_client,
    export_activities,
    validate_date_arg,
    verbose_log,
)

DEFAULT_START_YEAR = 2025
DEFAULT_END_YEAR = 2017
DEFAULT_OUTPUT_ROOT = Path("data/garmin")
DEFAULT_DETAIL_DELAY_SECONDS = 2.0
DEFAULT_DETAIL_JITTER_SECONDS = 2.0


@dataclass(frozen=True)
class YearRangeConfig:
    start_year: int
    end_year: int
    output_root: Path
    page_size: int
    include_details: bool
    activity_type: str | None
    tokenstore: str | None
    detail_delay_seconds: float
    detail_jitter_seconds: float
    verbose: bool = False
    request_interval_seconds: float = 0.0
    max_retries: int = 5
    backoff_initial_seconds: float = 2.0
    backoff_max_seconds: float = 60.0


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    client = build_client()
    client.login(config.tokenstore)
    results = export_year_range(client, config)

    total_activities = sum(result.activity_count for result in results)
    total_skipped = sum(result.skipped_existing_count for result in results)
    print(
        "Finished Garmin year export: "
        f"{len(results)} years, {total_activities} manifest entries, "
        f"{total_skipped} existing activity files skipped."
    )
    return 0


def parse_args(argv: Sequence[str] | None = None) -> YearRangeConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Export Garmin activities year by year with one login and resumable "
            "per-activity JSON files."
        )
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"First year to export. Default: {DEFAULT_START_YEAR}",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
        help=f"Last year to export. Default: {DEFAULT_END_YEAR}",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=(
            "Parent directory for activities-YYYY folders. "
            f"Default: {DEFAULT_OUTPUT_ROOT}"
        ),
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Activities to request per Garmin API page. Default: {DEFAULT_PAGE_SIZE}",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Only export paged activity summaries, not per-activity detail payloads.",
    )
    parser.add_argument(
        "--activity-type",
        help=(
            "Optional Garmin activity type filter such as running, cycling, "
            "or swimming."
        ),
    )
    parser.add_argument(
        "--tokenstore",
        default=os.getenv("GARMIN_TOKENSTORE"),
        help="Optional garminconnect token directory. Defaults to the package default.",
    )
    parser.add_argument(
        "--detail-delay",
        type=float,
        default=DEFAULT_DETAIL_DELAY_SECONDS,
        help=(
            "Seconds to wait before downloading details for each activity. "
            f"Default: {DEFAULT_DETAIL_DELAY_SECONDS}"
        ),
    )
    parser.add_argument(
        "--detail-jitter",
        type=float,
        default=DEFAULT_DETAIL_JITTER_SECONDS,
        help=(
            "Additional random seconds added to each detail wait. "
            f"Default: {DEFAULT_DETAIL_JITTER_SECONDS}"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print timestamped progress while collecting and exporting activities.",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
        help="Minimum seconds between Garmin requests. Default: 1 second.",
    )
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--backoff-initial", type=float, default=2.0)
    parser.add_argument("--backoff-max", type=float, default=60.0)
    args = parser.parse_args(argv)

    if args.page_size < 1:
        parser.error("--page-size must be at least 1")
    if args.detail_delay < 0:
        parser.error("--detail-delay must be at least 0")
    if args.detail_jitter < 0:
        parser.error("--detail-jitter must be at least 0")
    if args.request_interval < 0 or args.max_retries < 0:
        parser.error("request interval and retries must be at least 0")
    if args.backoff_initial < 0 or args.backoff_max < args.backoff_initial:
        parser.error("invalid backoff range")
    for year in (args.start_year, args.end_year):
        validate_year(parser, year)

    return YearRangeConfig(
        start_year=args.start_year,
        end_year=args.end_year,
        output_root=args.output_root,
        page_size=args.page_size,
        include_details=not args.no_details,
        activity_type=args.activity_type,
        tokenstore=args.tokenstore,
        detail_delay_seconds=args.detail_delay,
        detail_jitter_seconds=args.detail_jitter,
        verbose=args.verbose,
        request_interval_seconds=args.request_interval,
        max_retries=args.max_retries,
        backoff_initial_seconds=args.backoff_initial,
        backoff_max_seconds=args.backoff_max,
    )


def export_year_range(
    client: GarminClient,
    config: YearRangeConfig,
) -> list[ExportResult]:
    results: list[ExportResult] = []
    for year in years_inclusive(config.start_year, config.end_year):
        verbose_log(config.verbose, f"Exporting Garmin activities for {year}")
        result = export_activities(client, export_config_for_year(config, year))
        results.append(result)
        verbose_log(
            config.verbose,
            (
                f"Finished {year}: {result.activity_count} manifest entries, "
                f"{result.skipped_existing_count} existing files skipped, "
                f"output {result.output_dir}"
            ),
        )
    return results


def export_config_for_year(config: YearRangeConfig, year: int) -> ExportConfig:
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    validate_date_arg(argparse.ArgumentParser(), "--start-date", start_date)
    validate_date_arg(argparse.ArgumentParser(), "--end-date", end_date)
    return ExportConfig(
        output_dir=config.output_root / f"activities-{year}",
        page_size=config.page_size,
        include_details=config.include_details,
        activity_type=config.activity_type,
        start_date=start_date,
        end_date=end_date,
        tokenstore=config.tokenstore,
        detail_delay_seconds=config.detail_delay_seconds,
        detail_jitter_seconds=config.detail_jitter_seconds,
        skip_existing=True,
        verbose=config.verbose,
        request_interval_seconds=config.request_interval_seconds,
        max_retries=config.max_retries,
        backoff_initial_seconds=config.backoff_initial_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
    )


def years_inclusive(start_year: int, end_year: int) -> tuple[int, ...]:
    step = -1 if start_year >= end_year else 1
    return tuple(range(start_year, end_year + step, step))


def validate_year(parser: argparse.ArgumentParser, year: int) -> None:
    if year < 1900 or year > 2200:
        parser.error("years must be between 1900 and 2200")


if __name__ == "__main__":
    raise SystemExit(main())
