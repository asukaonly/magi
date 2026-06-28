"""Quality checks for user-facing L2 assertions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, SupportsInt


PROFILE_FAMILIES = {
    "identity_profile",
    "preference_profile",
    "routine_profile",
    "communication_profile",
}


@dataclass(frozen=True)
class AssertionQualityIssue:
    assertion_id: str
    issue_codes: tuple[str, ...]
    trait_family: str = ""
    trait_name: str = ""
    trait_value: str = ""


@dataclass(frozen=True)
class AssertionQualityReport:
    total_assertions: int
    issue_counts: dict[str, int] = field(default_factory=dict)
    issue_items: list[AssertionQualityIssue] = field(default_factory=list)


def analyze_assertion_quality(
    assertions: Iterable[Mapping[str, Any]],
) -> AssertionQualityReport:
    total = 0
    issue_counts: dict[str, int] = {}
    issue_items: list[AssertionQualityIssue] = []

    for assertion in assertions:
        total += 1
        issue_codes = _issue_codes(assertion)
        if not issue_codes:
            continue
        for code in issue_codes:
            issue_counts[code] = issue_counts.get(code, 0) + 1
        issue_items.append(
            AssertionQualityIssue(
                assertion_id=_text(assertion.get("assertion_id")),
                issue_codes=tuple(issue_codes),
                trait_family=_text(assertion.get("trait_family")),
                trait_name=_text(assertion.get("trait_name")),
                trait_value=_text(assertion.get("trait_value") or assertion.get("value")),
            )
        )

    return AssertionQualityReport(
        total_assertions=total,
        issue_counts=issue_counts,
        issue_items=issue_items,
    )


def _issue_codes(assertion: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    trait_value = _text(assertion.get("trait_value") or assertion.get("value"))
    if not trait_value:
        codes.append("blank_value")

    source_domain = _text(assertion.get("source_domain")).casefold()
    trait_family = _text(assertion.get("trait_family"))
    evidence_count = _evidence_count(assertion)
    if (
        source_domain == "external_activity"
        and trait_family in PROFILE_FAMILIES
        and evidence_count <= 1
    ):
        codes.append("single_evidence_external_profile")

    return codes


def _evidence_count(assertion: Mapping[str, Any]) -> int:
    raw_count = assertion.get("evidence_count")
    if isinstance(raw_count, (str, bytes, bytearray, SupportsInt)):
        try:
            return int(raw_count)
        except ValueError:
            pass
    evidence_events = assertion.get("evidence_events") or assertion.get("evidence_event_ids")
    if isinstance(evidence_events, list):
        return len(evidence_events)
    return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "AssertionQualityIssue",
    "AssertionQualityReport",
    "analyze_assertion_quality",
]
