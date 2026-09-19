import getpass
import json
from pathlib import Path
from typing import Any

import garminconnect  # type: ignore[import-untyped]
import pytest
from pytest import MonkeyPatch

from garmin_export import cli, year_range
from garmin_export.request_errors import ExportStopped
from tests.test_export_requests import HttpFailure


@pytest.mark.parametrize("yearly", [False, True])
def test_dotenv_is_loaded_before_tokenstore_defaults(
    tmp_path: Path, monkeypatch: MonkeyPatch, yearly: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GARMIN_TOKENSTORE", raising=False)
    (tmp_path / ".env").write_text("GARMIN_TOKENSTORE=/tmp/from-dotenv\n")
    parser = year_range.parse_args if yearly else cli.parse_args
    assert parser([]).tokenstore == "/tmp/from-dotenv"
    monkeypatch.setenv("GARMIN_TOKENSTORE", "/tmp/from-shell")
    assert parser([]).tokenstore == "/tmp/from-shell"
    assert parser(["--tokenstore", "/tmp/from-cli"]).tokenstore == "/tmp/from-cli"


def test_default_session_directory_is_explicit(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GARMIN_TOKENSTORE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    expected = str(tmp_path / ".garminconnect")
    assert cli.parse_args([]).tokenstore == expected
    assert year_range.parse_args([]).tokenstore == expected


@pytest.mark.parametrize("initial_cache", [None, "corrupt", "stale"])
def test_login_persists_session_and_next_run_needs_no_credentials(
    tmp_path: Path, monkeypatch: MonkeyPatch, initial_cache: str | None
) -> None:
    tokenstore = tmp_path / "tokens"
    tokenfile = tokenstore / "garmin_tokens.json"
    if initial_cache is not None:
        tokenstore.mkdir()
        tokenfile.write_text(
            "invalid JSON"
            if initial_cache == "corrupt"
            else json.dumps({"di_token": "stale"})
        )
    prompts: list[str] = []
    logins: list[tuple[str, str]] = []
    monkeypatch.setenv("GARMIN_EMAIL", "offline@example.invalid")

    def password(prompt: str) -> str:
        prompts.append(prompt)
        return "typed-password"

    def login(self: Any, email: str, secret: str, **_kwargs: Any) -> tuple[None, None]:
        logins.append((email, secret))
        self.di_token = "offline-session"
        self.di_refresh_token = "offline-refresh"
        return None, None

    def profile(self: Any) -> None:
        if self.client.di_token == "stale":
            raise garminconnect.GarminConnectAuthenticationError("401 stale token")

    monkeypatch.setattr(getpass, "getpass", password)
    monkeypatch.setattr(garminconnect.client.Client, "login", login)
    monkeypatch.setattr(garminconnect.Garmin, "_load_profile_and_settings", profile)
    first = cli.authenticate_client(str(tokenstore))
    assert first is not None
    assert json.loads(tokenfile.read_text())["di_token"] == "offline-session"

    def unexpected_prompt(prompt: str) -> str:
        pytest.fail("a saved session must not prompt for credentials")

    monkeypatch.setattr(getpass, "getpass", unexpected_prompt)
    monkeypatch.setattr("builtins.input", unexpected_prompt)
    second = cli.authenticate_client(str(tokenstore))
    assert second is not first
    assert len(prompts) == 1
    assert logins == [("offline@example.invalid", "typed-password")]


@pytest.mark.parametrize("status", [403, 429, 503])
def test_failed_session_request_does_not_trigger_credential_login(
    monkeypatch: MonkeyPatch, status: int
) -> None:
    calls = 0

    def denied(self: Any, tokenstore: str | None) -> None:
        nonlocal calls
        calls += 1
        raise HttpFailure(status)

    def unexpected_prompt(prompt: str) -> str:
        pytest.fail("server failures must not trigger another login")

    monkeypatch.setattr(garminconnect.Garmin, "login", denied)
    monkeypatch.setattr(getpass, "getpass", unexpected_prompt)
    monkeypatch.setattr("builtins.input", unexpected_prompt)
    expected = ExportStopped if status in {403, 429} else HttpFailure
    with pytest.raises(expected):
        cli.authenticate_client("unused")
    assert calls == 1


def test_build_client_prompts_for_email_and_mfa(monkeypatch: MonkeyPatch) -> None:
    prompts: list[str] = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return "offline@example.invalid" if "email" in prompt else "123456"

    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "typed-password")
    client: Any = cli.build_client()
    assert client.prompt_mfa() == "123456"
    assert prompts == ["Garmin email: ", "Garmin MFA code: "]
