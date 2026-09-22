"""Source grounding and deterministic normalization of typed Claim literals."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import date
from typing import Any

from .ontology_aliases import canonicalize_predicate

_DIGITS = {character: value for value, character in enumerate("零一二三四五六七八九")}
_DIGITS.update({"〇": 0, "两": 2})
_UNITS = {"十": 10, "百": 100, "千": 1000}
_NUMBER_CHARACTERS = "0-9０-９零〇一二两三四五六七八九十百千"
_NUMBER_TOKEN = rf"[{_NUMBER_CHARACTERS}]+"
_NUMBER_SOURCE = re.compile(
    rf"(?<![{_NUMBER_CHARACTERS}])[+\-＋－]?{_NUMBER_TOKEN}"
    rf"(?:[.．点]{_NUMBER_TOKEN})?(?![{_NUMBER_CHARACTERS}])"
)
_DATE_VALUE = re.compile(
    rf"(?:(?P<year>{_NUMBER_TOKEN})(?:年|[-/]))?"
    rf"(?P<month>{_NUMBER_TOKEN})(?:月|[-/])(?P<day>{_NUMBER_TOKEN})日?"
)
_DATE_SOURCE = re.compile(
    rf"(?<![{_NUMBER_CHARACTERS}]){_DATE_VALUE.pattern}(?![{_NUMBER_CHARACTERS}])"
)
_INTEGER_PREDICATES = frozenset({"BIRTH_YEAR", "STATED_AGE", "AGE"})


def canonical_literal_value(predicate: str, value: Any) -> str | int | None:
    """Normalize scalar spelling without interpreting surrounding prose.

    The emitted value and its source surface stay immutable on the Claim. This
    value is only the host's typed identity for routing and scalar equivalence.
    """
    canonical = canonicalize_predicate(predicate) or predicate.upper()
    text = " ".join(unicodedata.normalize("NFKC", str(value if value is not None else "")).split())
    if not text:
        return None
    if canonical == "BIRTH_DATE":
        match = _DATE_VALUE.fullmatch(text)
        parts = _date_parts(match) if match is not None else None
        if parts is None:
            return None
        year, month, day = parts
        return f"{year:04d}-{month:02d}-{day:02d}" if year is not None else f"{month:02d}-{day:02d}"
    if canonical in _INTEGER_PREDICATES:
        integer = _integer_value(text)
        lower, upper = (1900, 2200) if canonical == "BIRTH_YEAR" else (0, 130)
        return integer if integer is not None and lower <= integer <= upper else None
    return text[:200]


def grounded_literal_surface(
    predicate: str,
    value: str,
    sources: Sequence[str],
) -> str | None:
    """Return an exact authorized span matching the complete typed literal.

    Sources must already be current evidence or validated contextual antecedents.
    Numeric spelling may differ, but a missing year or an unrelated scalar never
    supplies a claimed value. This checks provenance, not semantic entailment.
    """
    canonical = canonicalize_predicate(predicate) or predicate.upper()
    if canonical not in _INTEGER_PREDICATES and canonical != "BIRTH_DATE":
        return next((value for source in sources if value and value in source), None)
    expected = canonical_literal_value(canonical, value)
    if expected is None:
        return None
    pattern = _DATE_SOURCE if canonical == "BIRTH_DATE" else _NUMBER_SOURCE
    for source in sources:
        for match in pattern.finditer(source):
            surface = match.group(0)
            actual = canonical_literal_value(canonical, surface)
            if actual == expected:
                return surface
    return None


def _integer_value(text: str) -> int | None:
    text = unicodedata.normalize("NFKC", text)
    if text.isascii() and text.isdigit():
        return int(text)
    if not text or any(character not in _DIGITS and character not in _UNITS for character in text):
        return None
    if not any(character in _UNITS for character in text):
        return int("".join(str(_DIGITS[character]) for character in text))
    total = 0
    digit: int | None = None
    previous_unit = 10000
    zero = False
    for character in text:
        if character in _DIGITS:
            value = _DIGITS[character]
            if digit is not None or (value == 0 and (zero or previous_unit == 10000)):
                return None
            if value == 0:
                zero = True
            else:
                digit = value
            continue
        unit = _UNITS[character]
        if unit >= previous_unit:
            return None
        if digit is None:
            if unit != 10 or total or zero:
                return None
            digit = 1
        total += digit * unit
        digit = None
        previous_unit = unit
        zero = False
    if digit is None:
        return None if zero else total
    # A form such as "一百二" is ambiguous shorthand; do not infer its scale.
    if previous_unit > 10 and not zero:
        return None
    return total + digit


def _date_parts(match: re.Match[str]) -> tuple[int | None, int, int] | None:
    year = _integer_value(match.group("year")) if match.group("year") else None
    month, day = _integer_value(match.group("month")), _integer_value(match.group("day"))
    if month is None or day is None or (match.group("year") and year is None):
        return None
    try:
        date(year if year is not None else 2000, month, day)
    except ValueError:
        return None
    return year, month, day
