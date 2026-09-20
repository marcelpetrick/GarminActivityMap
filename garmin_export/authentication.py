"""Fail closed on authentication blocks in the pinned Garmin SDK.

The SDK catches ordinary exceptions inside its strategy, fingerprint, MFA and
token-refresh loops. A private cancellation signal must cross those handlers;
only the public context boundary translates it to ExportStopped. Transport
wrappers exist only during login and only inspect this context's responses, so
requests in other threads remain unaffected. Login guards are serialized to
ensure class methods are restored in order. No SDK authentication code is copied.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import RLock
from typing import Any

from .request_errors import ExportStopped

_AUTHENTICATING: ContextVar[bool] = ContextVar("garmin_authenticating", default=False)
_TRANSPORT_LOCK = RLock()


class _AuthenticationBlocked(BaseException):
    def __init__(self, status: int) -> None:
        self.status = status


def check_auth_response(response: Any) -> None:
    status = response.status_code
    if status in {403, 429}:
        raise _AuthenticationBlocked(status)
    # Garmin can report rate limits in an otherwise successful JSON response.
    try:
        payload = response.json()
    except ValueError:
        return
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and str(error.get("status-code")) in {"403", "429"}:
        raise _AuthenticationBlocked(int(error["status-code"]))


@contextmanager
def guarded_transport(transport: Any, method: str) -> Iterator[None]:
    original: Callable[..., Any] = getattr(transport, method)

    @wraps(original)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        response = original(*args, **kwargs)
        if _AUTHENTICATING.get():
            check_auth_response(response)
        return response

    setattr(transport, method, guarded)
    try:
        yield
    finally:
        setattr(transport, method, original)


@contextmanager
def stop_on_auth_block() -> Iterator[None]:
    # Lazy imports retain the CLI's helpful missing-dependency error.
    from curl_cffi import requests as cffi_requests
    from requests import Session

    with _TRANSPORT_LOCK, ExitStack() as stack:
        # requests.send also sees redirect responses; cffi uses one request call.
        stack.enter_context(guarded_transport(Session, "send"))
        stack.enter_context(guarded_transport(cffi_requests.Session, "request"))
        token = _AUTHENTICATING.set(True)
        try:
            yield
        except _AuthenticationBlocked as exc:
            raise ExportStopped(
                f"Stopped login after HTTP {exc.status}; try again later."
            ) from None
        finally:
            _AUTHENTICATING.reset(token)
