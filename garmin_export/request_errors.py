"""Interpret Garmin errors without losing response metadata in wrapped exceptions."""

import math
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


class ExportStopped(RuntimeError):
    """The current run must stop making requests to Garmin."""


def error_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def status_code(exc: BaseException) -> int | None:
    chain = tuple(error_chain(exc))
    for error in chain:
        status = getattr(getattr(error, "response", None), "status_code", None)
        if isinstance(status, int):
            return status
    for error in chain:
        name = type(error).__name__
        if name == "GarminConnectTooManyRequestsError":
            return 429
        if name == "GarminConnectAuthenticationError":
            return 401
        match = re.search(r"\b(401|403|429|5\d\d)\b", str(error))
        if match:
            return int(match.group(1))
        if "too many requests" in str(error).lower():
            return 429
    return None


def retry_after_seconds(exc: BaseException) -> float | None:
    for error in error_chain(exc):
        headers = getattr(getattr(error, "response", None), "headers", {})
        value = headers.get("Retry-After", headers.get("retry-after"))
        if value is not None:
            delay = parse_retry_after(str(value))
            if delay is not None:
                return delay
    return None


def parse_retry_after(value: str) -> float | None:
    try:
        delay = float(value)
    except ValueError:
        try:
            timestamp = parsedate_to_datetime(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            delay = (timestamp - datetime.now(UTC)).total_seconds()
        except ValueError, TypeError, OverflowError:
            return None
    return max(0.0, delay) if math.isfinite(delay) else None
