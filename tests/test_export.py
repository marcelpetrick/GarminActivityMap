import getpass as getpass_module
import json
import os
import sys
from argparse import ArgumentParser
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pytest import CaptureFixture, MonkeyPatch

from garmin_export import cli, year_range
from garmin_export.cli import (
    ExportConfig,
    ExportProgress,
    ExportResult,
    RequestExecutor,
    activity_start_date,
    build_client,
    build_export_plan,
    collect_activities,
    collect_activities_by_date,
    date_range_label,
    export_activities,
    extract_activity_id,
    format_duration,
    has_detail_payload,
    is_rate_limit_error,
    is_retryable_error,
    iter_activities,
    load_local_env,
    main,
    month_ranges,
    parse_args,
    throttle_before_detail,
    validate_date_arg,
    write_json,
)
from garmin_export.request_errors import ExportStopped
from garmin_export.year_range import (
    YearRangeConfig,
    default_start_year,
    describe_year_range_results,
    export_config_for_year,
    export_year_range,
    years_inclusive,
)
from garmin_export.year_range import (
    parse_args as parse_year_range_args,
)


class FakeClient:
    def __init__(self) -> None:
        self.detail_calls: list[tuple[str, str]] = []
        self.date_calls: list[tuple[str, str | None, str | None]] = []

    def login(self, tokenstore: str | None = None) -> None:
        return None

    def connectapi(self, path: str, *, params: dict[str, str]) -> Any:
        assert path == cli.ACTIVITY_LIST_PATH
        rows = self.get_activities_by_date(
            params["startDate"], params.get("endDate"), params.get("activityType")
        )
        start, limit = int(params["start"]), int(params["limit"])
        return rows[start : start + limit]

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
        self.date_calls.append((startdate, enddate, activitytype))
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
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
    )

    result = export_activities(client, config)

    assert result.activity_count == 3
    assert result.skipped_existing_count == 0
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
        end_date="2026-05-31",
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
    )

    activities = collect_activities(client, config)

    assert activities == [
        {
            "activityId": 201,
            "startDate": "2026-05-13",
            "endDate": "2026-05-31",
            "activityType": "cycling",
        }
    ]
    assert client.date_calls == [("2026-05-13", "2026-05-31", "cycling")] * 2


def test_month_ranges_split_date_export_into_calendar_windows() -> None:
    assert month_ranges("2025-01-15", "2025-03-02") == (
        ("2025-01-15", "2025-01-31"),
        ("2025-02-01", "2025-02-28"),
        ("2025-03-01", "2025-03-02"),
    )


def test_collect_activities_by_date_deduplicates_chunk_boundaries() -> None:
    class ChunkedClient(FakeClient):
        def get_activities_by_date(
            self,
            startdate: str,
            enddate: str | None = None,
            activitytype: str | None = None,
            sortorder: str | None = None,
        ) -> list[dict[str, Any]]:
            self.date_calls.append((startdate, enddate, activitytype))
            if startdate == "2025-01-01":
                return [{"activityId": 1}, {"activityId": 2}]
            return [{"activityId": 2}, {"activityId": 3}]

    client = ChunkedClient()
    config = ExportConfig(
        output_dir=Path("unused"),
        page_size=2,
        include_details=False,
        activity_type=None,
        start_date="2025-01-01",
        end_date="2025-02-28",
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
    )

    activities = collect_activities_by_date(client, config)

    assert [activity["activityId"] for activity in activities] == [1, 2, 3]
    assert client.date_calls == [
        ("2025-01-01", "2025-01-31", None),
        ("2025-01-01", "2025-01-31", None),
        ("2025-02-01", "2025-02-28", None),
        ("2025-02-01", "2025-02-28", None),
    ]


def test_load_local_env_ignores_password_values(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GARMIN_EMAIL="local@example.invalid"\nGARMIN_PASSWORD="do-not-load"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)

    load_local_env(env_file)

    assert "GARMIN_EMAIL" in os.environ
    assert "GARMIN_PASSWORD" not in os.environ


