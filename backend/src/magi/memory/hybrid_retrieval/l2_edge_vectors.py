"""Edge vector supplement retrieval for L2 hybrid retrieval."""

from __future__ import annotations

import logging
from typing import Any

from .protocols import EmbeddingServiceProtocol, L2StoreProtocol
from ..embedding.embedding_text_builders import L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION

logger = logging.getLogger(__name__)


class L2EdgeVectorSupplementMixin:
    """Supplement relationship results with edge-vector similarity search."""

    _store: L2StoreProtocol
    _embedding_service: EmbeddingServiceProtocol | None
    _edge_vector_index: Any | None

    @staticmethod
    def _collect_boost_groups(predicates: list[str] | None) -> set[str] | None:
        """Collect synonym groups from predicates for soft re-ranking."""
        if not predicates:
            return None
        from ...memory.l2.ontology import get_predicate_synonym_group

        groups: set[str] = set()
        for pred in predicates:
            group = get_predicate_synonym_group(pred)
            if group:
                groups.add(group)
        return groups or None

    async def _supplement_edge_vector_search(
        self,
        *,
        content_query: str,
        existing_relationships: list[dict[str, Any]],
        status_filters: list[str] | None,
        predicates: list[str] | None,
        predicate_boost_groups: set[str] | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return vector-similar edges that are not already present."""
        if self._embedding_service is None or self._edge_vector_index is None:
            return []
        query_text = content_query.strip()
        if not query_text:
            return []
        try:
            embedding = await self._embedding_service.embed_text(query_text)
            if embedding is None:
                return []
            index_identity_builder = getattr(self._embedding_service, "result_for_index", None)
            if callable(index_identity_builder):
                embedding = index_identity_builder(
                    embedding,
                    text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
                )
            candidates = await self._store.search_edges_by_embedding(
                vector_index=self._edge_vector_index,
                embedding=embedding,
                limit=limit,
                status_filters=status_filters,
                predicates=predicates,
            )
        except Exception as exc:
            logger.debug("Edge vector supplement failed: %s", exc)
            return []
        if not candidates:
            return []

        if predicate_boost_groups:
            from ...memory.l2.ontology import get_predicate_synonym_group

            for edge in candidates:
                group = get_predicate_synonym_group(str(edge.get("predicate") or ""))
                if group and group in predicate_boost_groups:
                    dist = edge.get("vector_distance")
                    if dist is not None:
                        edge["vector_distance"] = dist * 0.7
            candidates.sort(key=lambda e: e.get("vector_distance") or float("inf"))

        existing_ids = {str(r.get("triple_id") or "") for r in existing_relationships}
        return [c for c in candidates if str(c.get("triple_id") or "") not in existing_ids]


__all__ = ["L2EdgeVectorSupplementMixin"]
