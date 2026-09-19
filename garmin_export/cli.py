from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

from .request_errors import ExportStopped, retry_after_seconds, status_code

DEFAULT_OUTPUT_DIR = Path("data/garmin/activities")
DEFAULT_PAGE_SIZE = 100
DEFAULT_DETAIL_DELAY_SECONDS = 3.0
DEFAULT_DETAIL_JITTER_SECONDS = 2.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_INITIAL_SECONDS = 2.0
DEFAULT_BACKOFF_MAX_SECONDS = 60.0
PROGRESS_REPORT_INTERVAL = 10
DETAIL_KEYS = frozenset({"activity", "details"})
ACTIVITY_LIST_PATH = "/activitylist-service/activities/search/activities"
MAX_ACTIVITY_PAGES = 10_000
T = TypeVar("T")


class GarminClient(Protocol):
    def login(self, tokenstore: str | None = None) -> Any: ...

    def get_activities(
        self, start: int = 0, limit: int = 20, activitytype: str | None = None
    ) -> list[dict[str, Any]]: ...

    def connectapi(self, path: str, *, params: dict[str, str]) -> Any: ...

    def get_activity(self, activity_id: str) -> dict[str, Any]: ...

    def get_activity_details(self, activity_id: str) -> dict[str, Any]: ...


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
    request_interval_seconds: float = 0.0
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_initial_seconds: float = DEFAULT_BACKOFF_INITIAL_SECONDS
    backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS


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
    failed_count: int
    retry_count: int
    downloaded_count: int = 0
    first_activity_date: str | None = None
    last_activity_date: str | None = None


@dataclass(frozen=True)
class ExportPlan:
    total: int
    already_present: int
    missing: int
    summary_only: int
    first_activity_date: str | None
    last_activity_date: str | None
    undated_count: int


@dataclass
class ExportProgress:
    started_at: str
    updated_at: str
    total: int = 0
    completed: int = 0
    pending: int = 0
    failures: int = 0
    retries: int = 0
    estimated_completion_at: str | None = None
    failed_activity_ids: list[str] | None = None
    status: str = "collecting"
    stopped_reason: str | None = None


class RequestExecutor:
    def __init__(self, config: ExportConfig, progress: ExportProgress) -> None:
        self.config = config
        self.progress = progress
        self._last_request_at: float | None = None
        self._stopped: ExportStopped | None = None

    def call(self, operation: Callable[[], T], description: str) -> T:
        if self._stopped is not None:
            raise self._stopped
        attempt = 0
        while True:
            self._pace()
            try:
                result = operation()
                self._last_request_at = monotonic_seconds()
                return result
            except Exception as exc:
                self._last_request_at = monotonic_seconds()
                status = status_code(exc)
                if status in {401, 403} or (
                    status == 429 and attempt >= self.config.max_retries
                ):
                    self._stopped = ExportStopped(
                        f"Stopped export after HTTP {status} for {description}; "
                        "remaining activities are pending. Resume later."
                    )
                    raise self._stopped from exc
                if not is_retryable_error(exc) or attempt >= self.config.max_retries:
                    raise
                delay = min(
                    self.config.backoff_initial_seconds * (2**attempt),
                    self.config.backoff_max_seconds,
                )
                server_delay = retry_after_seconds(exc)
                if server_delay is not None:
                    delay = max(delay, server_delay)
                elif status == 429:
                    delay = max(delay, 60.0)
                attempt += 1
                self.progress.retries += 1
                verbose_log(
                    self.config.verbose,
                    f"Retry {attempt}/{self.config.max_retries} for {description} "
                    f"after {delay:g}s: {exc}",
                )
                sleep_seconds(delay)

    def _pace(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = monotonic_seconds() - self._last_request_at
        remaining = self.config.request_interval_seconds - elapsed
        if remaining > 0:
            sleep_seconds(remaining)


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
        request_interval_seconds=args.request_interval,
        max_retries=args.max_retries,
        backoff_initial_seconds=args.backoff_initial,
        backoff_max_seconds=args.backoff_max,
    )

    try:
        client = authenticate_client(config.tokenstore)
        result = export_activities(client, config)
    except ExportStopped as exc:
        print(str(exc))
        return 1

    print(
        f"Exported {result.activity_count} activities to {result.output_dir}; "
        f"manifest: {config.output_dir / 'manifest.json'}"
    )
    return 1 if result.failed_count else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    load_local_env(Path(".env"))
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
        default=default_tokenstore(),
        help="Token directory. Default: GARMIN_TOKENSTORE or ~/.garminconnect.",
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
    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
        help="Minimum seconds between Garmin requests. Default: 1 second.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Retries for transient Garmin failures. Default: {DEFAULT_MAX_RETRIES}",
    )
    parser.add_argument(
        "--backoff-initial",
        type=float,
        default=DEFAULT_BACKOFF_INITIAL_SECONDS,
        help="Initial exponential retry delay in seconds.",
    )
    parser.add_argument(
        "--backoff-max",
        type=float,
        default=DEFAULT_BACKOFF_MAX_SECONDS,
        help="Maximum exponential retry delay in seconds.",
    )
    args = parser.parse_args(argv)

    if args.page_size < 1:
        parser.error("--page-size must be at least 1")
    if args.detail_delay < 0:
        parser.error("--detail-delay must be at least 0")
    if args.detail_jitter < 0:
        parser.error("--detail-jitter must be at least 0")
    if args.request_interval < 0:
        parser.error("--request-interval must be at least 0")
    if args.max_retries < 0:
        parser.error("--max-retries must be at least 0")
    if args.backoff_initial < 0 or args.backoff_max < 0:
        parser.error("backoff values must be at least 0")
    if args.backoff_max < args.backoff_initial:
        parser.error("--backoff-max must be at least --backoff-initial")
    validate_date_arg(parser, "--start-date", args.start_date)
    validate_date_arg(parser, "--end-date", args.end_date)
    if args.end_date and not args.start_date:
        parser.error("--end-date requires --start-date")

    return args


