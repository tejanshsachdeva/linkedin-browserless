"""Compute human-readable durations from profile date strings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_MONTH_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class DatePoint:
    year: int
    month: int = 1


def parse_date_point(value: str | None) -> DatePoint | None:
    if not value:
        return None
    text = value.strip()
    match = _MONTH_RE.match(text)
    if match:
        month = _MONTHS.index(match.group(1)) + 1
        return DatePoint(year=int(match.group(2)), month=month)
    if text.isdigit():
        return DatePoint(year=int(text))
    return None


def _has_month_precision(value: str | None) -> bool:
    return bool(value and _MONTH_RE.match(value.strip()))


def compute_duration(start_date: str | None, end_date: str | None) -> str | None:
    start = parse_date_point(start_date)
    if start is None:
        return None
    end = parse_date_point(end_date) or DatePoint(year=date.today().year, month=date.today().month)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end_date is not None and _has_month_precision(start_date) and _has_month_precision(end_date):
        months += 1
    if months < 0:
        return None
    years, remainder = divmod(months, 12)
    parts: list[str] = []
    if years:
        parts.append(f"{years} yr{'s' if years != 1 else ''}")
    if remainder:
        parts.append(f"{remainder} mo{'s' if remainder != 1 else ''}")
    if not parts:
        return "Less than 1 mo"
    return " ".join(parts)
