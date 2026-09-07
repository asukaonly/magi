"""Claim-scoped source authority after semantic and exact-evidence validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ...event_contracts import MemoryEvent
from ...evidence import EvidenceClassification, PolicyDecision
from ..phase1_models import L2AssertionMode, L2Phase1FactClaim


def grounded_claim_evidence_class(
    claim: L2Phase1FactClaim,
    classification: EvidenceClassification,
) -> str:
    """Classify the grounded proposition without changing its L1 event policy."""
    if (
        claim.assertion_mode is L2AssertionMode.ASSERTED
        and classification.evidence_class in {"user_self_report", "user_question", "user_request"}
        and classification.speaker_role == "user"
        and classification.semantic_owner == "user"
    ):
        return "user_self_report"
    return classification.evidence_class


@dataclass(frozen=True, slots=True)
class ClaimGraphSource:
    """An actual supporting event authorized to contribute graph evidence."""

    event: MemoryEvent
    evidence_class: str


def resolve_claim_graph_sources(
    claims: Iterable[L2Phase1FactClaim],
    eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]],
) -> dict[str, ClaimGraphSource]:
    """Use each Claim's own supporting events, never the batch's last event."""
    result: dict[str, ClaimGraphSource] = {}
    for claim in claims:
        sources: list[ClaimGraphSource] = []
        for event, classification, policy in eligible_events:
            if event.event_id not in claim.supporting_event_ids:
                continue
            evidence_class = grounded_claim_evidence_class(claim, classification)
            if policy.allow_graph_write or evidence_class == "user_self_report":
                sources.append(ClaimGraphSource(event, evidence_class))
        if sources:
            result[claim.claim_id] = max(
                sources,
                key=lambda source: (source.evidence_class == "user_self_report", source.event.timestamp, source.event.event_id),
            )
    return result