def default_tokenstore() -> str:
    return os.getenv("GARMIN_TOKENSTORE") or str(Path.home() / ".garminconnect")


def build_client(*, prompt_credentials: bool = True) -> GarminClient:
    try:
        from garminconnect import Garmin  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: run `python -m pip install -r requirements.txt`."
        ) from exc

    if not prompt_credentials:
        return cast(GarminClient, Garmin(retry_attempts=0))
    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ")
    password = getpass.getpass("Garmin password: ")
    return cast(
        GarminClient,
        Garmin(
            email,
            password,
            prompt_mfa=lambda: input("Garmin MFA code: "),
            retry_attempts=0,
        ),
    )


def authenticate_client(tokenstore: str | None) -> GarminClient:
    client = build_client(prompt_credentials=False)
    from garminconnect import GarminConnectAuthenticationError

    try:
        login_with_stop(client, tokenstore)
        return client
    except GarminConnectAuthenticationError:
        # Missing, unreadable or rejected cached credentials require user login.
        client = build_client()
        login_with_stop(client, tokenstore)
        return client


def login_with_stop(client: GarminClient, tokenstore: str | None) -> None:
    try:
        client.login(tokenstore)
    except Exception as exc:
        status = status_code(exc)
        if status in {403, 429}:
            raise ExportStopped(
                f"Stopped login after HTTP {status}; try again later."
            ) from exc
        raise


