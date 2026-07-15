"""Auxiliary L2 phase and reconciliation contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .phase_model_utils import _optional_text


@dataclass(slots=True)
class ContradictionHint:
    """LLM- or rule-generated hint that a record may need revalidation."""

    target_record_id: str
    target_record_type: str
    contradiction_kind: str
    confidence: float
    evidence_text: str
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StructuredEntityHint:
    """Structured entity hint supplied by a source integration."""

    mention_text: str
    entity_type: str
    canonical_name_hint: str | None = None
    resolved_entity_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StructuredGraphHint:
    """Structured graph hint supplied by a source integration."""

    subject_ref: str
    predicate: str
    object_ref: str
    object_type: str
    subject_type: str | None = None
    fact_kind: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    origin_mode: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StructuredGraphHint":
        return cls(
            subject_ref=str(payload.get("subject_ref", "")),
            predicate=str(payload.get("predicate", "")),
            object_ref=str(payload.get("object_ref", "")),
            object_type=str(payload.get("object_type", "")),
            subject_type=_optional_text(payload.get("subject_type")),
            fact_kind=_optional_text(payload.get("fact_kind")),
            confidence=float(payload["confidence"])
            if payload.get("confidence") is not None
            else None,
            evidence_text=_optional_text(payload.get("evidence_text")),
            origin_mode=_optional_text(payload.get("origin_mode")),
            attributes=dict(payload.get("attributes", {}))
            if isinstance(payload.get("attributes"), dict)
            else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReconciledTraitOutcome:
    """Stable serialization of one reconcile decision."""

    entity_id: str
    entity_type: str
    trait_name: str
    winning_value: str
    status: str
    confidence: float
    evidence_event_ids: list[str]
    time_span_hours: float
    stability_kind: str
    recommended_snapshot_field: str
    natural_summary: str = ""
    expires_at: float | None = None
    trait_family: str = ""  # closed enum from L2 Phase 2; e.g. "state_profile", "mood"
    source_assertion_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ContradictionHint",
    "ReconciledTraitOutcome",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
