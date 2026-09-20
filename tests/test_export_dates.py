from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Self

import pytest
from pytest import MonkeyPatch

from garmin_export import year_range
from tests.test_export import FakeClient


class ExportDay(date):
    @classmethod
    def today(cls) -> Self:
        return cls(2026, 9, 19)


def test_current_year_queries_stop_at_today(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(year_range, "date", ExportDay)
    config = replace(
        year_range.parse_args(["--start-year", "2026", "--end-year", "2026"]),
        output_root=tmp_path,
        include_details=False,
        request_interval_seconds=0,
    )
    client = FakeClient()
    results = year_range.export_year_range(client, config)

    windows = list(dict.fromkeys((start, end) for start, end, _ in client.date_calls))
    assert len(windows) == 9
    assert windows[0] == ("2026-01-01", "2026-01-31")
    assert windows[-1] == ("2026-09-01", "2026-09-19")
    assert results[0].end_date == "2026-09-19"


@pytest.mark.parametrize(
    "today", [date(2026, 1, 1), date(2024, 2, 29), date(2026, 12, 31)]
)
def test_calendar_boundaries_preserve_history_and_include_today(today: date) -> None:
    config = year_range.parse_args([])
    current = year_range.export_config_for_year(config, today.year, today)
    previous = year_range.export_config_for_year(config, today.year - 1, today)
    assert current.start_date == f"{today.year}-01-01"
    assert current.end_date == today.isoformat()
    assert previous.end_date == f"{today.year - 1}-12-31"


@pytest.mark.parametrize(
    "start,end,expected",
    [(2027, 2025, [2026, 2025]), (2025, 2027, [2025, 2026]), (2027, 2028, [])],
)
def test_future_years_do_not_issue_activity_requests(
    tmp_path: Path, monkeypatch: MonkeyPatch, start: int, end: int, expected: list[int]
) -> None:
    monkeypatch.setattr(year_range, "date", ExportDay)
    config = replace(
        year_range.parse_args(["--start-year", str(start), "--end-year", str(end)]),
        output_root=tmp_path,
        include_details=False,
        request_interval_seconds=0,
    )
    client = FakeClient()
    results = year_range.export_year_range(client, config)
    assert [int(Path(result.output_dir).name[-4:]) for result in results] == expected
    assert all(int(startdate[:4]) <= 2026 for startdate, _, _ in client.date_calls)
    assert bool(client.date_calls) == bool(expected)
    assert not (tmp_path / "activities-2027").exists()


def test_future_year_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="future year"):
        year_range.export_config_for_year(
            year_range.parse_args([]), 2027, ExportDay.today()
        )
