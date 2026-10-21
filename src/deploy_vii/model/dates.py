"""Date helpers extracted from the pinned reader; no table/parser dependencies."""

import re
from datetime import date

_FOUR_DIGITS = re.compile(r"(?<!\d)\d{4}(?!\d)")
_TWO_YEARS = re.compile(r"(?<!\d)(\d{4})\s*[/-]\s*(\d{4}|\d{2})(?!\d)")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _end_year(start: str, end: str) -> int | None:
    first = int(start)
    if len(end) == 4:
        return int(end) if int(end) == first + 1 else None
    return first + 1 if int(end) == (first + 1) % 100 else None


def fiscal_year_number(value: str) -> int | None:
    """A fiscal year's four-digit year: a two-year spelling's END year
    (`FY2025/26` is 2026), else the last run of exactly four digits."""
    for start, end in reversed(_TWO_YEARS.findall(value)):
        year = _end_year(start, end)
        if year is not None:
            return year
    runs = _FOUR_DIGITS.findall(value)
    return int(runs[-1]) if runs else None


def iso_date(value: str | None) -> date | None:
    """`value` as a calendar date where it is exactly `YYYY-MM-DD`; else None."""
    if value is None or _ISO_DATE.fullmatch(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:  # `2025-02-30`: no such day
        return None
