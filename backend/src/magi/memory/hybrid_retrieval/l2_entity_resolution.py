"""Entity resolution operations for L2 hybrid retrieval."""

from __future__ import annotations

from typing import Optional

from .models import L2Conditions
from .protocols import EntityCatalogProtocol


class L2EntityResolutionMixin:
    """Resolve structured and free-text entity references for L2 queries."""

    _entity_catalog: EntityCatalogProtocol | None

    async def _resolve_entities(
        self,
        conditions: L2Conditions,
        *,
        user_id: Optional[str] = None,
    ) -> list[dict[str, str]]:
        resolved: list[dict[str, str]] = []
        seen: set[str] = set()

        for entity in conditions.entities or []:
            normalized = str(entity).strip()
            if not normalized:
                continue
            if ":" in normalized:
                entity_type, _, _ = normalized.partition(":")
                if normalized not in seen:
                    resolved.append({"entity_id": normalized, "entity_type": entity_type or "entity", "match_source": "explicit"})
                    seen.add(normalized)
                continue
            if self._entity_catalog is None:
                continue
            matches = await self._entity_catalog.resolve_query_entities(
                normalized,
                limit=5,
                entity_types=conditions.entity_types,
            )
            for match in matches:
                entity_id = str(match["entity_id"])
                if entity_id in seen:
                    continue
                resolved.append({
                    "entity_id": entity_id,
                    "entity_type": str(match["entity_type"]),
                    "match_source": str(match.get("match_source") or "unknown"),
                })
                seen.add(entity_id)

        if resolved or self._entity_catalog is None or not conditions.content_query:
            return resolved

        # For unknown self-scoped predicates, the object is unknown.  Avoid
        # resolving incidental query text into a hard relationship filter.
        if conditions.subject_hint == "self" and (
            not conditions.predicate_family
            or conditions.predicate_family == "unknown"
        ):
            return resolved

        query_matches = await self._entity_catalog.resolve_query_entities(
            conditions.content_query,
            limit=max(conditions.limit, 5),
            entity_types=conditions.entity_types,
        )
        for match in query_matches:
            entity_id = str(match["entity_id"])
            if entity_id in seen:
                continue
            resolved.append({
                "entity_id": entity_id,
                "entity_type": str(match["entity_type"]),
                "match_source": str(match.get("match_source") or "unknown"),
            })
            seen.add(entity_id)
        return resolved


__all__ = ["L2EntityResolutionMixin"]