def export_activities(
    client: GarminClient,
    config: ExportConfig,
    executor: RequestExecutor | None = None,
) -> ExportResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    activity_dir = config.output_dir / "activities"
    activity_dir.mkdir(exist_ok=True)

    exported_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    started_at = monotonic_seconds()
    progress = ExportProgress(
        started_at=exported_at,
        updated_at=exported_at,
        failed_activity_ids=[],
    )
    executor = executor or RequestExecutor(config, progress)
    executor.progress = progress
    files: list[str] = []
    skipped_existing_count = 0
    downloaded_count = 0
    print(f"Collecting Garmin activity list for {date_range_label(config)} ...")
    verbose_log(config.verbose, f"Collecting activities for {date_range_label(config)}")
    write_progress(config.output_dir, progress)
    try:
        activities = collect_activities(client, config, executor)
    except ExportStopped as exc:
        record_stopped_export(config, progress, exc)
        raise
    activity_total = len(activities)
    progress.total = activity_total
    progress.pending = activity_total
    progress.status = "downloading"
    write_progress(config.output_dir, progress)
    verbose_log(config.verbose, f"Found {activity_total} activities")
    plan = build_export_plan(activities, config)
    for line in describe_plan(plan, config):
        print(line)

    for index, activity in enumerate(activities, start=1):
        activity_id = extract_activity_id(activity)
        relative_file = Path("activities") / f"{activity_id}.json"
        output_file = config.output_dir / relative_file
        progress_label = f"{index}/{activity_total}"

        if config.skip_existing and is_complete_export(
            output_file, config.include_details
        ):
            verbose_log(
                config.verbose,
                f"{progress_label} skip existing activity {activity_id}",
            )
            files.append(relative_file.as_posix())
            skipped_existing_count += 1
            progress.completed += 1
            progress.pending -= 1
            update_progress(config.output_dir, progress)
            continue

        payload: dict[str, Any] = {"summary": activity}
        verbose_log(config.verbose, f"{progress_label} export activity {activity_id}")

        if config.include_details:
            try:
                payload = complete_activity_payload(
                    client, config, executor, activity, output_file
                )
            except ExportStopped as exc:
                record_stopped_export(config, progress, exc)
                raise
            except Exception as exc:
                progress.failures += 1
                progress.pending -= 1
                if progress.failed_activity_ids is not None:
                    progress.failed_activity_ids.append(activity_id)
                update_progress(config.output_dir, progress)
                verbose_log(
                    config.verbose,
                    f"{progress_label} failed activity {activity_id}: {exc}",
                )
                continue

        write_json(output_file, payload)
        if config.include_details:
            checkpoint_path(config, activity_id).unlink(missing_ok=True)
        verbose_log(
            config.verbose,
            f"{progress_label} wrote {relative_file.as_posix()}",
        )
        files.append(relative_file.as_posix())
        downloaded_count += 1
        progress.completed += 1
        progress.pending -= 1
        update_progress(config.output_dir, progress)
        if downloaded_count % PROGRESS_REPORT_INTERVAL == 0:
            print(
                f"  {progress_label} activities processed; "
                f"{downloaded_count} downloaded, "
                f"{skipped_existing_count} already present, "
                f"{progress.failures} failed" + estimated_completion_label(progress)
            )

    progress.status = "incomplete" if progress.failures else "complete"
    update_progress(config.output_dir, progress)
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
        failed_count=progress.failures,
        retry_count=progress.retries,
        downloaded_count=downloaded_count,
        first_activity_date=plan.first_activity_date,
        last_activity_date=plan.last_activity_date,
    )
    write_json(config.output_dir / "manifest.json", asdict(manifest))
    for line in describe_result(manifest, monotonic_seconds() - started_at):
        print(line)
    return manifest


def checkpoint_path(config: ExportConfig, activity_id: str) -> Path:
    # .part files are excluded from the map loader's recursive *.json scan.
    return config.output_dir / ".partial" / f"{activity_id}.part"


def complete_activity_payload(
    client: GarminClient,
    config: ExportConfig,
    executor: RequestExecutor,
    activity: dict[str, Any],
    output_file: Path,
) -> dict[str, Any]:
    activity_id = extract_activity_id(activity)
    checkpoint = checkpoint_path(config, activity_id)
    payload: dict[str, Any] = {"summary": activity}
    if config.skip_existing:
        for source in (output_file, checkpoint):
            saved = load_export_payload(source)
            for key in DETAIL_KEYS:
                if isinstance(saved.get(key), dict):
                    payload[key] = saved[key]

    for key, fetch in (
        ("activity", client.get_activity),
        ("details", client.get_activity_details),
    ):
        if key in payload:
            continue
        throttle_before_detail(config)
        verbose_log(config.verbose, f"Fetch {key} payload for activity {activity_id}")
        component = executor.call(partial(fetch, activity_id), f"{key} {activity_id}")
        if not isinstance(component, dict):
            raise ValueError(f"Invalid {key} payload for activity {activity_id}")
        payload[key] = component
        checkpoint.parent.mkdir(exist_ok=True)
        write_json(checkpoint, payload)
    return payload


def record_stopped_export(
    config: ExportConfig, progress: ExportProgress, exc: ExportStopped
) -> None:
    progress.status = "stopped"
    progress.stopped_reason = str(exc)
    progress.estimated_completion_at = None
    progress.updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    write_progress(config.output_dir, progress)


