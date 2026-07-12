"""Shared L2 extraction flow contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...event_contracts import MemoryEvent
from ...evidence import EvidenceClassification, PolicyDecision
from ..models import L2EventWindow, ResolvedEntityMention


@dataclass(slots=True)
class L2ExtractionEventDecision:
    """One event's evidence classification and L2 write policy."""

    event: MemoryEvent
    classification: EvidenceClassification
    policy: PolicyDecision

    @property
    def is_write_eligible(self) -> bool:
        return self.policy.allow_graph_write or self.policy.allow_assertion_write


@dataclass(slots=True)
class L2ExtractionPlan:
    """Prepared event workset for a single L2 extraction batch."""

    decisions: list[L2ExtractionEventDecision]
    eligible_decisions: list[L2ExtractionEventDecision]
    primary: L2ExtractionEventDecision | None
    batch_event_ids: list[str]
    skip_result: dict[str, Any] | None


@dataclass(slots=True)
class _PreparedExtractionBatch:
    stored_event: MemoryEvent
    classification: EvidenceClassification
    policy: PolicyDecision
    eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]]
    batch_event_ids: list[str]
    context_messages: list[dict[str, Any]]
    history_contexts: list[dict[str, Any]]
    extraction_profile: Any
    self_entity_id: str | None
    event_window: L2EventWindow
    focal_subject: dict[str, Any]
    existing_entities: list[dict[str, Any]]
    catalog_name_index: dict[str, Any]
    direct_write_candidates: list[dict[str, Any]]
    direct_write_count: int


@dataclass(slots=True)
class _Phase1ExtractionFlow:
    phase1_result: Any
    resolved_mentions: list[ResolvedEntityMention]
    profile_signal_object_refs: set[str]


@dataclass(slots=True)
class _Phase2Context:
    focal_entities: list[dict[str, Any]]
    existing_graph_edges: list[dict[str, Any]]
    existing_assertions: list[dict[str, Any]]


@dataclass(slots=True)
class _Phase2CandidateSet:
    graph_candidates: list[dict[str, Any]]
    facet_candidates: list[dict[str, Any]]
    assertion_candidates: list[dict[str, Any]]
    contradiction_hints: list[Any]
    rejected_graph_candidate_count: int
    rejected_assertion_candidate_count: int
    claim_assessment_count: int
    rejected_claim_assessment_count: int


__all__ = [
    "L2ExtractionEventDecision",
    "L2ExtractionPlan",
    "_Phase1ExtractionFlow",
    "_Phase2CandidateSet",
    "_Phase2Context",
    "_PreparedExtractionBatch",
]
