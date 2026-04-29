"""Rule-based candidate extraction helpers for the L2 cognition store."""

from __future__ import annotations

from typing import Optional, Protocol, cast

from ...event_contracts import MemoryEvent, TomDepth
from ..models import L2KnowledgeEdgeWrite, L2TomAssertionWrite
from ..storage.utils import CALM_KEYWORDS, STRESS_KEYWORDS


class _CandidateHostProtocol(Protocol):
    def _entity_identity(self, event: MemoryEvent) -> tuple[Optional[str], Optional[str]]:
        ...


class L2StoreCandidateExtractionMixin:
    """Build lightweight rule-based L2 candidates from events."""

    def _extract_graph_candidates(self, event: MemoryEvent) -> list[L2KnowledgeEdgeWrite]:
        content = event.content.lower()
        if " like " not in f" {content} ":
            return []
        subject_id, subject_type = cast(_CandidateHostProtocol, self)._entity_identity(event)
        if subject_id is None or subject_type is None:
            return []
        return [
            L2KnowledgeEdgeWrite(
                subject_id=subject_id,
                subject_type=subject_type,
                predicate="LIKES",
                object_id="topic:mentioned_preference",
                object_type="topic",
                evidence_event_ids=[event.event_id],
                confidence=0.7,
                observed_at=event.timestamp,
                source_type=event.source,
                extraction_method="keyword_rule",
            )
        ]

    def _extract_assertion_candidates(self, event: MemoryEvent) -> list[L2TomAssertionWrite]:
        subject_id, subject_type = cast(_CandidateHostProtocol, self)._entity_identity(event)
        if subject_id is None or subject_type is None:
            return []
        if not event.cognition_eligible or event.tom_depth != TomDepth.DEFENSIVE_PSYCHOLOGY:
            return []

        text = event.content.lower()
        if any(keyword in text for keyword in STRESS_KEYWORDS):
            return [
                L2TomAssertionWrite(
                    entity_id=subject_id,
                    entity_type=subject_type,
                    trait_name="stress_level",
                    trait_value="high",
                    confidence_score=0.3,
                    evidence_events=[event.event_id],
                    volatility_index=0.7,
                    source_domain=event.memory_domain.label,
                    inference_depth=event.tom_depth.label,
                    validation_state="tentative",
                    first_inferred_at=event.timestamp,
                    last_validated_at=event.timestamp,
                )
            ]
        if any(keyword in text for keyword in CALM_KEYWORDS):
            return [
                L2TomAssertionWrite(
                    entity_id=subject_id,
                    entity_type=subject_type,
                    trait_name="stress_level",
                    trait_value="low",
                    confidence_score=0.3,
                    evidence_events=[event.event_id],
                    volatility_index=0.7,
                    source_domain=event.memory_domain.label,
                    inference_depth=event.tom_depth.label,
                    validation_state="tentative",
                    first_inferred_at=event.timestamp,
                    last_validated_at=event.timestamp,
                )
            ]
        return []
