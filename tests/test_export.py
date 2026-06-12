import os
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from garmin_export.cli import (
    ExportConfig,
    collect_activities,
    export_activities,
    iter_activities,
    load_local_env,
)


class FakeClient:
    def __init__(self) -> None:
        self.detail_calls: list[tuple[str, str]] = []

    def login(self, tokenstore: str | None = None) -> None:
        return None

    def get_activities(
        self, start: int = 0, limit: int = 20, activitytype: str | None = None
    ) -> list[dict[str, Any]]:
        activities = [
            {"activityId": 101, "activityName": "One", "activityType": activitytype},
            {"activityId": 102, "activityName": "Two", "activityType": activitytype},
            {"activityId": 103, "activityName": "Three", "activityType": activitytype},
        ]
        return activities[start : start + limit]

    def get_activities_by_date(
        self,
        startdate: str,
        enddate: str | None = None,
        activitytype: str | None = None,
        sortorder: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "activityId": 201,
                "startDate": startdate,
                "endDate": enddate,
                "activityType": activitytype,
            }
        ]

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        self.detail_calls.append(("summary", activity_id))
        return {"activityId": activity_id, "full": True}

    def get_activity_details(self, activity_id: str) -> dict[str, Any]:
        self.detail_calls.append(("details", activity_id))
        return {"activityId": activity_id, "metrics": []}


def test_iter_activities_reads_until_empty_page() -> None:
    client = FakeClient()

    activities = iter_activities(client, page_size=2, activity_type="running")

    assert [activity["activityId"] for activity in activities] == [101, 102, 103]
    assert {activity["activityType"] for activity in activities} == {"running"}


def test_export_activities_writes_manifest_and_activity_files(tmp_path: Path) -> None:
    client = FakeClient()
    config = ExportConfig(
        output_dir=tmp_path,
        page_size=2,
        include_details=True,
        activity_type=None,
        start_date=None,
        end_date=None,
        tokenstore=None,
    )

    result = export_activities(client, config)

    assert result.activity_count == 3
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "activities" / "101.json").exists()
    assert ("details", "101") in client.detail_calls


def test_collect_activities_uses_date_range_when_start_date_is_set() -> None:
    client = FakeClient()
    config = ExportConfig(
        output_dir=Path("unused"),
        page_size=2,
        include_details=True,
        activity_type="cycling",
        start_date="2026-05-13",
        end_date="2026-06-13",
        tokenstore=None,
    )

    activities = collect_activities(client, config)

    assert activities == [
        {
            "activityId": 201,
            "startDate": "2026-05-13",
            "endDate": "2026-06-13",
            "activityType": "cycling",
        }
    ]


def test_load_local_env_ignores_password_values(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GARMIN_EMAIL="local@example.invalid"\n'
        'GARMIN_PASSWORD="do-not-load"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)

    load_local_env(env_file)

    assert "GARMIN_EMAIL" in os.environ
    assert "GARMIN_PASSWORD" not in os.environ
