"""Exercise the real pinned SDK's login loops using offline HTTP responses."""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import garminconnect  # type: ignore[import-untyped]
import pytest
from curl_cffi import requests as cffi_requests
from pytest import MonkeyPatch
from requests import Response, Session

from garmin_export import cli
from garmin_export.authentication import stop_on_auth_block
from garmin_export.request_errors import ExportStopped

PROFILE = {"displayName": "offline", "fullName": "Offline Test"}
LOGIN = {"responseStatus": {"type": "SUCCESSFUL"}, "serviceTicketId": "ST-offline"}
TOKEN = {"access_token": "offline-token", "refresh_token": "offline-refresh"}
SETTINGS = {"userData": {"measurementSystem": "metric"}}


class OfflineHTTP:
    def __init__(
        self, monkeypatch: MonkeyPatch, responses: list[tuple[int, Any]]
    ) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

        def send(_session: Any, request: Any, **_kwargs: Any) -> Response:
            return self.reply(request.method, request.url)

        def request(_session: Any, method: str, url: str, **_kwargs: Any) -> Response:
            return self.reply(method, url)

        monkeypatch.setattr(Session, "send", send)
        monkeypatch.setattr(cffi_requests.Session, "request", request)

    def reply(self, method: str, url: str) -> Response:
        self.calls.append((method, url))
        if not self.responses:
            pytest.fail(f"Unexpected extra HTTP request: {method} {url}")
        status, payload = self.responses.pop(0)
        response = Response()
        response.status_code = status
        response.url = url
        response._content = (
            payload if isinstance(payload, str) else json.dumps(payload)
        ).encode()
        return response


def offline_client(monkeypatch: MonkeyPatch) -> Any:
    monkeypatch.setenv("GARMIN_EMAIL", "offline@example.invalid")
    monkeypatch.setattr("getpass.getpass", lambda prompt: "offline-password")
    monkeypatch.setattr("builtins.input", lambda prompt: "123456")
    return cli.build_client()


@pytest.mark.parametrize("cffi", [False, True])
@pytest.mark.parametrize(
    "status,payload",
    [
        (403, {}),
        (429, {}),
        (200, {"error": {"status-code": "429"}}),
        (200, {"error": {"status-code": 403}}),
    ],
)
def test_first_login_block_stops_all_fingerprints_and_strategies(
    monkeypatch: MonkeyPatch, cffi: bool, status: int, payload: Any
) -> None:
    monkeypatch.setattr(garminconnect.client, "HAS_CFFI", cffi)
    http = OfflineHTTP(monkeypatch, [(status, payload)])
    client = offline_client(monkeypatch)
    with pytest.raises(ExportStopped, match="Stopped login after HTTP"):
        cli.login_with_stop(client, None)
    assert len(http.calls) == 1
    assert http.calls[0][1].split("?", 1)[0].endswith("/mobile/api/login")


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.parametrize(
    "phase", ["mfa", "exchange", "verification", "profile", "settings", "refresh"]
)
def test_blocks_inside_nested_sdk_authentication_stop_before_next_request(
    monkeypatch: MonkeyPatch, status: int, phase: str
) -> None:
    scripts: dict[str, list[tuple[int, Any]]] = {
        "mfa": [(200, {"responseStatus": {"type": "MFA_REQUIRED"}})],
        "exchange": [(200, LOGIN)],
        "verification": [(200, LOGIN), (200, TOKEN)],
        "profile": [],
        "settings": [(200, PROFILE)],
        "refresh": [],
    }
    script = scripts[phase] + [(status, {})]
    http = OfflineHTTP(monkeypatch, script)
    tokenstore = None
    if phase in {"profile", "settings", "refresh"}:
        token = "offline-token"
        if phase == "refresh":
            payload = base64.urlsafe_b64encode(b'{"exp":1}').decode().rstrip("=")
            token = f"e30.{payload}.signature"
        tokenstore = json.dumps(
            {
                "di_token": token,
                "di_refresh_token": "offline-refresh",
                "di_client_id": "offline-client",
            }
        )

        def unexpected_prompt(prompt: str) -> str:
            pytest.fail("blocked cached authentication must not prompt again")

        monkeypatch.setattr("getpass.getpass", unexpected_prompt)
        monkeypatch.setattr("builtins.input", unexpected_prompt)
        with pytest.raises(ExportStopped, match=f"HTTP {status}"):
            cli.authenticate_client(tokenstore)
    else:
        client = offline_client(monkeypatch)
        with pytest.raises(ExportStopped, match=f"HTTP {status}"):
            cli.login_with_stop(client, tokenstore)
    assert len(http.calls) == len(script)
    assert not http.responses