def test_export_activities_without_details_skips_detail_calls(tmp_path: Path) -> None:
    client = FakeClient()
    config = ExportConfig(
        output_dir=tmp_path,
        page_size=2,
        include_details=False,
        activity_type=None,
        start_date=None,
        end_date=None,
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
    )

    result = export_activities(client, config)
    payload = json.loads((tmp_path / "activities" / "101.json").read_text())

    assert result.activity_count == 3
    assert payload == {
        "summary": {
            "activityId": 101,
            "activityName": "One",
            "activityType": None,
        }
    }
    assert client.detail_calls == []


def test_parse_args_accepts_date_range_and_tokenstore(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARMIN_TOKENSTORE", "/tmp/garmin-tokenstore")

    args = parse_args(
        [
            "--output-dir",
            "exports/test",
            "--page-size",
            "5",
            "--no-details",
            "--activity-type",
            "running",
            "--start-date",
            "2026-05-13",
            "--end-date",
            "2026-06-13",
            "--detail-delay",
            "1.5",
            "--detail-jitter",
            "0.5",
        ]
    )

    assert args.output_dir == Path("exports/test")
    assert args.page_size == 5
    assert args.no_details is True
    assert args.activity_type == "running"
    assert args.start_date == "2026-05-13"
    assert args.end_date == "2026-06-13"
    assert args.detail_delay == 1.5
    assert args.detail_jitter == 0.5
    assert args.no_skip_existing is False
    assert args.tokenstore == "/tmp/garmin-tokenstore"


@pytest.mark.parametrize(
    "argv",
    [
        ["--page-size", "0"],
        ["--detail-delay", "-1"],
        ["--detail-jitter", "-1"],
        ["--start-date", "2026/05/13"],
        ["--end-date", "2026-06-13"],
    ],
)
def test_parse_args_rejects_invalid_values(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_extract_activity_id_supports_known_keys() -> None:
    assert extract_activity_id({"activity_id": 42}) == "42"
    assert extract_activity_id({"id": "abc"}) == "abc"


def test_extract_activity_id_rejects_missing_id() -> None:
    with pytest.raises(ValueError, match="missing an id"):
        extract_activity_id({"activityName": "missing"})


def test_validate_date_arg_accepts_none_and_valid_date() -> None:
    parser = ArgumentParser()

    validate_date_arg(parser, "--start-date", None)
    validate_date_arg(parser, "--start-date", "2026-06-13")


def test_write_json_writes_sorted_pretty_json(tmp_path: Path) -> None:
    output = tmp_path / "payload.json"

    write_json(output, {"z": 1, "a": 2})

    assert output.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "z": 1\n}\n'
    assert not (tmp_path / ".payload.json.tmp").exists()


def test_export_skips_existing_activity_files_by_default(tmp_path: Path) -> None:
    client = FakeClient()
    activity_file = tmp_path / "activities" / "101.json"
    activity_file.parent.mkdir(parents=True)
    activity_file.write_text(
        '{"activity": {"existing": true}, "details": {}, "summary": {}}\n',
        encoding="utf-8",
    )
    config = ExportConfig(
        output_dir=tmp_path,
        page_size=2,
        include_details=True,
        activity_type=None,
        start_date=None,
        end_date=None,
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
    )

    result = export_activities(client, config)

    assert result.activity_count == 3
    assert result.skipped_existing_count == 1
    assert ("summary", "101") not in client.detail_calls
    assert json.loads(activity_file.read_text(encoding="utf-8")) == {
        "activity": {"existing": True},
        "details": {},
        "summary": {},
    }


def test_throttle_before_detail_uses_delay_and_jitter(
    monkeypatch: MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    config = ExportConfig(
        output_dir=Path("unused"),
        page_size=2,
        include_details=True,
        activity_type=None,
        start_date=None,
        end_date=None,
        tokenstore=None,
        detail_delay_seconds=1.0,
        detail_jitter_seconds=2.0,
        skip_existing=True,
    )
    monkeypatch.setattr(cli, "jitter_seconds", lambda maximum: 0.75)
    monkeypatch.setattr(cli, "sleep_seconds", sleeps.append)

    throttle_before_detail(config)

    assert sleeps == [1.75]


def test_export_stops_with_pending_work_after_rate_limit_retries_are_exhausted(
    tmp_path: Path,
) -> None:
    class RateLimitedClient(FakeClient):
        def get_activity(self, activity_id: str) -> dict[str, Any]:
            raise RuntimeError("429 Too Many Requests")

    config = ExportConfig(
        output_dir=tmp_path,
        page_size=2,
        include_details=True,
        activity_type=None,
        start_date=None,
        end_date=None,
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
        max_retries=0,
    )

    with pytest.raises(ExportStopped):
        export_activities(RateLimitedClient(), config)
    state = json.loads((tmp_path / "export-state.json").read_text())

    assert state["failures"] == 0
    assert state["pending"] == 3
    assert state["failed_activity_ids"] == []
    assert state["status"] == "stopped"
    assert not (tmp_path / "manifest.json").exists()


def test_is_rate_limit_error_checks_status_code_and_message() -> None:
    assert is_rate_limit_error(RuntimeError("429 Too Many Requests"))
    assert not is_rate_limit_error(RuntimeError("temporary network failure"))
    assert is_retryable_error(TimeoutError("timed out"))
    assert is_retryable_error(RuntimeError("503 temporarily unavailable"))
    assert not is_retryable_error(ValueError("invalid payload"))


def test_request_executor_retries_with_exponential_backoff(
    monkeypatch: MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []
    config = ExportConfig(
        output_dir=Path("unused"),
        page_size=2,
        include_details=False,
        activity_type=None,
        start_date=None,
        end_date=None,
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
        max_retries=3,
        backoff_initial_seconds=2,
        backoff_max_seconds=5,
    )
    progress = ExportProgress("", "", failed_activity_ids=[])
    monkeypatch.setattr(cli, "sleep_seconds", sleeps.append)

    def flaky_operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("network timeout")
        return "ok"

    result = RequestExecutor(config, progress).call(flaky_operation, "test request")

    assert result == "ok"
    assert attempts == 3
    assert sleeps == [2, 4]
    assert progress.retries == 2


def test_load_local_env_missing_file_is_noop(tmp_path: Path) -> None:
    load_local_env(tmp_path / "missing.env")


def test_load_local_env_respects_existing_values(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GARMIN_EMAIL=file@example.invalid\n", encoding="utf-8")
    monkeypatch.setenv("GARMIN_EMAIL", "existing@example.invalid")

    load_local_env(env_file)

    assert os.environ["GARMIN_EMAIL"] == "existing@example.invalid"


def test_build_client_prompts_for_password_without_env_password(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeGarmin:
        def __init__(
            self,
            email: str,
            password: str,
            prompt_mfa: Any,
            retry_attempts: int,
        ) -> None:
            captured["email"] = email
            captured["password"] = password
            captured["prompt_mfa"] = prompt_mfa
            captured["retry_attempts"] = retry_attempts

    monkeypatch.setenv("GARMIN_EMAIL", "local@example.invalid")
    monkeypatch.setenv("GARMIN_PASSWORD", "must-not-be-used")
    monkeypatch.setattr(getpass_module, "getpass", lambda prompt: "typed-password")
    monkeypatch.setitem(
        sys.modules, "garminconnect", SimpleNamespace(Garmin=FakeGarmin)
    )

    client = build_client()

    assert client is not None
    assert captured["email"] == "local@example.invalid"
    assert captured["password"] == "typed-password"
    assert captured["retry_attempts"] == 0


def test_main_exports_with_built_client(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    client = FakeClient()

    monkeypatch.setattr(cli, "authenticate_client", lambda tokenstore: client)

    exit_code = main(
        [
            "--output-dir",
            str(tmp_path),
            "--page-size",
            "2",
            "--detail-delay",
            "0",
            "--detail-jitter",
            "0",
            "--request-interval",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Exported 3 activities" in output
    assert (tmp_path / "manifest.json").exists()


def failed_export_result(tmp_path: Path) -> ExportResult:
    return ExportResult(
        output_dir=str(tmp_path),
        exported_at="2026-01-01T00:00:00+00:00",
        activity_count=2,
        include_details=True,
        activity_type=None,
        start_date=None,
        end_date=None,
        files=["activities/1.json", "activities/2.json"],
        skipped_existing_count=0,
        failed_count=1,
        retry_count=0,
        downloaded_count=2,
    )


def test_main_returns_failure_when_an_activity_could_not_be_exported(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = FakeClient()
    monkeypatch.setattr(cli, "authenticate_client", lambda tokenstore: client)
    monkeypatch.setattr(
        cli, "export_activities", lambda client, config: failed_export_result(tmp_path)
    )

    assert main(["--output-dir", str(tmp_path)]) == 1


def test_year_range_main_returns_failure_when_any_year_is_incomplete(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = FakeClient()
    monkeypatch.setattr(year_range, "authenticate_client", lambda tokenstore: client)
    monkeypatch.setattr(
        year_range,
        "export_year_range",
        lambda client, config: [failed_export_result(tmp_path)],
    )

    assert (
        year_range.main(["--output-root", str(tmp_path), "--start-year", "2025"]) == 1
    )


def test_export_verbose_logs_progress(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    config = ExportConfig(
        output_dir=tmp_path,
        page_size=2,
        include_details=False,
        activity_type=None,
        start_date="2025-01-01",
        end_date="2025-12-31",
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
        verbose=True,
    )

    export_activities(FakeClient(), config)

    output = capsys.readouterr().out
    assert "Collecting activities for 2025-01-01 to 2025-12-31" in output
    assert "Found 1 activities" in output
    assert "1/1 export activity 201" in output
    assert "1/1 wrote activities/201.json" in output


def test_date_range_label_describes_config() -> None:
    config = ExportConfig(
        output_dir=Path("unused"),
        page_size=2,
        include_details=False,
        activity_type=None,
        start_date=None,
        end_date=None,
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
    )

    assert date_range_label(config) == "all available dates"


class DatedClient(FakeClient):
    def get_activities_by_date(
        self,
        startdate: str,
        enddate: str | None = None,
        activitytype: str | None = None,
        sortorder: str | None = None,
    ) -> list[dict[str, Any]]:
        self.date_calls.append((startdate, enddate, activitytype))
        if startdate != "2025-01-01":
            return []
        return [
            {"activityId": 301, "startTimeLocal": "2025-01-04 09:12:00"},
            {"activityId": 302, "startTimeLocal": "2025-01-19 07:31:00"},
            {"activityId": 303, "startTimeLocal": "2025-01-27 18:02:00"},
        ]


def write_complete_activity(path: Path) -> None:
    write_json(
        path,
        {"activity": {"full": True}, "details": {"metrics": []}, "summary": {}},
    )


def write_summary_only_activity(path: Path) -> None:
    write_json(path, {"summary": {"activityId": int(path.stem)}})


def dated_config(output_dir: Path) -> ExportConfig:
    return ExportConfig(
        output_dir=output_dir,
        page_size=10,
        include_details=True,
        activity_type=None,
        start_date="2025-01-01",
        end_date="2025-12-31",
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
        skip_existing=True,
    )


def test_export_plan_reports_detected_range_and_missing_activities(
    tmp_path: Path,
) -> None:
    config = dated_config(tmp_path)
    activity_dir = tmp_path / "activities"
    activity_dir.mkdir(parents=True)
    write_complete_activity(activity_dir / "301.json")
    client = DatedClient()

    plan = build_export_plan(collect_activities(client, config), config)

    assert plan.total == 3
    assert plan.already_present == 1
    assert plan.missing == 2
    assert plan.summary_only == 0
    assert plan.first_activity_date == "2025-01-04"
    assert plan.last_activity_date == "2025-01-27"
    assert plan.undated_count == 0


def test_export_only_downloads_activities_missing_on_disk(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    activity_dir = tmp_path / "activities"
    activity_dir.mkdir(parents=True)
    write_complete_activity(activity_dir / "301.json")
    preserved = (activity_dir / "301.json").read_text(encoding="utf-8")
    client = DatedClient()

    result = export_activities(client, dated_config(tmp_path))

    assert result.downloaded_count == 2
    assert result.skipped_existing_count == 1
    assert result.activity_count == 3
    assert result.first_activity_date == "2025-01-04"
    assert result.last_activity_date == "2025-01-27"
    assert [call for call in client.detail_calls if call[1] == "301"] == []
    assert ("details", "302") in client.detail_calls
    assert (activity_dir / "301.json").read_text(encoding="utf-8") == preserved

    output = capsys.readouterr().out
    assert "Activities listed : 3 from 2025-01-04 to 2025-01-27" in output
    assert "Already on disk   : 1 (skipped)" in output
    assert "Still to download : 2" in output
    assert "Downloaded        : 2" in output


def test_export_plan_reports_a_complete_local_export(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    activity_dir = tmp_path / "activities"
    activity_dir.mkdir(parents=True)
    for activity_id in (301, 302, 303):
        write_complete_activity(activity_dir / f"{activity_id}.json")
    client = DatedClient()

    result = export_activities(client, dated_config(tmp_path))

    assert result.downloaded_count == 0
    assert client.detail_calls == []
    assert "Nothing to download" in capsys.readouterr().out


def test_summary_only_files_are_completed_with_details(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    activity_dir = tmp_path / "activities"
    activity_dir.mkdir(parents=True)
    write_summary_only_activity(activity_dir / "301.json")
    write_complete_activity(activity_dir / "302.json")
    client = DatedClient()

    result = export_activities(client, dated_config(tmp_path))
    payload = json.loads((activity_dir / "301.json").read_text(encoding="utf-8"))

    assert ("details", "301") in client.detail_calls
    assert ("details", "302") not in client.detail_calls
    assert "details" in payload
    assert result.downloaded_count == 2
    assert result.skipped_existing_count == 1
    assert "Summary only      : 1 (details will be fetched)" in capsys.readouterr().out


def test_summary_only_files_are_kept_when_details_are_disabled(tmp_path: Path) -> None:
    activity_dir = tmp_path / "activities"
    activity_dir.mkdir(parents=True)
    write_summary_only_activity(activity_dir / "301.json")
    config = replace(dated_config(tmp_path), include_details=False)
    client = DatedClient()

    result = export_activities(client, config)

    assert result.skipped_existing_count == 1
    assert result.downloaded_count == 2
    assert client.detail_calls == []


def test_detail_detection_requires_valid_activity_and_details_payloads(
    tmp_path: Path,
) -> None:
    complete = tmp_path / "complete.json"
    complete.write_text(
        json.dumps(
            {
                "summary": {"note": "x" * 2_000},
                "activity": {},
                "details": {"metrics": []},
            }
        ),
        encoding="utf-8",
    )
    summary_only = tmp_path / "summary-only.json"
    summary_only.write_text(
        json.dumps({"summary": {"note": "x" * 2_000}}),
        encoding="utf-8",
    )
    activity_only = tmp_path / "activity-only.json"
    activity_only.write_text(json.dumps({"activity": {}}), encoding="utf-8")
    details_only = tmp_path / "details-only.json"
    details_only.write_text(json.dumps({"details": {}}), encoding="utf-8")
    null_payloads = tmp_path / "null-payloads.json"
    null_payloads.write_text(
        json.dumps({"activity": None, "details": None}), encoding="utf-8"
    )
    truncated = tmp_path / "truncated.json"
    truncated.write_text('{"activity": {}, "details": {', encoding="utf-8")

    assert has_detail_payload(complete) is True
    assert has_detail_payload(summary_only) is False
    assert has_detail_payload(activity_only) is False
    assert has_detail_payload(details_only) is False
    assert has_detail_payload(null_payloads) is False
    assert has_detail_payload(truncated) is False
    assert has_detail_payload(tmp_path / "missing.json") is False


def test_activity_start_date_reads_known_shapes() -> None:
    assert (
        activity_start_date({"startTimeLocal": "2025-03-04 07:00:00"}) == "2025-03-04"
    )
    assert activity_start_date({"startTimeGMT": "2025-03-04T07:00:00"}) == "2025-03-04"
    assert activity_start_date({"beginTimestamp": 1_740_000_000_000}) is not None
    assert activity_start_date({"startTimeLocal": "not-a-date"}) is None
    assert activity_start_date({"activityId": 5}) is None


def test_format_duration_scales_to_hours() -> None:
    assert format_duration(-5) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(125) == "2m 05s"
    assert format_duration(3_725) == "1h 02m 05s"


def test_year_range_summary_lists_per_year_counts(tmp_path: Path) -> None:
    client = DatedClient()
    config = YearRangeConfig(
        start_year=2025,
        end_year=2025,
        output_root=tmp_path,
        page_size=10,
        include_details=False,
        activity_type=None,
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
    )

    results = export_year_range(client, config)
    lines = describe_year_range_results(results)

    assert "Newly downloaded  : 3" in lines[1]
    assert "activities-2025: 3 new, 0 present, 0 failed" in lines[3]
    assert "(2025-01-04 to 2025-01-27)" in lines[3]


def test_years_inclusive_supports_descending_and_ascending_ranges() -> None:
    assert years_inclusive(2025, 2017) == (
        2025,
        2024,
        2023,
        2022,
        2021,
        2020,
        2019,
        2018,
        2017,
    )
    assert years_inclusive(2024, 2026) == (2024, 2025, 2026)


def test_year_range_args_default_to_the_current_year_through_2017() -> None:
    config = parse_year_range_args(["--verbose"])

    assert config.start_year == date.today().year
    assert config.start_year == default_start_year()
    assert config.end_year == 2017
    assert config.output_root == Path("data/garmin")
    assert config.detail_delay_seconds == 2.0
    assert config.detail_jitter_seconds == 2.0
    assert config.verbose is True


def test_default_year_range_covers_the_current_year() -> None:
    config = parse_year_range_args([])

    years = years_inclusive(config.start_year, config.end_year)

    assert years[0] == date.today().year
    assert years[-1] == 2017
    assert len(years) == date.today().year - 2016


def test_export_config_for_year_uses_resumable_activity_directory(
    tmp_path: Path,
) -> None:
    config = YearRangeConfig(
        start_year=2025,
        end_year=2025,
        output_root=tmp_path,
        page_size=50,
        include_details=True,
        activity_type="running",
        tokenstore=None,
        detail_delay_seconds=2.0,
        detail_jitter_seconds=2.0,
        verbose=True,
    )

    year_config = export_config_for_year(config, 2025)

    assert year_config.output_dir == tmp_path / "activities-2025"
    assert year_config.start_date == "2025-01-01"
    assert year_config.end_date == "2025-12-31"
    assert year_config.skip_existing is True
    assert year_config.verbose is True


def test_export_year_range_writes_each_year_directory(tmp_path: Path) -> None:
    client = FakeClient()
    config = YearRangeConfig(
        start_year=2025,
        end_year=2024,
        output_root=tmp_path,
        page_size=2,
        include_details=False,
        activity_type=None,
        tokenstore=None,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
    )

    results = export_year_range(client, config)

    assert [Path(result.output_dir).name for result in results] == [
        "activities-2025",
        "activities-2024",
    ]
    assert (tmp_path / "activities-2025" / "activities" / "201.json").exists()
    assert (tmp_path / "activities-2024" / "activities" / "201.json").exists()
