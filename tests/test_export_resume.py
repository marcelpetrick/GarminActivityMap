import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

from garmin_export import cli
from garmin_export.request_errors import ExportStopped
from tests.test_export import FakeClient, dated_config
from tests.test_export_requests import HttpFailure


class OneActivityClient(FakeClient):
    def get_activities(
        self, start: int = 0, limit: int = 20, activitytype: str | None = None
    ) -> list[dict[str, Any]]:
        return [{"activityId": 101}] if start == 0 else []


@pytest.mark.parametrize(
    "failure", [ValueError("unavailable"), HttpFailure(429), KeyboardInterrupt()]
)
def test_resume_downloads_only_missing_component(
    tmp_path: Path, monkeypatch: MonkeyPatch, failure: BaseException
) -> None:
    client = OneActivityClient()
    config = replace(
        dated_config(tmp_path), start_date=None, end_date=None, max_retries=0
    )

    def fail(activity_id: str) -> dict[str, Any]:
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(client, "get_activity_details", fail)
        if isinstance(failure, ValueError):
            result = cli.export_activities(client, config)
            assert result.failed_count == 1
            assert result.downloaded_count == 0
        else:
            expected = (
                KeyboardInterrupt
                if isinstance(failure, KeyboardInterrupt)
                else ExportStopped
            )
            with pytest.raises(expected):
                cli.export_activities(client, config)

    output = tmp_path / "activities/101.json"
    checkpoint = cli.checkpoint_path(config, "101")
    assert not output.exists()
    assert json.loads(checkpoint.read_text())["activity"]["activityId"] == "101"
    assert checkpoint not in list(tmp_path.rglob("*.json"))

    result = cli.export_activities(client, config)
    assert result.downloaded_count == 1
    assert client.detail_calls == [("summary", "101"), ("details", "101")]
    assert cli.has_detail_payload(output)
    assert not checkpoint.exists()


@pytest.mark.parametrize("component", ["activity", "details"])
def test_existing_partial_json_preserves_valid_component(
    tmp_path: Path, component: str
) -> None:
    output = tmp_path / "activities/101.json"
    output.parent.mkdir()
    cli.write_json(output, {"summary": {"activityId": 101}, component: {"saved": True}})
    client = OneActivityClient()
    config = replace(dated_config(tmp_path), start_date=None, end_date=None)
    cli.export_activities(client, config)
    expected = "details" if component == "activity" else "summary"
    assert client.detail_calls == [(expected, "101")]
    assert json.loads(output.read_text())[component] == {"saved": True}


@pytest.mark.parametrize("checkpoint_contents", ["broken", "[]", '{"activity": null}'])
def test_invalid_checkpoints_are_repaired(
    tmp_path: Path, checkpoint_contents: str
) -> None:
    config = replace(dated_config(tmp_path), start_date=None, end_date=None)
    checkpoint = cli.checkpoint_path(config, "101")
    checkpoint.parent.mkdir()
    checkpoint.write_text(checkpoint_contents)
    client = OneActivityClient()
    result = cli.export_activities(client, config)
    assert result.downloaded_count == 1
    assert client.detail_calls == [("summary", "101"), ("details", "101")]
    assert not checkpoint.exists()


@pytest.mark.parametrize("invalid", [None, [], "invalid"])
def test_invalid_download_is_not_reported_as_complete(
    tmp_path: Path, monkeypatch: MonkeyPatch, invalid: Any
) -> None:
    config = replace(dated_config(tmp_path), start_date=None, end_date=None)
    client = OneActivityClient()
    monkeypatch.setattr(client, "get_activity_details", lambda activity_id: invalid)
    result = cli.export_activities(client, config)
    assert result.downloaded_count == 0
    assert result.failed_count == 1
    assert not (tmp_path / "activities/101.json").exists()
    assert cli.checkpoint_path(config, "101").exists()


def test_force_redownload_does_not_reuse_saved_components(tmp_path: Path) -> None:
    config = replace(
        dated_config(tmp_path), start_date=None, end_date=None, skip_existing=False
    )
    output = tmp_path / "activities/101.json"
    output.parent.mkdir()
    checkpoint = cli.checkpoint_path(config, "101")
    checkpoint.parent.mkdir()
    for path in (output, checkpoint):
        cli.write_json(path, {"activity": {"old": True}, "details": {"old": True}})
    client = OneActivityClient()
    cli.export_activities(client, config)
    assert client.detail_calls == [("summary", "101"), ("details", "101")]
    assert "old" not in json.loads(output.read_text())["activity"]
    assert not checkpoint.exists()


def test_checkpoint_survives_failure_to_publish_final_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config = replace(dated_config(tmp_path), start_date=None, end_date=None)
    client = OneActivityClient()
    output = tmp_path / "activities/101.json"
    write = cli.write_json

    def disk_full(path: Path, payload: Any) -> None:
        if path == output:
            raise OSError("disk full")
        write(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "write_json", disk_full)
        with pytest.raises(OSError, match="disk full"):
            cli.export_activities(client, config)

    assert cli.has_detail_payload(cli.checkpoint_path(config, "101"))
    client.detail_calls.clear()
    result = cli.export_activities(client, config)
    assert result.downloaded_count == 1
    assert client.detail_calls == []
    assert cli.has_detail_payload(output)
