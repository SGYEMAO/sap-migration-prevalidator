from __future__ import annotations

import re
from typing import Any

import pandas as pd


EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
EMAIL_COLUMN_HINTS = ("email", "contact", "owner", "responsible")


def extract_emails_from_template(template_data: dict[str, pd.DataFrame]) -> list[str]:
    """Extract unique email addresses from prioritized template columns, then all cells."""
    found: list[str] = []
    seen: set[str] = set()

    for df in template_data.values():
        for column in df.columns:
            column_name = str(column).strip().lower()
            if any(hint in column_name for hint in EMAIL_COLUMN_HINTS):
                _add_emails_from_series(df[column], found, seen)

    for df in template_data.values():
        for column in df.columns:
            column_name = str(column).strip().lower()
            if any(hint in column_name for hint in EMAIL_COLUMN_HINTS):
                continue
            _add_emails_from_series(df[column], found, seen)

    return found


def _add_emails_from_series(series: pd.Series, found: list[str], seen: set[str]) -> None:
    for value in series:
        for email in _extract_emails_from_value(value):
            normalized = email.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            found.append(email)


def _extract_emails_from_value(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return re.findall(EMAIL_REGEX, value)
