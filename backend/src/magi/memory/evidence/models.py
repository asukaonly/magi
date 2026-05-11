"""Shared memory evidence classification and policy models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EvidenceClassification:
    """Classification result used by memory evidence governance."""

    evidence_class: str
    reason_code: str
    speaker_role: str | None
    grounding_type: str | None
    semantic_owner: str | None
    originality_type: str | None
    source_event_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass(slots=True)
class PolicyDecision:
    """Resolved write and retrieval policy for one classified evidence item."""

    allow_entity_extraction: bool
    allow_graph_write: bool
    allow_assertion_write: bool
    allow_snapshot_impact: bool
    graph_scope: str
    assertion_scope: str
    evidence_weight: float
    count_as_new_evidence: bool
    require_source_backlink: bool
    skip_reason: str | None = None


__all__ = ["EvidenceClassification", "PolicyDecision"]