from __future__ import annotations

import argparse
import getpass
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


DEFAULT_OUTPUT_DIR = Path("data/garmin/activities")
DEFAULT_PAGE_SIZE = 100


class GarminClient(Protocol):
    def login(self, tokenstore: str | None = None) -> Any:
        ...

    def get_activities(
        self, start: int = 0, limit: int = 20, activitytype: str | None = None
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
    tokenstore: str | None


@dataclass(frozen=True)
class ExportResult:
    output_dir: str
    exported_at: str
    activity_count: int
    include_details: bool
    activity_type: str | None
    files: list[str]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = ExportConfig(
        output_dir=args.output_dir,
        page_size=args.page_size,
        include_details=not args.no_details,
        activity_type=args.activity_type,
        tokenstore=args.tokenstore,
    )

    client = build_client()
    client.login(config.tokenstore)
    result = export_activities(client, config)

    print(
        f"Exported {result.activity_count} activities to {result.output_dir}; "
        f"manifest: {config.output_dir / 'manifest.json'}"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
        help="Optional Garmin activity type filter such as running, cycling, or swimming.",
    )
    parser.add_argument(
        "--tokenstore",
        default=os.getenv("GARMIN_TOKENSTORE"),
        help="Optional garminconnect token directory. Defaults to the package default.",
    )
    args = parser.parse_args(argv)

    if args.page_size < 1:
        parser.error("--page-size must be at least 1")

    return args


def build_client() -> GarminClient:
    try:
        from garminconnect import Garmin
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: run `python -m pip install -r requirements.txt`."
        ) from exc

    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ")
    password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    return Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: "))


def export_activities(client: GarminClient, config: ExportConfig) -> ExportResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    activity_dir = config.output_dir / "activities"
    activity_dir.mkdir(exist_ok=True)

    exported_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    files: list[str] = []

    for activity in iter_activities(client, config.page_size, config.activity_type):
        activity_id = extract_activity_id(activity)
        payload: dict[str, Any] = {"summary": activity}

        if config.include_details:
            payload["activity"] = client.get_activity(activity_id)
            payload["details"] = client.get_activity_details(activity_id)

        relative_file = Path("activities") / f"{activity_id}.json"
        write_json(config.output_dir / relative_file, payload)
        files.append(relative_file.as_posix())

    manifest = ExportResult(
        output_dir=str(config.output_dir),
        exported_at=exported_at,
        activity_count=len(files),
        include_details=config.include_details,
        activity_type=config.activity_type,
        files=files,
    )
    write_json(config.output_dir / "manifest.json", asdict(manifest))
    return manifest


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


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True, ensure_ascii=False)
        file.write("\n")
