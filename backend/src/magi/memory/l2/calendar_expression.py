"""Typed calendar meaning emitted by extraction, without source-time authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

_UNITS = frozenset({"day", "week", "month", "year"})
_INTEGER_FIELDS = frozenset({
    "year", "month", "day", "offset", "week_offset", "weekday",
    "year_offset", "start_month", "month_count",
})


@dataclass(frozen=True, slots=True)
class ClaimCalendarExpression:
    """One closed calendar operation; the host supplies anchors and date math."""

    kind: str
    unit: str | None = None
    year: int | None = None
    month: int | None = None
    day: int | None = None
    offset: int | None = None
    week_offset: int | None = None
    weekday: int | None = None
    year_offset: int | None = None
    start_month: int | None = None
    month_count: int | None = None

    def __post_init__(self) -> None:
        fields = self.to_dict()
        for name in _INTEGER_FIELDS.intersection(fields):
            if type(fields[name]) is not int or abs(fields[name]) > 10000:
                raise ValueError("Calendar expression requires bounded integer operands")
        expected: set[str]
        if self.kind == "at_observation":
            expected = {"kind"}
        elif self.kind == "absolute":
            if self.unit not in {"day", "month", "year"}:
                raise ValueError("Absolute calendar expression has an invalid unit")
            expected = {"kind", "unit", "year"}
            if self.unit in {"day", "month"}:
                expected.add("month")
            if self.unit == "day":
                expected.add("day")
        elif self.kind == "relative_period":
            if self.unit not in _UNITS:
                raise ValueError("Relative calendar expression has an invalid unit")
            expected = {"kind", "unit", "offset"}
        elif self.kind == "weekday":
            expected = {"kind", "week_offset", "weekday"}
        elif self.kind == "month_window":
            if (self.year is None) == (self.year_offset is None):
                raise ValueError("Month window requires exactly one year reference")
            expected = {"kind", "start_month", "month_count", "year" if self.year is not None else "year_offset"}
        else:
            raise ValueError("Unsupported calendar expression kind")
        if set(fields) != expected:
            raise ValueError("Calendar expression operands do not match its operation")
        for name, lower, upper in (
            ("year", 1, 9998), ("month", 1, 12), ("day", 1, 31),
            ("weekday", 0, 6), ("start_month", 1, 12), ("month_count", 1, 12),
        ):
            value = fields.get(name)
            if value is not None and not lower <= value <= upper:
                raise ValueError("Calendar expression operand is out of range")

    @property
    def requires_anchor(self) -> bool:
        return self.kind in {"relative_period", "weekday", "at_observation"} or self.year_offset is not None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    @classmethod
    def from_dict(cls, value: object) -> ClaimCalendarExpression | None:
        """Invalid or absent judgments stay unresolved; never infer an operation."""
        if not isinstance(value, dict):
            return None
        try:
            return cls(**value)
        except (TypeError, ValueError):
            return None
