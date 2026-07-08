"""Insight extraction pipeline for timeline events."""
from __future__ import annotations

import inspect
from typing import Any, Iterable

from magi.identity.defaults import CANONICAL_LOCAL_USER

from .contracts import TimelineEvent

_CANONICAL_SELF_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"

ALLOWED_EDGE_TYPES = {
    "LIKES",
    "DISLIKES",
    "CARES_ABOUT",
    "INTERACTED_WITH",
    "VISITED",
    "PURCHASED",
    "VIEWED",
    "LISTENED",
    "CREATED",
    "COMMITTED",
    "CHECKED_OUT",
    "MERGED",
    "REBASED",
    "EXECUTED",
    "USED",
    "CAPTURED",
    "OWNS",
    "MENTIONED",
    "RELATED_TO",
}


class TimelineInsightPipeline:
    """Normalizes relation candidates and writes allowed edges to the user graph."""

    def __init__(self, unified_memory) -> None:
        self._unified_memory = unified_memory

    def normalize_relation(self, relation_type: str) -> str | None:
        normalized = str(relation_type or "").strip().upper()
        if normalized in ALLOWED_EDGE_TYPES:
            return normalized
        return None

    async def process_event(
        self,
        event: TimelineEvent,
        relation_candidates: Iterable[dict[str, Any]],
        allowed_edge_whitelist: Iterable[str],
    ) -> list[dict[str, Any]]:
        allowed = {
            normalized
            for normalized in (
                self.normalize_relation(edge_type) for edge_type in allowed_edge_whitelist
            )
            if normalized is not None
        }
        persisted: list[dict[str, Any]] = []
        for candidate in relation_candidates:
            predicate = self.normalize_relation(str(candidate.get("predicate", "")))
            if predicate is None or predicate not in allowed:
                continue
            subject_id = str(candidate.get("subject_id", _CANONICAL_SELF_ENTITY_ID))
            object_id = str(candidate.get("object_id", "")).strip()
            if not object_id:
                continue
            subject_type = str(candidate.get("subject_type", "user"))
            object_type = str(candidate.get("object_type", "topic"))
            confidence = float(candidate.get("confidence", 0.5))
            observed_at = float(candidate.get("observed_at", event.occurred_at))
            source_type = str(candidate.get("source_type", event.source_type))
            maybe_awaitable = self._unified_memory.upsert_user_graph_edge(
                subject_id=subject_id,
                subject_type=subject_type,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                evidence_event_ids=[event.event_id],
                confidence=confidence,
                observed_at=observed_at,
                source_type=source_type,
                subject_attributes=dict(candidate.get("subject_attributes", {})),
                object_attributes=dict(candidate.get("object_attributes", {})),
            )
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
            persisted.append(
                {
                    "subject_id": subject_id,
                    "predicate": predicate,
                    "object_id": object_id,
                    "confidence": confidence,
                }
            )
        return persisted
