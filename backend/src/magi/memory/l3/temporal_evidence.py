"""Evidence-pack and rule-hint helpers for L3 temporal summaries."""

from __future__ import annotations

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
_CONSTRAINT_KEYWORDS = {
    "avoid",
    "budget",
    "cannot",
    "deadline",
    "hybrid",
    "must",
    "need",
    "prefer",
    "priority",
    "remote",
    "salary",
    "should",
    "time",
}


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
        evidence_items = [
            TemporalEvidenceItem(
                event_id=str(event.get("event_id") or ""),
                event_type=str(event.get("event_type") or ""),
                content=str(event.get("content") or ""),
                timestamp=float(event["timestamp"]) if event.get("timestamp") is not None else None,
                memory_domain=str(event.get("memory_domain") or "") or None,
                importance_score=float(event["importance_score"])
                if event.get("importance_score") is not None
                else None,
                interpretation_context=first_context_interpretation_context(event),
            )
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
            importance_aggregate=(sum(importance_values) / len(importance_values))
            if importance_values
            else None,
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
        ordered_items = sorted(
            evidence_items,
            key=lambda item: float(item.timestamp) if item.timestamp is not None else float("inf"),
        )
        window_change_candidates = self._build_window_change_candidates(ordered_items)
        recurring_constraints = self._build_recurring_constraints(evidence_items)
        return {
            "top_terms": [term for term, _count in term_counter.most_common(5)],
            "high_importance_event_ids": high_importance_event_ids,
            "repeated_event_types": repeated_event_types,
            "window_change_candidates": window_change_candidates,
            "recurring_constraints": recurring_constraints,
        }

    def _build_window_change_candidates(
        self,
        evidence_items: list[TemporalEvidenceItem],
    ) -> list[dict[str, object]]:
        if len(evidence_items) < 2:
            return []
        early_terms = self._extract_ranked_terms(evidence_items[0].content)[:3]
        late_terms = self._extract_ranked_terms(evidence_items[-1].content)[:3]
        new_terms = [term for term in late_terms if term not in early_terms][:3]
        dropped_terms = [term for term in early_terms if term not in late_terms][:3]
        if not early_terms and not late_terms:
            return []
        return [
            {
                "kind": "first_last_focus_shift",
                "from_event_id": evidence_items[0].event_id,
                "to_event_id": evidence_items[-1].event_id,
                "early_terms": early_terms,
                "late_terms": late_terms,
                "new_terms": new_terms,
                "dropped_terms": dropped_terms,
            }
        ]

    def _build_recurring_constraints(
        self,
        evidence_items: list[TemporalEvidenceItem],
    ) -> list[dict[str, object]]:
        hits: dict[str, list[str]] = {}
        for item in evidence_items:
            content = item.content.lower()
            matched = [keyword for keyword in _CONSTRAINT_KEYWORDS if keyword in content]
            for keyword in matched:
                hits.setdefault(keyword, [])
                if item.event_id not in hits[keyword]:
                    hits[keyword].append(item.event_id)
        recurring = [
            {
                "keyword": keyword,
                "event_ids": event_ids,
            }
            for keyword, event_ids in sorted(hits.items())
            if len(event_ids) >= 2
        ]
        return recurring

    def _extract_ranked_terms(self, content: str) -> list[str]:
        counter: Counter[str] = Counter()
        for token in _TOP_TERM_PATTERN.findall(content.lower()):
            if token in _STOP_TERMS:
                continue
            counter[token] += 1
        return [term for term, _count in counter.most_common(5)]


__all__ = ["TemporalEvidencePackMixin"]
