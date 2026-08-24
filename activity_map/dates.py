from __future__ import annotations

from datetime import date, datetime

DATE_FORMAT = "%Y-%m-%d"


def parse_date_text(text: str) -> date | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return datetime.strptime(stripped, DATE_FORMAT).date()
    except ValueError:
        return None


def is_valid_date_text(text: str) -> bool:
    return not text.strip() or parse_date_text(text) is not None


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)
