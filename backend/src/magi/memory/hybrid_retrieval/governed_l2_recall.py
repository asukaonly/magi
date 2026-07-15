"""Correction-aware L2 claim view used by product recall."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from .models import TemporalContext


def effective_at_for_context(
    temporal_context: TemporalContext | None,
    *,
    now: float | None = None,
) -> float:
    """Resolve a temporal retrieval intent to the governed claim point."""
    tc = temporal_context
    if tc is not None:
        if tc.mode == "as_of" and tc.anchor is not None:
            return float(tc.anchor)
        if tc.mode in {"during", "before"} and tc.end is not None:
            return float(tc.end)
    return float(now if now is not None else time.time())


def effective_range_for_context(
    temporal_context: TemporalContext | None,
    *,
    now: float | None = None,
) -> tuple[float | None, float | None] | None:
    """Return an interval for range intent without collapsing its history."""
    tc = temporal_context
    current = float(now if now is not None else time.time())
    if tc is None:
        return None
    if tc.mode == "during":
        return tc.start, tc.end
    if tc.mode == "since":
        return tc.start, current
    if tc.mode == "before":
        return None, tc.end
    if tc.mode == "after":
        return tc.start, current
    return None


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
    ) -> None:
        self._store = store
        self._context_scope = dict(context_scope or {})
        self._effective_at = float(effective_at)
        self._effective_range = effective_range

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
        per_entity = await asyncio.gather(
            *(
                self._store.list_current_assertions(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    trait_families=trait_families,
                    validation_states=validation_states,
                    target_entity_id=target_entity_id,
                    context_scope=self._context_scope,
                    effective_at=self._effective_at,
                    effective_range=self._effective_range,
                    limit=limit_per_entity,
                )
                for entity_id in unique_ids
            )
        )
        return {
            entity_id: [self._mark_governed(item) for item in assertions]
            for entity_id, assertions in zip(unique_ids, per_entity)
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
        per_entity = await asyncio.gather(
            *(
                self._store.list_current_relationships(
                    entity_ids=[entity_id],
                    direction=direction,
                    object_id=target_object_id,
                    predicates=predicates,
                    object_types=object_types,
                    evidence_classes=evidence_classes,
                    context_scope=self._context_scope,
                    effective_at=self._effective_at,
                    effective_range=self._effective_range,
                    limit=limit_per_entity,
                )
                for entity_id in unique_ids
            )
        )
        return {
            entity_id: [self._mark_governed(item) for item in relationships]
            for entity_id, relationships in zip(unique_ids, per_entity)
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
        candidates = await self._store.search_edges_by_embedding(
            vector_index=vector_index,
            embedding=embedding,
            limit=limit,
            status_filters=["active", "deprecated"],
            predicates=predicates,
        )
        triple_ids = [str(item.get("triple_id")) for item in candidates if item.get("triple_id")]
        if not triple_ids:
            return []
        governed = await self._store.list_current_relationships(
            triple_ids=triple_ids,
            predicates=predicates,
            context_scope=self._context_scope,
            effective_at=self._effective_at,
            effective_range=self._effective_range,
            limit=len(triple_ids),
        )
        governed_by_id = {
            str(item.get("triple_id")): self._mark_governed(item) for item in governed
        }
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            triple_id = str(candidate.get("triple_id") or "")
            relationship = governed_by_id.get(triple_id)
            if relationship is None:
                continue
            # Vector metadata may be stale across a concurrent correction. The
            # governed row must win for lifecycle, validity, and scope fields.
            results.append({**candidate, **relationship})
        return results

    def _mark_governed(self, item: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["_governed_valid_at"] = self._effective_at
        return result


__all__ = [
    "GovernedL2RecallView",
    "effective_at_for_context",
    "effective_range_for_context",
]
