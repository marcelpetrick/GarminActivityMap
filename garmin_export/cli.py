from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

DEFAULT_OUTPUT_DIR = Path("data/garmin/activities")
DEFAULT_PAGE_SIZE = 100
DEFAULT_DETAIL_DELAY_SECONDS = 3.0
DEFAULT_DETAIL_JITTER_SECONDS = 2.0


class GarminClient(Protocol):
    def login(self, tokenstore: str | None = None) -> Any:
        ...

    def get_activities(
        self, start: int = 0, limit: int = 20, activitytype: str | None = None
    ) -> list[dict[str, Any]]:
        ...

    def get_activities_by_date(
        self,
        startdate: str,
        enddate: str | None = None,
        activitytype: str | None = None,
        sortorder: str | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        ...

    def get_activity_details(self, activity_id: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ExportConfig:
    output_dir: Path
    page_size: int
    include_details: bool
    activity_type: str | None
    start_date: str | None
    end_date: str | None
    tokenstore: str | None
    detail_delay_seconds: float
    detail_jitter_seconds: float
    skip_existing: bool
    verbose: bool = False


@dataclass(frozen=True)
class ExportResult:
    output_dir: str
    exported_at: str
    activity_count: int
    include_details: bool
    activity_type: str | None
    start_date: str | None
    end_date: str | None
    files: list[str]
    skipped_existing_count: int


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = ExportConfig(
        output_dir=args.output_dir,
        page_size=args.page_size,
        include_details=not args.no_details,
        activity_type=args.activity_type,
        start_date=args.start_date,
        end_date=args.end_date,
        tokenstore=args.tokenstore,
        detail_delay_seconds=args.detail_delay,
        detail_jitter_seconds=args.detail_jitter,
        skip_existing=not args.no_skip_existing,
        verbose=args.verbose,
    )

    client = build_client()
    client.login(config.tokenstore)
    result = export_activities(client, config)

    print(
        f"Exported {result.activity_count} activities to {result.output_dir}; "
        f"manifest: {config.output_dir / 'manifest.json'}"
    )
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Garmin Connect activities to ignored local JSON files."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for JSON exports. Default: {DEFAULT_OUTPUT_DIR}",
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
        "--start-date",
        help="Optional export start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end-date",
        help="Optional export end date in YYYY-MM-DD format.",
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
        "--no-skip-existing",
        action="store_true",
        help="Re-download activity files even when they already exist.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print timestamped progress while collecting and exporting activities.",
    )
    args = parser.parse_args(argv)

    if args.page_size < 1:
        parser.error("--page-size must be at least 1")
    if args.detail_delay < 0:
        parser.error("--detail-delay must be at least 0")
    if args.detail_jitter < 0:
        parser.error("--detail-jitter must be at least 0")
    validate_date_arg(parser, "--start-date", args.start_date)
    validate_date_arg(parser, "--end-date", args.end_date)
    if args.end_date and not args.start_date:
        parser.error("--end-date requires --start-date")

    return args


def build_client() -> GarminClient:
    try:
        from garminconnect import Garmin  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: run `python -m pip install -r requirements.txt`."
        ) from exc

    load_local_env(Path(".env"))
    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ")
    password = getpass.getpass("Garmin password: ")
    return cast(
        GarminClient,
        Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: ")),
    )


def export_activities(client: GarminClient, config: ExportConfig) -> ExportResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    activity_dir = config.output_dir / "activities"
    activity_dir.mkdir(exist_ok=True)

    exported_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    files: list[str] = []
    skipped_existing_count = 0
    verbose_log(config.verbose, f"Collecting activities for {date_range_label(config)}")
    activities = collect_activities(client, config)
    activity_total = len(activities)
    verbose_log(config.verbose, f"Found {activity_total} activities")

    for index, activity in enumerate(activities, start=1):
        activity_id = extract_activity_id(activity)
        relative_file = Path("activities") / f"{activity_id}.json"
        output_file = config.output_dir / relative_file
        progress = f"{index}/{activity_total}"

        if config.skip_existing and output_file.exists():
            verbose_log(
                config.verbose,
                f"{progress} skip existing activity {activity_id}",
            )
            files.append(relative_file.as_posix())
            skipped_existing_count += 1
            continue

        payload: dict[str, Any] = {"summary": activity}
        verbose_log(config.verbose, f"{progress} export activity {activity_id}")

        if config.include_details:
            throttle_before_detail(config)
            verbose_log(
                config.verbose,
                f"{progress} fetch activity payload {activity_id}",
            )
            try:
                payload["activity"] = client.get_activity(activity_id)
                throttle_before_detail(config)
                verbose_log(
                    config.verbose,
                    f"{progress} fetch activity details {activity_id}",
                )
                payload["details"] = client.get_activity_details(activity_id)
            except Exception as exc:
                if is_rate_limit_error(exc):
                    raise RuntimeError(
                        "Garmin returned a rate-limit response. "
                        "Stopping export so the account is not hammered. "
                        "Wait before retrying; existing files will be skipped "
                        "by default on the next run."
                    ) from exc
                raise

        write_json(output_file, payload)
        verbose_log(config.verbose, f"{progress} wrote {relative_file.as_posix()}")
        files.append(relative_file.as_posix())

    manifest = ExportResult(
        output_dir=str(config.output_dir),
        exported_at=exported_at,
        activity_count=len(files),
        include_details=config.include_details,
        activity_type=config.activity_type,
        start_date=config.start_date,
        end_date=config.end_date,
        files=files,
        skipped_existing_count=skipped_existing_count,
    )
    write_json(config.output_dir / "manifest.json", asdict(manifest))
    return manifest


