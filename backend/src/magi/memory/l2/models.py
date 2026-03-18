"""Contracts for the asynchronous L2 cognition pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


def _non_empty_text(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


@dataclass(slots=True)
class L2EventExtractionJob:
    """Queue payload for event-to-candidate extraction."""

    event_ids: list[str]
    batch_key: str
    job_type: str = "extract"

    @classmethod
    def from_event_id(cls, event_id: str) -> "L2EventExtractionJob":
        normalized = _non_empty_text(event_id, field_name="event_id")
        return cls(event_ids=[normalized], batch_key=f"event:{normalized}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityReconcileJob:
    """Queue payload for entity-level reconcile."""

    entity_ids: list[str]
    job_type: str = "reconcile"
    batch_key: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = sorted({_non_empty_text(entity_id, field_name="entity_id") for entity_id in self.entity_ids})
        if not normalized:
            raise ValueError("entity_ids must not be empty")
        self.entity_ids = normalized
        self.batch_key = "entities:" + "|".join(normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2SnapshotRefreshJob:
    """Queue payload for snapshot refresh work."""

    entity_ids: list[str]
    reason: str = "reconcile"
    job_type: str = "snapshot_refresh"
    batch_key: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = sorted({_non_empty_text(entity_id, field_name="entity_id") for entity_id in self.entity_ids})
        if not normalized:
            raise ValueError("entity_ids must not be empty")
        self.entity_ids = normalized
        self.batch_key = "snapshots:" + "|".join(normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ManualL2EventRequest:
    """User-supplied manual event used by the L2 lab."""

    text: str
    user_id: str
    session_id: Optional[str] = None
    source: str = "l2_lab"
    cognition_eligible: bool = True
    entity_focus_hint: Optional[str] = None

    def __post_init__(self) -> None:
        self.text = _non_empty_text(self.text, field_name="text")
        self.user_id = _non_empty_text(self.user_id, field_name="user_id")
        if self.session_id is not None:
            self.session_id = self.session_id.strip() or None
        if self.entity_focus_hint is not None:
            self.entity_focus_hint = self.entity_focus_hint.strip() or None
        self.source = self.source.strip() or "l2_lab"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    canonical_name_hint: Optional[str] = None
    resolved_entity_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StructuredGraphHint:
    """Structured graph hint supplied by a source integration."""

    subject_ref: str
    predicate: str
    object_ref: str
    object_type: str
    subject_type: Optional[str] = None
    evidence_text: Optional[str] = None

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ContradictionHint",
    "L2EntityReconcileJob",
    "L2EventExtractionJob",
    "L2SnapshotRefreshJob",
    "ManualL2EventRequest",
    "ReconciledTraitOutcome",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
