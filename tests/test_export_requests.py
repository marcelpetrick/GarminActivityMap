import getpass
from dataclasses import replace
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from garmin_export import cli
from tests.test_export import dated_config


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
