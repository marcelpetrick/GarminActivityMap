import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any, Self

import pytest
from pytest import MonkeyPatch

from garmin_export import cli
from garmin_export.estimates import expected_request_wait
from tests.test_export import FakeClient, dated_config, write_complete_activity


@pytest.mark.parametrize(
    "interval,delay,jitter,expected",
    [
        (1, 2, 2, 3),
        (5, 2, 2, 5),
        (2, 1, 2, 2.25),
        (2, 2, 0, 2),
        (0, 0, 0, 0),
        (3, 1, 2, 3),
        (0, 1, 2, 2),
    ],
)
def test_pacing_estimate_accounts_for_overlapping_waits(
    interval: float, delay: float, jitter: float, expected: float
) -> None:
    assert expected_request_wait(interval, delay, jitter) == expected


def test_initial_estimate_for_46_missing_activities_is_276_seconds(
    tmp_path: Path,
) -> None:
    config = replace(
        dated_config(tmp_path),
        request_interval_seconds=1,
        detail_delay_seconds=2,
        detail_jitter_seconds=2,
    )
    plan = cli.build_export_plan([{"activityId": i} for i in range(1, 47)], config)
    assert plan.detail_requests == 92
    assert cli.estimated_seconds(plan, config) == 276
    assert "4m 36s" in cli.describe_plan(plan, config)[-1]
    assert "network and disk time additional" in cli.describe_plan(plan, config)[-1]


def test_plan_counts_only_missing_payloads_and_respects_force_download(
    tmp_path: Path,
) -> None:
    config = dated_config(tmp_path)
    activities = [{"activityId": i} for i in range(1, 6)]
    output = tmp_path / "activities"
    output.mkdir()
    partial = tmp_path / ".partial"
    partial.mkdir()
    write_complete_activity(output / "1.json")
    cli.write_json(output / "2.json", {"summary": {"activityId": 2}})
    cli.write_json(partial / "3.part", {"activity": {}})
    cli.write_json(partial / "4.part", {"activity": {}, "details": {}})
    cli.write_json(output / "5.json", {"details": {}})

    plan = cli.build_export_plan(activities, config)
    assert plan.missing == 4
    assert plan.detail_requests == 4
    forced = cli.build_export_plan(activities, replace(config, skip_existing=False))
    assert forced.detail_requests == 10
    summaries = cli.build_export_plan(
        activities, replace(config, include_details=False)
    )
    assert summaries.detail_requests == 0
    assert cli.estimated_seconds(summaries, config) == 0


@pytest.mark.parametrize("skipped_first", [0, 527])
@pytest.mark.parametrize("retry_details", [False, True])
def test_live_eta_ignores_listing_and_skips_and_measures_retries(
    tmp_path: Path, monkeypatch: MonkeyPatch, skipped_first: int, retry_details: bool
) -> None:
    clock = [0.0]
    snapshots: list[dict[str, Any]] = []
    base = datetime(2026, 9, 19, tzinfo=UTC).timestamp()

    class ExportClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(base + clock[0], tz)

    def advance(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(cli, "datetime", ExportClock)
    monkeypatch.setattr(cli, "monotonic_seconds", lambda: clock[0])
    monkeypatch.setattr(cli, "sleep_seconds", advance)
    save_progress = cli.write_progress

    def capture(path: Path, progress: cli.ExportProgress) -> None:
        snapshots.append(asdict(progress))
        save_progress(path, progress)

    monkeypatch.setattr(cli, "write_progress", capture)
    existing = list(range(1, skipped_first + 1))
    middle, tail = [10003, 10004, 10005], [10006, 10007]
    rows = [{"activityId": i} for i in [*existing, 10001, *middle, 10002, *tail]]
    output = tmp_path / "activities"
    output.mkdir()
    for activity_id in [*existing, *middle, *tail]:
        write_complete_activity(output / f"{activity_id}.json")
    complete_check = cli.is_complete_export

    def slow_local_check(path: Path, include_details: bool) -> bool:
        advance(1)
        return complete_check(path, include_details)

    monkeypatch.setattr(cli, "is_complete_export", slow_local_check)

    class Client(FakeClient):
        retried = False

        def get_activities(
            self, start: int = 0, limit: int = 20, activitytype: str | None = None
        ) -> list[dict[str, Any]]:
            advance(100)  # Slow listing must not influence the download samples.
            return rows[start : start + limit]

        def get_activity(self, activity_id: str) -> dict[str, Any]:
            advance(2)
            return super().get_activity(activity_id)

        def get_activity_details(self, activity_id: str) -> dict[str, Any]:
            advance(2)
            if retry_details and not self.retried:
                self.retried = True
                raise TimeoutError("network timeout")
            return super().get_activity_details(activity_id)

    config = replace(
        dated_config(tmp_path),
        start_date=None,
        end_date=None,
        page_size=1000,
        request_interval_seconds=1,
        detail_delay_seconds=3,
    )
    result = cli.export_activities(Client(), config)
    assert result.downloaded_count == 2
    assert result.skipped_existing_count == skipped_first + 5

    observed_samples: set[int] = set()
    for snapshot in snapshots:
        estimate = snapshot["download_estimate"]
        if estimate is None or estimate["completed_requests"] not in {1, 2}:
            continue
        observed_samples.add(estimate["completed_requests"])
        remaining = (
            datetime.fromisoformat(snapshot["estimated_completion_at"])
            - datetime.fromisoformat(snapshot["updated_at"])
        ).total_seconds()
        expected = (
            15 if estimate["completed_requests"] == 1 else (14 if retry_details else 10)
        )
        assert remaining == expected
    assert observed_samples == {1, 2}
    final = snapshots[-1]
    assert final["download_estimate"]["completed_requests"] == 4
    assert final["download_estimate"]["elapsed_seconds"] == (
        24 if retry_details else 20
    )
    assert final["download_estimate"]["remaining_requests"] == 0
    assert final["estimated_completion_at"] == final["updated_at"]


@pytest.mark.parametrize("failed_component", ["activity", "details"])
def test_failed_activities_remove_abandoned_requests_from_eta(
    tmp_path: Path, failed_component: str
) -> None:
    class Client(FakeClient):
        def get_activity(self, activity_id: str) -> dict[str, Any]:
            if activity_id == "101" and failed_component == "activity":
                raise ValueError("unavailable")
            return super().get_activity(activity_id)

        def get_activity_details(self, activity_id: str) -> dict[str, Any]:
            if activity_id == "101" and failed_component == "details":
                raise ValueError("unavailable")
            return super().get_activity_details(activity_id)

    config = replace(dated_config(tmp_path), start_date=None, end_date=None)
    result = cli.export_activities(Client(), config)
    state = json.loads((tmp_path / "export-state.json").read_text())
    assert result.failed_count == 1
    assert state["download_estimate"]["remaining_requests"] == 0
    assert state["download_estimate"]["completed_requests"] == (
        4 if failed_component == "activity" else 5
    )
    assert state["estimated_completion_at"] == state["updated_at"]


def test_summary_export_has_no_network_download_estimate(tmp_path: Path) -> None:
    config = replace(
        dated_config(tmp_path),
        start_date=None,
        end_date=None,
        include_details=False,
    )
    client = FakeClient()
    plan = cli.build_export_plan(client.get_activities(), config)
    assert "local file writes only" in cli.describe_plan(plan, config)[-1]
    cli.export_activities(client, config)
    state = json.loads((tmp_path / "export-state.json").read_text())
    assert state["download_estimate"]["completed_requests"] == 0
    assert state["download_estimate"]["remaining_requests"] == 0
