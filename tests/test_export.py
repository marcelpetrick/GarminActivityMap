import getpass as getpass_module
import json
import os
import sys
from argparse import ArgumentParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pytest import CaptureFixture, MonkeyPatch

from garmin_export import cli
from garmin_export.cli import (
    ExportConfig,
    build_client,
    collect_activities,
    date_range_label,
    export_activities,
    extract_activity_id,
    is_rate_limit_error,
    iter_activities,
    load_local_env,
    main,
    parse_args,
    throttle_before_detail,
    validate_date_arg,
    write_json,
)
from garmin_export.year_range import (
    YearRangeConfig,
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
        end_date="2026-06-13",
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
    activity_file.write_text('{"existing": true}\n', encoding="utf-8")
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
    assert json.loads(activity_file.read_text(encoding="utf-8")) == {"existing": True}


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


def test_export_stops_on_rate_limit(tmp_path: Path) -> None:
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
    )

    with pytest.raises(RuntimeError, match="rate-limit"):
        export_activities(RateLimitedClient(), config)


def test_is_rate_limit_error_checks_status_code_and_message() -> None:
    assert is_rate_limit_error(RuntimeError("429 Too Many Requests"))
    assert not is_rate_limit_error(RuntimeError("temporary network failure"))


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
        ) -> None:
            captured["email"] = email
            captured["password"] = password
            captured["prompt_mfa"] = prompt_mfa

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


def test_main_exports_with_built_client(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    client = FakeClient()

    monkeypatch.setattr(cli, "build_client", lambda: client)

    exit_code = main(["--output-dir", str(tmp_path), "--page-size", "2"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Exported 3 activities" in output
    assert (tmp_path / "manifest.json").exists()


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


def test_year_range_args_default_to_2025_through_2017() -> None:
    config = parse_year_range_args(["--verbose"])

    assert config.start_year == 2025
    assert config.end_year == 2017
    assert config.output_root == Path("data/garmin")
    assert config.detail_delay_seconds == 2.0
    assert config.detail_jitter_seconds == 2.0
    assert config.verbose is True


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
