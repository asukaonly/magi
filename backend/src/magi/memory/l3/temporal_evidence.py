"""Evidence-pack and rule-hint helpers for L3 temporal summaries."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from .evidence_context import first_context_interpretation_context
from .models import TemporalEvidenceItem, TemporalEvidencePack

_TOP_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOP_TERMS = {
    "about",
    "after",
    "and",
    "are",
    "care",
    "but",
    "for",
    "from",
    "have",
    "into",
    "job",
    "jobs",
    "just",
    "more",
    "posts",
    "read",
    "several",
    "than",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "want",
    "with",
    "year",
    "you",
    "your",
}
MAX_TEMPORAL_EVENT_CHARS = 6000
MAX_TEMPORAL_EVIDENCE_CHARS = 60000
_EXCERPT_MARKER = "\n[... source text omitted ...]\n"


def _metadata(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("metadata_json")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _content_limit(events: list[dict[str, Any]]) -> int:
    """Allocate a shared cap without letting a long transcript crowd out other sources."""
    lengths = [len(str(event.get("content") or "")) for event in events]
    low, high = 0, MAX_TEMPORAL_EVENT_CHARS
    while low < high:
        midpoint = (low + high + 1) // 2
        if sum(min(length, midpoint) for length in lengths) <= MAX_TEMPORAL_EVIDENCE_CHARS:
            low = midpoint
        else:
            high = midpoint - 1
    return low


def _excerpt(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    if limit <= len(_EXCERPT_MARKER):
        return content[:limit]
    remaining = limit - len(_EXCERPT_MARKER)
    head = remaining * 2 // 3
    tail = remaining - head
    return content[:head] + _EXCERPT_MARKER + content[-tail:]


def _evidence_item(event: dict[str, Any], content_limit: int) -> TemporalEvidenceItem:
    content = str(event.get("content") or "")
    metadata = _metadata(event)
    activity = metadata.get("activity")
    return TemporalEvidenceItem(
        event_id=str(event.get("event_id") or ""),
        event_type=str(event.get("event_type") or ""),
        content=_excerpt(content, content_limit),
        timestamp=float(event["timestamp"]) if event.get("timestamp") is not None else None,
        memory_domain=str(event.get("memory_domain") or "") or None,
        importance_score=(
            float(event["importance_score"]) if event.get("importance_score") is not None else None
        ),
        interpretation_context=first_context_interpretation_context(event),
        source=str(event.get("source") or "") or None,
        author_type=str(event.get("author_type") or "") or None,
        activity=(
            {
                key: activity[key]
                for key in ("source_code", "action_code", "object_code", "qualifiers")
                if key in activity
            }
            if isinstance(activity, dict)
            else None
        ),
        source_object_id=str(metadata.get("source_object_id") or "") or None,
        content_truncated=len(content) > content_limit,
    )


class TemporalEvidencePackMixin:
    """Build temporal evidence packs and deterministic rule hints."""

    def build_evidence_pack(
        self,
        *,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> TemporalEvidencePack:
        """Build a compact evidence pack from already-fetched L1 events."""
        kept_events = [
            event
            for event in events
            if str(event.get("memory_domain") or "") != "runtime_telemetry"
            and str(event.get("retention_class") or "") != "disposable"
        ]
        content_limit = _content_limit(kept_events)
        evidence_items = [
            _evidence_item(event, content_limit)
            for event in kept_events
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
        return TemporalEvidencePack(
            summary_category=summary_category,  # type: ignore[arg-type]
            period_start=float(period_start),
            period_end=float(period_end),
            source_event_count=len(source_event_ids),
            source_event_ids=source_event_ids,
            events=evidence_items,
            importance_aggregate=(
                (sum(importance_values) / len(importance_values)) if importance_values else None
            ),
            event_type_distribution=event_type_distribution,
            rule_hints=self._build_rule_hints(evidence_items, event_type_distribution),
        )

    def _build_rule_hints(
        self,
        evidence_items: list[TemporalEvidenceItem],
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
            event_type for event_type, count in sorted(event_type_distribution.items()) if count > 1
        ]
        return {
            "top_terms": [term for term, _count in term_counter.most_common(5)],
            "high_importance_event_ids": high_importance_event_ids,
            "repeated_event_types": repeated_event_types,
        }


__all__ = ["TemporalEvidencePackMixin"]
