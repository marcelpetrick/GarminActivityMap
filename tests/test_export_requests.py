import getpass
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pytest import MonkeyPatch

from garmin_export import cli, year_range
from garmin_export.request_errors import (
    ExportStopped,
    parse_retry_after,
    retry_after_seconds,
    status_code,
)
from tests.test_export import FakeClient, dated_config


class HttpFailure(RuntimeError):
    def __init__(self, status: int, retry_after: str | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.response = SimpleNamespace(
            status_code=status,
            headers={} if retry_after is None else {"Retry-After": retry_after},
        )


@pytest.fixture
def clock(monkeypatch: MonkeyPatch) -> list[float]:
    now = [0.0]

    def sleep(delay: float) -> None:
        now[0] += delay

    monkeypatch.setattr(cli, "monotonic_seconds", lambda: now[0])
    monkeypatch.setattr(cli, "sleep_seconds", sleep)
    return now


def test_retry_budget_counts_actual_transport_attempts(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import garminconnect  # type: ignore[import-untyped]

    monkeypatch.setenv("GARMIN_EMAIL", "offline@example.invalid")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "offline-password")
    client = cli.build_client()
    calls = 0

    def unavailable(path: str) -> None:
        nonlocal calls
        calls += 1
        raise garminconnect.requests.ConnectionError("network unavailable")

    monkeypatch.setattr(client.client, "connectapi", unavailable)  # type: ignore[attr-defined]
    monkeypatch.setattr(cli, "sleep_seconds", lambda delay: None)
    config = replace(dated_config(tmp_path), max_retries=5)
    progress = cli.ExportProgress("", "")
    with pytest.raises(garminconnect.GarminConnectConnectionError):
        cli.RequestExecutor(config, progress).call(
            lambda: client.get_activity("101"), "activity 101"
        )

    assert calls == 6
    assert progress.retries == 5


@pytest.mark.parametrize("header, minimum", [("120", 120), (None, 60), ("bad", 60)])
def test_rate_limit_cooldown_then_success(
    tmp_path: Path, clock: list[float], header: str | None, minimum: float
) -> None:
    calls: list[float] = []

    def request() -> str:
        calls.append(clock[0])
        if len(calls) == 1:
            raise HttpFailure(429, header)
        return "ok"

    executor = cli.RequestExecutor(dated_config(tmp_path), cli.ExportProgress("", ""))
    assert executor.call(request, "details") == "ok"
    assert calls == [0, minimum]


@pytest.mark.parametrize("status, expected_calls", [(429, 6), (403, 1), (401, 1)])
def test_run_stops_before_other_activities_or_years(
    tmp_path: Path, clock: list[float], status: int, expected_calls: int
) -> None:
    class BlockedClient(FakeClient):
        def get_activity(self, activity_id: str) -> dict[str, Any]:
            self.detail_calls.append(("activity", activity_id))
            raise HttpFailure(status)

    client = BlockedClient()
    config = replace(
        year_range.parse_args(["--start-year", "2025", "--end-year", "2024"]),
        output_root=tmp_path,
        detail_delay_seconds=0,
        detail_jitter_seconds=0,
    )
    with pytest.raises(ExportStopped):
        year_range.export_year_range(client, config)

    assert len(client.detail_calls) == expected_calls
    assert {activity_id for _, activity_id in client.detail_calls} == {"201"}
    assert all(start.startswith("2025") for start, _, _ in client.date_calls)
    assert not (tmp_path / "activities-2024").exists()
    state = json.loads((tmp_path / "activities-2025/export-state.json").read_text())
    assert state["status"] == "stopped"
    assert state["pending"] == 1
    assert state["failures"] == 0
    assert state["estimated_completion_at"] is None


def test_stopped_executor_cannot_send_more_requests(tmp_path: Path) -> None:
    calls = 0

    def denied() -> None:
        nonlocal calls
        calls += 1
        raise HttpFailure(403)

    executor = cli.RequestExecutor(dated_config(tmp_path), cli.ExportProgress("", ""))
    for _ in range(2):
        with pytest.raises(ExportStopped):
            executor.call(denied, "activity")
    assert calls == 1


@pytest.mark.parametrize("use_year_range", [False, True])
def test_cli_returns_failure_when_listing_is_denied(
    tmp_path: Path, monkeypatch: MonkeyPatch, use_year_range: bool
) -> None:
    class DeniedClient(FakeClient):
        def get_activities(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            raise HttpFailure(403)

        def get_activities_by_date(
            self, *_args: Any, **_kwargs: Any
        ) -> list[dict[str, Any]]:
            raise HttpFailure(403)

    module = year_range if use_year_range else cli
    monkeypatch.setattr(module, "build_client", DeniedClient)
    args = (
        ["--output-root", str(tmp_path), "--start-year", "2025", "--end-year", "2025"]
        if use_year_range
        else ["--output-dir", str(tmp_path)]
    )
    assert module.main(args) == 1
    root = tmp_path / "activities-2025" if use_year_range else tmp_path
    state = json.loads((root / "export-state.json").read_text())
    assert state["status"] == "stopped"
    assert "HTTP 403" in state["stopped_reason"]


def test_wrapped_errors_preserve_status_and_server_cooldown() -> None:
    outer = RuntimeError("Rate limit exceeded")
    inner = HttpFailure(429, "120")
    outer.__cause__ = inner
    inner.__context__ = outer  # Malformed exception chains must still terminate.
    assert status_code(outer) == 429
    assert retry_after_seconds(outer) == 120
    assert cli.is_rate_limit_error(outer)
    assert not cli.is_retryable_error(HttpFailure(404))


@pytest.mark.parametrize("value", ["invalid", "nan", "inf", "-inf"])
def test_invalid_retry_after_is_ignored(value: str) -> None:
    assert parse_retry_after(value) is None


def test_retry_after_supports_http_dates_and_past_dates() -> None:
    future = datetime.now(UTC) + timedelta(seconds=120)
    delay = parse_retry_after(format_datetime(future, usegmt=True))
    assert delay is not None and 118 <= delay <= 120
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0
    assert parse_retry_after("-1") == 0


def test_request_spacing_is_preserved_between_years(
    tmp_path: Path, clock: list[float]
) -> None:
    calls: list[float] = []

    class EmptyClient(FakeClient):
        def get_activities_by_date(
            self, *_args: Any, **_kwargs: Any
        ) -> list[dict[str, Any]]:
            calls.append(clock[0])
            return []

    config = replace(
        year_range.parse_args(["--start-year", "2025", "--end-year", "2024"]),
        output_root=tmp_path,
        include_details=False,
    )
    year_range.export_year_range(EmptyClient(), config)
    assert calls == list(range(24))


def test_date_pages_are_paced_and_retry_only_the_failed_page(
    tmp_path: Path, clock: list[float]
) -> None:
    import garminconnect

    client = garminconnect.Garmin(retry_attempts=0)
    calls: list[tuple[int, float]] = []

    def transport(path: str, *, params: dict[str, str]) -> list[dict[str, int]]:
        assert path == "/activitylist-service/activities/search/activities"
        assert params["limit"] == "100"
        assert params["startDate"] == "2025-01-01"
        assert params["endDate"] == "2025-01-31"
        assert params["activityType"] == "running"
        offset = int(params["start"])
        calls.append((offset, clock[0]))
        if len(calls) == 2:
            raise TimeoutError("network timeout")
        # Exercise a server cap below the requested page size.
        return (
            [{"activityId": offset + i + 1} for i in range(20)] if offset < 40 else []
        )

    client.client.connectapi = transport
    config = replace(
        dated_config(tmp_path),
        page_size=100,
        end_date="2025-01-31",
        activity_type="running",
        request_interval_seconds=1,
    )
    rows = cli.collect_activities_by_date(client, config)
    assert [row["activityId"] for row in rows] == list(range(1, 41))
    assert calls == [(0, 0), (20, 1), (20, 3), (40, 4)]


def test_open_ended_date_query_uses_explicit_pages(tmp_path: Path) -> None:
    calls: list[dict[str, str]] = []

    class Client(FakeClient):
        def connectapi(self, path: str, *, params: dict[str, str]) -> Any:
            calls.append(params)
            return [{"activityId": 1}] if params["start"] == "0" else []

    config = replace(dated_config(tmp_path), end_date=None, page_size=50)
    assert cli.collect_activities_by_date(Client(), config) == [{"activityId": 1}]
    assert [params["start"] for params in calls] == ["0", "1"]
    assert all(params["limit"] == "50" for params in calls)
    assert all(
        "endDate" not in params and "activityType" not in params for params in calls
    )


@pytest.mark.parametrize("payload", [None, {}, [None], ["invalid"]])
def test_invalid_page_payload_is_rejected(tmp_path: Path, payload: Any) -> None:
    class Client(FakeClient):
        def connectapi(self, path: str, *, params: dict[str, str]) -> Any:
            return payload

    with pytest.raises(ValueError, match="list of activity objects"):
        cli.collect_activities_by_date(Client(), dated_config(tmp_path))


def test_repeated_pages_stop_instead_of_looping() -> None:
    offsets: list[int] = []

    def repeated(offset: int) -> list[dict[str, Any]]:
        offsets.append(offset)
        return [{"activityId": 1}]

    with pytest.raises(ValueError, match="no progress"):
        cli.collect_activity_pages(repeated, None, "activities")
    assert offsets == [0, 1]


def test_endless_unique_pages_are_bounded(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "MAX_ACTIVITY_PAGES", 2)
    with pytest.raises(ValueError, match="exceeded 2 pages"):
        cli.collect_activity_pages(
            lambda offset: [{"activityId": offset + 1}], None, "activities"
        )