def build_export_plan(
    activities: Sequence[dict[str, Any]],
    config: ExportConfig,
) -> ExportPlan:
    already_present = 0
    summary_only = 0
    dates: list[str] = []
    undated_count = 0
    for activity in activities:
        activity_date = activity_start_date(activity)
        if activity_date is None:
            undated_count += 1
        else:
            dates.append(activity_date)
        output_file = (
            config.output_dir / "activities" / f"{extract_activity_id(activity)}.json"
        )
        if not config.skip_existing:
            continue
        if is_complete_export(output_file, config.include_details):
            already_present += 1
        elif output_file.exists():
            summary_only += 1
    return ExportPlan(
        total=len(activities),
        already_present=already_present,
        missing=len(activities) - already_present,
        summary_only=summary_only,
        first_activity_date=min(dates) if dates else None,
        last_activity_date=max(dates) if dates else None,
        undated_count=undated_count,
    )


def is_complete_export(path: Path, include_details: bool) -> bool:
    if not path.exists():
        return False
    if not include_details:
        return True
    return has_detail_payload(path)


def has_detail_payload(path: Path) -> bool:
    payload = load_export_payload(path)
    return all(isinstance(payload.get(key), dict) for key in DETAIL_KEYS)


def load_export_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except OSError, ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def describe_plan(plan: ExportPlan, config: ExportConfig) -> tuple[str, ...]:
    lines = [
        f"Export plan for {date_range_label(config)}",
        f"  Output directory  : {config.output_dir}",
        f"  Activities listed : {plan.total}{covered_range_label(plan)}",
        f"  Already on disk   : {plan.already_present} (skipped)",
        f"  Still to download : {plan.missing}",
    ]
    if not config.skip_existing:
        lines[3] = "  Already on disk   : re-downloading, --no-skip-existing is set"
    if plan.summary_only:
        lines.append(
            f"  Summary only      : {plan.summary_only} (details will be fetched)"
        )
    if plan.undated_count:
        lines.append(f"  Without a date    : {plan.undated_count}")
    if plan.missing:
        lines.append(
            f"  Estimated runtime : {format_duration(estimated_seconds(plan, config))}"
        )
    else:
        lines.append("  Nothing to download; the local export is already complete.")
    return tuple(lines)


def describe_result(result: ExportResult, elapsed_seconds: float) -> tuple[str, ...]:
    return (
        f"Export finished for {result.output_dir} in "
        f"{format_duration(elapsed_seconds)}",
        f"  Downloaded        : {result.downloaded_count}",
        f"  Already present   : {result.skipped_existing_count}",
        f"  Failed            : {result.failed_count} "
        f"(retried {result.retry_count} times)",
        f"  Manifest entries  : {result.activity_count}",
    )


def estimated_completion_label(progress: ExportProgress) -> str:
    if progress.estimated_completion_at is None:
        return ""
    return f"; estimated completion {progress.estimated_completion_at}"


def covered_range_label(plan: ExportPlan) -> str:
    if plan.first_activity_date is None or plan.last_activity_date is None:
        return ""
    if plan.first_activity_date == plan.last_activity_date:
        return f" on {plan.first_activity_date}"
    return f" from {plan.first_activity_date} to {plan.last_activity_date}"


def estimated_seconds(plan: ExportPlan, config: ExportConfig) -> float:
    requests_per_activity = 2 if config.include_details else 0
    per_activity = requests_per_activity * (
        config.request_interval_seconds
        + config.detail_delay_seconds
        + config.detail_jitter_seconds / 2.0
    )
    return plan.missing * max(per_activity, config.request_interval_seconds)


