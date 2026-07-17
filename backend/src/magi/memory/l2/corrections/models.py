"""Typed correction records shared by storage and API services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class CorrectionTargetKind(str, Enum):
    ASSERTION = "assertion"
    EDGE = "edge"


class CorrectionKind(str, Enum):
    RECORD_ERROR = "record_error"
    SITUATION_CHANGED = "situation_changed"
    SCOPE_REFINEMENT = "scope_refinement"


class CorrectionState(str, Enum):
    ACTIVE = "active"
    REVERTED = "reverted"


class CorrectionRuleKind(str, Enum):
    BLOCK_CLAIM = "block_claim"
    AUTHORITATIVE_SLOT = "authoritative_slot"
    CLOSE_BEFORE = "close_before"
    SCOPE_ONLY = "scope_only"


@dataclass(frozen=True)
class NewMemoryCorrection:
    correction_id: str
    request_id: str
    actor_id: str
    target_kind: CorrectionTargetKind
    target_id: str
    slot_key: str
    claim_fingerprint: str
    correction_kind: CorrectionKind
    before: Mapping[str, Any]
    created_at: float
    reason: str | None = None
    replacement: Mapping[str, Any] | None = None
    effective_at: float | None = None
    scope: Mapping[str, Any] | None = None
    source_event_id: str | None = None
    audit_event_id: str | None = None
    replacement_target_id: str | None = None


@dataclass(frozen=True)
class CorrectionRule:
    rule_id: str
    correction_id: str
    target_kind: CorrectionTargetKind
    rule_kind: CorrectionRuleKind
    slot_key: str
    created_at: float
    claim_fingerprint: str | None = None
    scope_key: str = "global"
    effective_from: float | None = None
    effective_to: float | None = None
    active: bool = True


@dataclass(frozen=True)
class MemoryCorrection:
    correction_id: str
    request_id: str
    actor_id: str
    target_kind: CorrectionTargetKind
    target_id: str
    slot_key: str
    claim_fingerprint: str
    correction_kind: CorrectionKind
    before: dict[str, Any]
    created_at: float
    state: CorrectionState
    reason: str | None = None
    replacement: dict[str, Any] | None = None
    effective_at: float | None = None
    scope: dict[str, Any] | None = None
    source_event_id: str | None = None
    audit_event_id: str | None = None
    replacement_target_id: str | None = None
    reverted_at: float | None = None
    reverted_by: str | None = None
    transition_applied_at: float | None = None
    transition_cancelled_at: float | None = None
    transition_cancel_reason: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "MemoryCorrection":
        return cls(
            correction_id=str(row["correction_id"]),
            request_id=str(row["request_id"]),
            actor_id=str(row["actor_id"]),
            target_kind=CorrectionTargetKind(str(row["target_kind"])),
            target_id=str(row["target_id"]),
            slot_key=str(row["slot_key"]),
            claim_fingerprint=str(row["claim_fingerprint"]),
            correction_kind=CorrectionKind(str(row["correction_kind"])),
            before=_json_object(row["before_json"]) or {},
            replacement=_json_object(row.get("replacement_json")),
            effective_at=_optional_float(row.get("effective_at")),
            scope=_json_object(row.get("scope_json")),
            source_event_id=_optional_text(row.get("source_event_id")),
            audit_event_id=_optional_text(row.get("audit_event_id")),
            replacement_target_id=_optional_text(row.get("replacement_target_id")),
            state=CorrectionState(str(row["state"])),
            created_at=float(row["created_at"]),
            reverted_at=_optional_float(row.get("reverted_at")),
            reverted_by=_optional_text(row.get("reverted_by")),
            reason=_optional_text(row.get("reason")),
            transition_applied_at=_optional_float(row.get("transition_applied_at")),
            transition_cancelled_at=_optional_float(row.get("transition_cancelled_at")),
            transition_cancel_reason=_optional_text(row.get("transition_cancel_reason")),
        )


@dataclass(frozen=True)
class CorrectionCreateResult:
    correction: MemoryCorrection
    created: bool
    subject_revisions: dict[str, int]


@dataclass(frozen=True)
class ApplyAssertionCorrectionCommand:
    """One user-authoritative change to an assertion claim."""

    assertion_id: str
    request_id: str
    actor_id: str
    correction_kind: CorrectionKind
    replacement_value: str | None = None
    reason: str | None = None
    effective_at: float | None = None
    scope: Mapping[str, Any] | None = None
    source_event_id: str | None = None
    source_event_observed_at: float | None = None
    audit_event_id: str | None = None
    expected_updated_at: float | None = None


@dataclass(frozen=True)
class AssertionCorrectionResult:
    correction: MemoryCorrection
    created: bool
    current_assertion_id: str | None
    subject_revision: int | None


@dataclass(frozen=True)
class ApplyRelationshipCorrectionCommand:
    """One user-authoritative change to a relationship claim."""

    triple_id: str
    request_id: str
    actor_id: str
    correction_kind: CorrectionKind
    replacement: Mapping[str, Any] | None = None
    reason: str | None = None
    effective_at: float | None = None
    scope: Mapping[str, Any] | None = None
    source_event_id: str | None = None
    source_event_observed_at: float | None = None
    audit_event_id: str | None = None
    expected_updated_at: float | None = None


@dataclass(frozen=True)
class RelationshipCorrectionResult:
    correction: MemoryCorrection
    created: bool
    current_triple_id: str | None
    subject_revision: int | None


def _json_object(value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("Correction JSON payload must be an object")
    return parsed


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


__all__ = [
    "ApplyAssertionCorrectionCommand",
    "ApplyRelationshipCorrectionCommand",
    "AssertionCorrectionResult",
    "CorrectionCreateResult",
    "CorrectionKind",
    "CorrectionRule",
    "CorrectionRuleKind",
    "CorrectionState",
    "CorrectionTargetKind",
    "MemoryCorrection",
    "NewMemoryCorrection",
    "RelationshipCorrectionResult",
]
