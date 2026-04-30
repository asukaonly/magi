"""Relationship query helpers for L2 hybrid retrieval."""

from __future__ import annotations

from typing import Any

from .protocols import L2StoreProtocol


class L2RelationshipQueryMixin:
    """Low-level relationship query helpers shared by L2 retrieval plans."""

    _store: L2StoreProtocol

    async def _query_relationships_for_entity(
        self,
        *,
        entity_id: str,
        entity_type: str,
        direction: str,
        predicates: list[str] | None,
        status_filters: list[str] | None,
        object_id: str | None,
        object_types: list[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if direction == "incoming":
            return await self._store.get_relationships(
                object_id=entity_id,
                predicates=predicates,
                status_filters=status_filters,
                limit=limit,
            )
        if direction == "both":
            outgoing = await self._store.get_relationships(
                subject_id=entity_id,
                predicates=predicates,
                status_filters=status_filters,
                object_id=object_id,
                object_types=object_types,
                limit=limit,
            )
            incoming = await self._store.get_relationships(
                object_id=entity_id,
                predicates=predicates,
                status_filters=status_filters,
                limit=limit,
            )
            seen: set[str] = set()
            merged: list[dict[str, Any]] = []
            for item in outgoing + incoming:
                triple_id = str(item.get("triple_id") or "")
                if triple_id and triple_id in seen:
                    continue
                if triple_id:
                    seen.add(triple_id)
                merged.append(item)
            return merged
        return await self._store.get_relationships(
            subject_id=entity_id,
            predicates=predicates,
            status_filters=status_filters,
            object_id=object_id if self._allows_object_id_filter(entity_type=entity_type, direction=direction) else None,
            object_types=object_types if self._allows_object_type_filter(entity_type=entity_type, direction=direction) else None,
            limit=limit,
        )


__all__ = ["L2RelationshipQueryMixin"]