def collect_activities(
    client: GarminClient, config: ExportConfig
) -> list[dict[str, Any]]:
    if config.start_date:
        return collect_activities_by_date(client, config)

    return iter_activities(client, config.page_size, config.activity_type)


def collect_activities_by_date(
    client: GarminClient,
    config: ExportConfig,
) -> list[dict[str, Any]]:
    if config.start_date is None:
        return []

    if config.end_date is None:
        return client.get_activities_by_date(
            startdate=config.start_date,
            activitytype=config.activity_type,
        )

    activities_by_id: dict[str, dict[str, Any]] = {}
    for start_date, end_date in month_ranges(config.start_date, config.end_date):
        verbose_log(
            config.verbose,
            f"Collecting date window {start_date} to {end_date}",
        )
        activities = client.get_activities_by_date(
            startdate=start_date,
            enddate=end_date,
            activitytype=config.activity_type,
        )
        verbose_log(
            config.verbose,
            f"Found {len(activities)} activities in {start_date} to {end_date}",
        )
        for activity in activities:
            activities_by_id.setdefault(extract_activity_id(activity), activity)

    return list(activities_by_id.values())


def month_ranges(start_date: str, end_date: str) -> tuple[tuple[str, str], ...]:
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if end < start:
        raise ValueError("end_date must not be before start_date")

    ranges: list[tuple[str, str]] = []
    current = start
    while current <= end:
        next_month = first_day_of_next_month(current)
        window_end = min(next_month - timedelta(days=1), end)
        ranges.append((current.isoformat(), window_end.isoformat()))
        current = window_end + timedelta(days=1)
    return tuple(ranges)


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def first_day_of_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def iter_activities(
    client: GarminClient, page_size: int, activity_type: str | None
) -> list[dict[str, Any]]:
    start = 0
    activities: list[dict[str, Any]] = []

    while True:
        page = client.get_activities(
            start=start, limit=page_size, activitytype=activity_type
        )
        if not page:
            return activities
        activities.extend(page)
        if len(page) < page_size:
            return activities
        start += len(page)


def extract_activity_id(activity: dict[str, Any]) -> str:
    for key in ("activityId", "activity_id", "id"):
        value = activity.get(key)
        if value:
            return str(value)
    raise ValueError(f"Activity is missing an id field: {activity!r}")


def throttle_before_detail(config: ExportConfig) -> None:
    delay = config.detail_delay_seconds
    if config.detail_jitter_seconds:
        delay += jitter_seconds(config.detail_jitter_seconds)
    if delay > 0:
        sleep_seconds(delay)


def jitter_seconds(maximum: float) -> float:
    return random.uniform(0.0, maximum)


def sleep_seconds(delay: float) -> None:
    time.sleep(delay)


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    return status_code == 429 or "429" in text or "too many requests" in text


def date_range_label(config: ExportConfig) -> str:
    if config.start_date and config.end_date:
        return f"{config.start_date} to {config.end_date}"
    if config.start_date:
        return f"from {config.start_date}"
    return "all available dates"


def verbose_log(enabled: bool, message: str) -> None:
    if not enabled:
        return
    timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    print(f"[{timestamp}] {message}", flush=True)


def validate_date_arg(
    parser: argparse.ArgumentParser, argument_name: str, value: str | None
) -> None:
    if value is None:
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        parser.error(f"{argument_name} must use YYYY-MM-DD format")


def write_json(path: Path, payload: Any) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True, ensure_ascii=False)
            file.write("\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_local_env(path: Path, allowed_keys: set[str] | None = None) -> None:
    allowed = allowed_keys or {"GARMIN_EMAIL", "GARMIN_TOKENSTORE"}
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in allowed:
            os.environ.setdefault(key, value.strip().strip("\"'"))
