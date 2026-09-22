"""Source-span validation for literal Claim values."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from .ontology_aliases import canonicalize_predicate

_BIRTH_DATE_VALUE = re.compile(r"(?:(?P<year>[0-9]{4})-)?(?P<month>[0-9]{2})-(?P<day>[0-9]{2})")
_BIRTH_DATE_SOURCE = re.compile(
    r"(?<![0-9])(?:(?P<year>[0-9]{4})(?:年|[-/]))?"
    r"(?P<month>[0-9]{1,2})(?:月|[-/])(?P<day>[0-9]{1,2})日?(?![0-9])"
)


def grounded_literal_surface(
    predicate: str,
    value: str,
    sources: Sequence[str],
) -> str | None:
    """Find the complete value in authorized quotes, allowing typed date spelling.

    Sources must already be current evidence or validated contextual antecedents.
    This validates literal provenance, not the proposition's semantic entailment.
    """
    canonical = canonicalize_predicate(predicate) or predicate.upper()
    if not value:
        return None
    if canonical == "BIRTH_DATE":
        expected = _BIRTH_DATE_VALUE.fullmatch(value)
        parts = _date_parts(expected) if expected is not None else None
        if parts is None:
            return None
        year, month, day = parts
        for source in sources:
            for match in _BIRTH_DATE_SOURCE.finditer(source):
                actual = _date_parts(match)
                if actual is not None and actual[1:] == (month, day) and (
                    year is None or actual[0] == year
                ):
                    return match.group(0)
        return None
    if canonical in {"BIRTH_YEAR", "STATED_AGE", "AGE"}:
        if not value.isascii() or not value.isdigit():
            return None
        pattern = re.compile(r"(?<![0-9])" + re.escape(value) + r"(?![0-9])")
        return next((number_match.group(0) for text in sources if (number_match := pattern.search(text))), None)
    return next((value for source in sources if value in source), None)


def _date_parts(match: re.Match[str]) -> tuple[int | None, int, int] | None:
    year = int(match.group("year")) if match.group("year") else None
    month, day = int(match.group("month")), int(match.group("day"))
    try:
        date(year or 2000, month, day)
    except ValueError:
        return None
    return year, month, day