@pytest.mark.parametrize(
    "first_response",
    [(503, "<html>unavailable</html>"), (200, {"error": None}), (200, [])],
)
def test_non_blocking_failure_can_still_fall_back_and_authenticate(
    monkeypatch: MonkeyPatch, first_response: tuple[int, Any]
) -> None:
    http = OfflineHTTP(
        monkeypatch,
        [
            first_response,
            (200, LOGIN),
            (200, TOKEN),
            (200, PROFILE),
            (200, PROFILE),
            (200, SETTINGS),
        ],
    )
    client = offline_client(monkeypatch)
    original_send = Session.send
    original_request = cffi_requests.Session.request
    cli.login_with_stop(client, None)
    assert client.display_name == "offline"
    assert client.password is None
    assert len(http.calls) == 6
    assert not http.responses
    assert Session.send is original_send
    assert cffi_requests.Session.request is original_request


@pytest.mark.parametrize("strategy", ["widget+cffi", "portal+cffi", "portal+requests"])
@pytest.mark.parametrize("status", [403, 429])
def test_web_strategies_stop_at_blocked_signin_page(
    monkeypatch: MonkeyPatch, strategy: str, status: int
) -> None:
    # Widget's second GET and portal's first GET do not consistently raise on
    # 403 in the SDK. The response guard must stop them before posting secrets.
    script: list[tuple[int, Any]] = (
        [(200, "embed")] if strategy == "widget+cffi" else []
    )
    script.append((status, "<html>blocked</html>"))
    http = OfflineHTTP(monkeypatch, script)
    client = offline_client(monkeypatch)
    client.client.skip_strategies = {
        "mobile+cffi",
        "mobile+requests",
        "widget+cffi",
        "portal+cffi",
        "portal+requests",
    } - {strategy}
    with pytest.raises(ExportStopped, match=f"HTTP {status}"):
        cli.login_with_stop(client, None)
    assert len(http.calls) == len(script)
    assert all(method == "GET" for method, _url in http.calls)


def test_invalid_credentials_keep_original_authentication_error(
    monkeypatch: MonkeyPatch,
) -> None:
    http = OfflineHTTP(
        monkeypatch, [(401, {"responseStatus": {"type": "INVALID_USERNAME_PASSWORD"}})]
    )
    client = offline_client(monkeypatch)
    with pytest.raises(garminconnect.GarminConnectAuthenticationError):
        cli.login_with_stop(client, None)
    assert len(http.calls) == 1


@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt])
def test_transport_methods_are_restored_even_when_login_is_interrupted(
    exception: type[BaseException],
) -> None:
    original_send = Session.send
    original_request = cffi_requests.Session.request
    with pytest.raises(exception), stop_on_auth_block():
        raise exception()
    assert Session.send is original_send
    assert cffi_requests.Session.request is original_request


def test_nested_guards_restore_transports_and_leave_other_threads_alone(
    monkeypatch: MonkeyPatch,
) -> None:
    OfflineHTTP(monkeypatch, [(429, {}), (429, {}), (429, {})])
    original_send = Session.send
    original_request = cffi_requests.Session.request
    with stop_on_auth_block():
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(Session().get, "https://offline.invalid").result()
        assert response.status_code == 429
        with pytest.raises(ExportStopped), stop_on_auth_block():
            Session().get("https://offline.invalid")
        with pytest.raises(ExportStopped), stop_on_auth_block():
            cffi_requests.get("https://offline.invalid")
    assert Session.send is original_send
    assert cffi_requests.Session.request is original_request
