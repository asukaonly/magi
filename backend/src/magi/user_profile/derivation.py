"""Deterministic profile field derivations."""

from __future__ import annotations

from datetime import date


def parse_iso_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def derive_birth_year(birth_date: date | None) -> int | None:
    return birth_date.year if birth_date is not None else None


def derive_age_years(birth_date: date | None, *, today: date | None = None) -> int | None:
    if birth_date is None:
        return None
    current = today or date.today()
    years = current.year - birth_date.year
    if (current.month, current.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(years, 0)


def derive_birth_year_range_from_stated_age(
    age: int,
    *,
    stated_at: date | None = None,
) -> tuple[int, int]:
    current = stated_at or date.today()
    latest = current.year - age
    earliest = latest - 1
    return earliest, latest