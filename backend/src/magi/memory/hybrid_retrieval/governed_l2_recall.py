"""Correction-aware L2 claim view used by product recall."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import TimeRange

_EDGE_VECTOR_OVERFETCH_FACTOR = 8
_EDGE_VECTOR_CANDIDATE_CAP = 256


@dataclass(frozen=True)
class GovernedTemporalBounds:
    """One normalized point/range contract for governed claim reads."""

    effective_at: float
    effective_range: tuple[float | None, float | None] | None
    include_history: bool


def governed_temporal_bounds(
    time_range: TimeRange | None,
    *,
    now: float | None = None,
) -> GovernedTemporalBounds:
    """Normalize a product ``TimeRange`` once for L2 and graph retrieval."""
    current = float(now if now is not None else time.time())
    if time_range is None:
        return GovernedTemporalBounds(current, None, False)
    if time_range.as_of is not None:
        return GovernedTemporalBounds(float(time_range.as_of), None, True)
    if time_range.start is not None and time_range.end is not None:
        start = float(time_range.start)
        end = float(time_range.end)
        return GovernedTemporalBounds(end, (start, end), True)
    if time_range.start is not None:
        start = float(time_range.start)
        if start > current:
            return GovernedTemporalBounds(start, (start, None), True)
        return GovernedTemporalBounds(current, (start, current), True)
    if time_range.end is not None:
        end = float(time_range.end)
        return GovernedTemporalBounds(end, (None, end), True)
    return GovernedTemporalBounds(current, None, False)


class GovernedL2RecallView:
    """Expose only correction-aware assertion and relationship reads.

    Low-level hybrid retrievers keep their query-shaping responsibilities, but
    every product claim read crosses this view before ranking or prompt assembly.
    Administrative/raw store APIs are deliberately not exposed here.
    """

    def __init__(
        self,
        store: Any,
        *,
        context_scope: Mapping[str, Any] | None,
        effective_at: float,
        effective_range: tuple[float | None, float | None] | None = None,
        include_relationship_history: bool = False,
    ) -> None:
        self._store = store
        self._context_scope = dict(context_scope or {})
        self._effective_at = float(effective_at)
        self._effective_range = effective_range
        self._include_relationship_history = bool(include_relationship_history)

    async def list_tom_assertions(
        self,
        *,
        entity_id: str | None = None,
        entity_type: str | None = None,
        trait_families: list[str] | None = None,
        validation_states: list[str] | None = None,
        include_expired: bool = False,
        include_inactive: bool = False,
        include_superseded: bool = False,
        target_entity_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        temporal_clause: tuple[str, list[Any]] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return governed assertions; raw lifecycle flags cannot widen recall."""
        del include_expired, include_inactive, include_superseded, offset, temporal_clause, query
        assertions = await self._store.list_current_assertions(
            entity_id=entity_id,
            entity_type=entity_type,
            trait_families=trait_families,
            validation_states=validation_states,
            target_entity_id=target_entity_id,
            context_scope=self._context_scope,
            effective_at=self._effective_at,
            effective_range=self._effective_range,
            committed_only=not self._include_relationship_history,
            limit=limit,
        )
        return [self._mark_governed(item) for item in assertions]

    async def batch_list_tom_assertions(
        self,
        *,
        entity_ids: list[str],
        entity_type: str | None = None,
        trait_families: list[str] | None = None,
        validation_states: list[str] | None = None,
        include_expired: bool = False,
        include_inactive: bool = False,
        include_superseded: bool = False,
        target_entity_id: str | None = None,
        limit_per_entity: int = 100,
        temporal_clause: tuple[str, list[Any]] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch governed assertions and preserve per-entity result limits."""
        del include_expired, include_inactive, include_superseded, temporal_clause
        unique_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
        if not unique_ids:
            return {}
        per_entity = await self._store.batch_list_current_assertions(
            entity_ids=unique_ids,
            entity_type=entity_type,
            trait_families=trait_families,
            validation_states=validation_states,
            target_entity_id=target_entity_id,
            context_scope=self._context_scope,
            effective_at=self._effective_at,
            effective_range=self._effective_range,
            committed_only=not self._include_relationship_history,
            limit_per_entity=limit_per_entity,
        )
        return {
            entity_id: [self._mark_governed(item) for item in per_entity.get(entity_id, [])]
            for entity_id in unique_ids
        }

    async def get_relationships(
        self,
        *,
        subject_id: str | None = None,
        object_id: str | None = None,
        status: str = "active",
        status_filters: list[str] | None = None,
        predicates: list[str] | None = None,
        object_types: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        temporal_clause: tuple[str, list[Any]] | None = None,
        evidence_classes: list[str] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return governed relationships; raw status filters cannot widen recall."""
        del status, status_filters, offset, temporal_clause, query
        relationships = await self._store.list_current_relationships(
            subject_id=subject_id,
            object_id=object_id,
            predicates=predicates,
            object_types=object_types,
            evidence_classes=evidence_classes,
            context_scope=self._context_scope,
            effective_at=self._effective_at,
            effective_range=self._effective_range,
            include_history=self._include_relationship_history,
            committed_only=not self._include_relationship_history,
            limit=limit,
        )
        return [self._mark_governed(item) for item in relationships]

    async def batch_get_relationships(
        self,
        *,
        entity_ids: list[str],
        direction: str = "outgoing",
        status: str = "active",
        status_filters: list[str] | None = None,
        predicates: list[str] | None = None,
        target_object_id: str | None = None,
        object_types: list[str] | None = None,
        limit_per_entity: int = 100,
        temporal_clause: tuple[str, list[Any]] | None = None,
        evidence_classes: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch governed relationships and preserve direction-aware buckets."""
        del status, status_filters, temporal_clause
        unique_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
        if not unique_ids:
            return {}
        per_entity = await self._store.batch_list_current_relationships(
            entity_ids=unique_ids,
            direction=direction,
            object_id=target_object_id,
            predicates=predicates,
            object_types=object_types,
            evidence_classes=evidence_classes,
            context_scope=self._context_scope,
            effective_at=self._effective_at,
            effective_range=self._effective_range,
            include_history=self._include_relationship_history,
            committed_only=not self._include_relationship_history,
            limit_per_entity=limit_per_entity,
        )
        return {
            entity_id: [self._mark_governed(item) for item in per_entity.get(entity_id, [])]
            for entity_id in unique_ids
        }

    async def search_edges_by_embedding(
        self,
        vector_index: Any,
        embedding: Any,
        limit: int,
        status_filters: list[str] | None = None,
        predicates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Hydrate vector candidates through the governed relationship read."""
        del status_filters
        requested_limit = max(1, int(limit))
        candidate_limit = (
            requested_limit
            if requested_limit >= _EDGE_VECTOR_CANDIDATE_CAP
            else min(
                _EDGE_VECTOR_CANDIDATE_CAP,
                max(
                    requested_limit * _EDGE_VECTOR_OVERFETCH_FACTOR,
                    requested_limit + _EDGE_VECTOR_OVERFETCH_FACTOR,
                ),
            )
        )
        while True:
            candidates = await self._store.search_edges_by_embedding(
                vector_index=vector_index,
                embedding=embedding,
                limit=candidate_limit,
                status_filters=["active", "deprecated"],
                predicates=predicates,
            )
            results = await self._hydrate_vector_candidates(
                candidates,
                predicates=predicates,
                requested_limit=requested_limit,
            )
            if (
                len(results) >= requested_limit
                or len(candidates) < candidate_limit
                or candidate_limit >= _EDGE_VECTOR_CANDIDATE_CAP
            ):
                return results
            candidate_limit = min(_EDGE_VECTOR_CANDIDATE_CAP, candidate_limit * 2)

    async def _hydrate_vector_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        predicates: list[str] | None,
        requested_limit: int,
    ) -> list[dict[str, Any]]:
        triple_ids = list(
            dict.fromkeys(
                str(item.get("triple_id")) for item in candidates if item.get("triple_id")
            )
        )
        if not triple_ids:
            return []
        governed = await self._store.list_current_relationships(
            triple_ids=triple_ids,
            predicates=predicates,
            context_scope=self._context_scope,
            effective_at=self._effective_at,
            effective_range=self._effective_range,
            include_history=self._include_relationship_history,
            committed_only=not self._include_relationship_history,
            limit=max(len(triple_ids), requested_limit),
        )
        governed_by_id: dict[str, list[dict[str, Any]]] = {}
        for item in governed:
            governed_by_id.setdefault(str(item.get("triple_id")), []).append(
                self._mark_governed(item)
            )
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            triple_id = str(candidate.get("triple_id") or "")
            for relationship in governed_by_id.get(triple_id, []):
                # Vector metadata may be stale across a concurrent correction.
                # Governed lifecycle, validity, and scope fields always win.
                results.append({**candidate, **relationship})
                if len(results) >= requested_limit:
                    return results
        return results

    def _mark_governed(self, item: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["_governed_valid_at"] = self._effective_at
        return result


__all__ = [
    "GovernedL2RecallView",
    "GovernedTemporalBounds",
    "governed_temporal_bounds",
]
