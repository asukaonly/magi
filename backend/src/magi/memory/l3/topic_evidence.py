"""Evidence-pack and rule-hint helpers for L3 thematic topic summaries."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .evidence_context import first_context_interpretation_context
from .models import ThematicEvidenceItem, ThematicEvidencePack

_TOP_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOP_TERMS = {
    "about",
    "across",
    "after",
    "and",
    "are",
    "first",
    "for",
    "from",
    "into",
    "job",
    "jobs",
    "looks",
    "more",
    "multiple",
    "portfolio",
    "roles",
    "should",
    "stronger",
    "switch",
    "than",
    "that",
    "the",
    "this",
    "want",
    "year",
}


class TopicEvidencePackMixin:
    """Build thematic topic evidence packs and deterministic rule hints."""

    def build_evidence_pack(
        self,
        *,
        topic: str,
        events: list[dict[str, Any]],
    ) -> ThematicEvidencePack:
        evidence_items = [
            ThematicEvidenceItem(
                event_id=str(event.get("event_id") or ""),
                event_type=str(event.get("event_type") or ""),
                content=str(event.get("content") or ""),
                timestamp=float(event["timestamp"]) if event.get("timestamp") is not None else None,
                importance_score=float(event["importance_score"])
                if event.get("importance_score") is not None
                else None,
                interpretation_context=first_context_interpretation_context(event),
            )
            for event in events
            if str(event.get("event_id") or "").strip()
        ]
        source_event_ids = [item.event_id for item in evidence_items]
        importance_values = [
            item.importance_score for item in evidence_items if item.importance_score is not None
        ]
        event_type_distribution: dict[str, int] = {}
        for item in evidence_items:
            event_type_distribution[item.event_type] = (
                event_type_distribution.get(item.event_type, 0) + 1
            )
        return ThematicEvidencePack(
            topic=str(topic).strip(),
            source_event_count=len(source_event_ids),
            source_event_ids=source_event_ids,
            events=evidence_items,
            importance_aggregate=(sum(importance_values) / len(importance_values))
            if importance_values
            else None,
            event_type_distribution=event_type_distribution,
            rule_hints=self._build_rule_hints(evidence_items, event_type_distribution),
        )

    def _build_rule_hints(
        self,
        evidence_items: list[ThematicEvidenceItem],
        event_type_distribution: dict[str, int],
    ) -> dict[str, object]:
        term_counter: Counter[str] = Counter()
        for item in evidence_items:
            for token in _TOP_TERM_PATTERN.findall(item.content.lower()):
                if token in _STOP_TERMS:
                    continue
                term_counter[token] += 1
        high_importance_event_ids = [
            item.event_id
            for item in sorted(
                evidence_items,
                key=lambda candidate: float(candidate.importance_score or 0.0),
                reverse=True,
            )[:3]
            if item.event_id
        ]
        repeated_event_types = [
            event_type
            for event_type, count in sorted(event_type_distribution.items())
            if count > 1 and event_type
        ]
        return {
            "top_terms": [term for term, _count in term_counter.most_common(5)],
            "high_importance_event_ids": high_importance_event_ids,
            "repeated_event_types": repeated_event_types,
        }


__all__ = ["TopicEvidencePackMixin"]
