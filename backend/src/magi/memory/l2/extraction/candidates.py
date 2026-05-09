"""Rule-based candidate extraction helpers for the L2 cognition store."""

from __future__ import annotations

from typing import Optional, Protocol, cast

from ...event_contracts import MemoryEvent
from ..models import L2KnowledgeEdgeWrite, L2TomAssertionWrite


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
        # Stress/calm assertion candidates used to be generated here from a
        # tiny English-only keyword list (anxious/relaxed/...). It missed every
        # non-English speaker and double-emitted whatever the L2 LLM extraction
        # already produces. The LLM pipeline is now the single source of mood
        # / stress assertions; rule fallback intentionally stays empty.
        del event
        return []
