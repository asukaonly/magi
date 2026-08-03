"""Typed write contracts for the normalized L2 grounded Claim ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class GroundedClaimInput:
    """Semantic body of one evidence-grounded Claim."""

    identity_key: str
    extractor_contract_version: int
    evidence_rule_version: int
    origin_attempt_key: str
    profile_id: str | None
    user_id: str | None
    subject_ref: str
    subject_type: str
    canonical_predicate: str
    fact_kind: str
    object_type: str
    polarity: str
    specificity: str
    confidence: float
    object_value: Any | None = None
    object_surface: str | None = None
    temporal_cue: str = "unspecified"
    fact_valid_from: float | None = None
    fact_valid_to: float | None = None
    target_from: float | None = None
    target_to: float | None = None
    raw_time_frame: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ClaimEvidenceInput:
    """One source-event occurrence supporting a grounded Claim."""

    event_id: str
    link_role: str
    required_for_grounding: bool
    event_time: float | None
    timestamp_confidence: str
    timestamp_quality: str
    evidence_rule_version: int
    evidence_mode: str
    source_type: str | None
    source_domain: str | None
    author_type: str | None
    timestamp_anchor_source: str | None = None
    evidence_class: str | None = None
    evidence_locator: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProjectionOutcomeInput:
    """Append-only result of one Claim projection attempt."""

    claim_id: str
    attempt_key: str
    target_kind: str
    outcome: str
    target_id: str = ""
    target_slot_key: str | None = None
    route_contract_version: int = 0
    reason_code: str | None = None
    details: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ClaimEntityRefInput:
    """Versioned entity-resolution enrichment for an immutable Claim."""

    claim_id: str
    ref_role: str
    entity_id: str
    resolution_version: int


__all__ = [
    "ClaimEvidenceInput",
    "ClaimEntityRefInput",
    "GroundedClaimInput",
    "ProjectionOutcomeInput",
]