def format_duration(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3_600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {remaining_seconds:02d}s"
    if minutes:
        return f"{minutes}m {remaining_seconds:02d}s"
    return f"{remaining_seconds}s"


def activity_start_date(activity: dict[str, Any]) -> str | None:
    for key in ("startTimeLocal", "startTimeGMT", "startDate", "beginTimestamp"):
        value = activity.get(key)
        if isinstance(value, str) and len(value) >= 10:
            candidate = value[:10]
            try:
                datetime.strptime(candidate, "%Y-%m-%d")
            except ValueError:
                continue
            return candidate
        if isinstance(value, int | float) and not isinstance(value, bool):
            seconds = float(value)
            if abs(seconds) > 10_000_000_000:
                seconds /= 1_000.0
            try:
                return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()
            except OSError, OverflowError, ValueError:
                continue
    return None


def collect_activities(
    client: GarminClient,
    config: ExportConfig,
    executor: RequestExecutor | None = None,
) -> list[dict[str, Any]]:
    request_executor = executor or RequestExecutor(
        config,
        ExportProgress("", "", failed_activity_ids=[]),
    )
    if config.start_date:
        return collect_activities_by_date(client, config, request_executor)

    return iter_activities(
        client,
        config.page_size,
        config.activity_type,
        request_executor,
    )


def collect_activities_by_date(
    client: GarminClient,
    config: ExportConfig,
    executor: RequestExecutor | None = None,
) -> list[dict[str, Any]]:
    if config.start_date is None:
        return []

    request_executor = executor or RequestExecutor(
        config,
        ExportProgress("", "", failed_activity_ids=[]),
    )
    activities_by_id: dict[str, dict[str, Any]] = {}
    windows = (
        month_ranges(config.start_date, config.end_date)
        if config.end_date is not None
        else ((config.start_date, None),)
    )
    for start_date, end_date in windows:
        verbose_log(
            config.verbose,
            f"Collecting date window {start_date} to {end_date}",
        )
        activities = collect_activity_pages(
            partial(
                fetch_date_page,
                client,
                config,
                start_date,
                end_date,
            ),
            request_executor,
            f"activities {start_date} to {end_date}",
        )
        verbose_log(
            config.verbose,
            f"Found {len(activities)} activities in {start_date} to {end_date}",
        )
        for activity in activities:
            activities_by_id.setdefault(extract_activity_id(activity), activity)

    return list(activities_by_id.values())


def fetch_date_page(
    client: GarminClient,
    config: ExportConfig,
    start_date: str,
    end_date: str | None,
    offset: int,
) -> list[dict[str, Any]]:
    params = {
        "startDate": start_date,
        "start": str(offset),
        "limit": str(config.page_size),
    }
    if end_date is not None:
        params["endDate"] = end_date
    if config.activity_type is not None:
        params["activityType"] = config.activity_type
    page = client.connectapi(ACTIVITY_LIST_PATH, params=params)
    if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
        raise ValueError("Garmin activity page must be a list of activity objects")
    return page


def collect_activity_pages(
    fetch_page: Callable[[int], list[dict[str, Any]]],
    executor: RequestExecutor | None,
    description: str,
) -> list[dict[str, Any]]:
    offset = 0
    activities: dict[str, dict[str, Any]] = {}
    for _ in range(MAX_ACTIVITY_PAGES):
        operation = partial(fetch_page, offset)
        page = (
            operation()
            if executor is None
            else executor.call(operation, f"{description} at offset {offset}")
        )
        if not page:
            return list(activities.values())
        previous_count = len(activities)
        for activity in page:
            activities.setdefault(extract_activity_id(activity), activity)
        if len(activities) == previous_count:
            raise ValueError("Garmin pagination made no progress; stopping export")
        # Advance by the actual page length: Garmin may cap the requested limit.
        offset += len(page)
    raise ValueError(f"Garmin pagination exceeded {MAX_ACTIVITY_PAGES} pages")


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
    client: GarminClient,
    page_size: int,
    activity_type: str | None,
    executor: RequestExecutor | None = None,
) -> list[dict[str, Any]]:
    return collect_activity_pages(
        partial(client.get_activities, limit=page_size, activitytype=activity_type),
        executor,
        "activities page",
    )


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
    return status_code(exc) == 429


def is_retryable_error(exc: Exception) -> bool:
    status = status_code(exc)
    if status is not None:
        return status == 429 or 500 <= status <= 599
    text = str(exc).lower()
    retry_markers = (
        "timeout",
        "timed out",
        "connection",
        "network",
        "temporarily unavailable",
    )
    return isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(
        marker in text for marker in retry_markers
    )


def monotonic_seconds() -> float:
    return time.monotonic()


def update_progress(output_dir: Path, progress: ExportProgress) -> None:
    progress.updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    processed = progress.completed + progress.failures
    if processed and progress.pending:
        started = datetime.fromisoformat(progress.started_at)
        elapsed = max((datetime.now(UTC) - started).total_seconds(), 0.0)
        remaining_seconds = elapsed / processed * progress.pending
        progress.estimated_completion_at = (
            (datetime.now(UTC) + timedelta(seconds=remaining_seconds))
            .replace(microsecond=0)
            .isoformat()
        )
    elif not progress.pending:
        progress.estimated_completion_at = progress.updated_at
    write_progress(output_dir, progress)


def write_progress(output_dir: Path, progress: ExportProgress) -> None:
    write_json(output_dir / "export-state.json", asdict(progress))


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
