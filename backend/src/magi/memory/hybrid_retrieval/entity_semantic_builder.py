"""Build entity-scoped semantic edges in the L2 knowledge graph.

After L2 extraction resolves entities for a new event, this module
identifies semantically similar events *within the same entity scope*
and creates ``SEMANTIC_CONTEXT`` edges between their cross-entity pairs
in the knowledge graph.

This is more precise than full-library kNN because edges are only
created between events that already share at least one entity, avoiding
false connections between unrelated but textually similar events.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..l2.models import L2ProjectionLease
from ..l2.projection.errors import ProjectionAttemptFencedError

logger = logging.getLogger(__name__)

# Default predicate for entity-scoped semantic edges
SEMANTIC_EDGE_PREDICATE = "SEMANTIC_CONTEXT"
SEMANTIC_EDGE_FACT_KIND = "semantic_edge"


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EntityScopedSemanticBuilder:
    """Build semantic edges scoped to shared entities.

    Given a newly extracted event and its resolved entities, finds
    sibling events (those sharing at least one entity) and creates
    ``SEMANTIC_CONTEXT`` edges in the knowledge graph between entity
    pairs in semantically similar events.
    """

    def __init__(
        self,
        l1_store: Any,
        l2_store: Any,
        *,
        config_getter: Optional[Callable[[], Any]] = None,
        similarity_threshold: float = 0.75,
        max_sibling_events: int = 20,
        max_edges_per_event: int = 10,
    ) -> None:
        self._l1_store = l1_store
        self._l2_store = l2_store
        self._config_getter = config_getter
        self._threshold = similarity_threshold
        self._max_siblings = max_sibling_events
        self._max_edges = max_edges_per_event

    def _resolve_config(self) -> tuple[bool, float, int, int]:
        """Read live config if available, falling back to constructor defaults."""
        if self._config_getter is not None:
            try:
                cfg = self._config_getter()
                memory_cfg = getattr(getattr(cfg, "agent", None), "memory", None)
                if memory_cfg is None and hasattr(cfg, "entity_semantic_edges"):
                    memory_cfg = cfg
                es = getattr(memory_cfg, "entity_semantic_edges", None)
                if es is not None:
                    return (
                        bool(getattr(es, "enabled", False)),
                        float(getattr(es, "similarity_threshold", self._threshold)),
                        int(getattr(es, "max_sibling_events", self._max_siblings)),
                        int(getattr(es, "max_edges_per_event", self._max_edges)),
                    )
            except Exception:
                pass
        # No config_getter or config missing — use constructor defaults
        return (True, self._threshold, self._max_siblings, self._max_edges)

    async def build_edges_for_event(
        self,
        event_id: str,
        entity_ids: List[str],
        *,
        observed_at: float,
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> int:
        """Build entity-scoped semantic edges for a newly extracted event.

        Returns the number of edges created/updated.
        """
        if not entity_ids or self._l1_store is None or self._l2_store is None:
            return 0

        enabled, threshold, max_siblings, max_edges = self._resolve_config()
        if not enabled:
            return 0

        lease_items = tuple(projection_leases)
        try:
            return await self._build_edges_impl(
                event_id,
                entity_ids,
                observed_at,
                threshold=threshold,
                max_siblings=max_siblings,
                max_edges=max_edges,
                projection_leases=lease_items,
            )
        except ProjectionAttemptFencedError:
            raise
        except Exception as exc:
            logger.warning(
                "Entity-scoped semantic edge building failed",
                exc_info=exc,
            )
            return 0

    async def _build_edges_impl(
        self,
        event_id: str,
        entity_ids: List[str],
        observed_at: float,
        *,
        threshold: float,
        max_siblings: int,
        max_edges: int,
        projection_leases: tuple[L2ProjectionLease, ...],
    ) -> int:
        sibling_ids = await self._find_sibling_event_ids(
            event_id=event_id,
            entity_ids=entity_ids,
            max_siblings=max_siblings,
        )
        if not sibling_ids:
            return 0

        similar_pairs = await self._find_similar_sibling_pairs(
            event_id=event_id,
            sibling_ids=sibling_ids,
            threshold=threshold,
            max_edges=max_edges,
        )
        if not similar_pairs:
            return 0

        event_entities = await self._event_entities_for_semantic_pairs(
            event_id=event_id,
            similar_pairs=similar_pairs,
        )
        edge_count = await self._upsert_semantic_context_edges(
            event_id=event_id,
            entity_ids=entity_ids,
            observed_at=observed_at,
            similar_pairs=similar_pairs,
            event_entities=event_entities,
            projection_leases=projection_leases,
        )
        logger.debug(
            "Entity-scoped semantic edges built",
            extra={
                "event_id": event_id,
                "entity_count": len(entity_ids),
                "sibling_count": len(sibling_ids),
                "similar_count": len(similar_pairs),
                "edge_count": edge_count,
            },
        )
        return edge_count

    async def _find_sibling_event_ids(
        self,
        *,
        event_id: str,
        entity_ids: List[str],
        max_siblings: int,
    ) -> Set[str]:
        entity_event_map: Dict[str, List[str]] = await self._l1_store.get_entity_event_ids(
            entity_ids,
            limit_per_entity=max_siblings,
        )
        sibling_ids: Set[str] = set()
        for eids in entity_event_map.values():
            sibling_ids.update(eids)
        sibling_ids.discard(event_id)
        return sibling_ids

    async def _find_similar_sibling_pairs(
        self,
        *,
        event_id: str,
        sibling_ids: Set[str],
        threshold: float,
        max_edges: int,
    ) -> List[Tuple[str, float]]:
        all_event_ids = [event_id] + list(sibling_ids)
        vectors: Dict[str, List[float]] = await self._l1_store.get_event_vectors(all_event_ids)
        new_vec = vectors.get(event_id)
        if new_vec is None:
            logger.debug("No embedding for new event %s, skipping semantic edges", event_id)
            return []

        similar_pairs: List[Tuple[str, float]] = []  # (sibling_event_id, similarity)
        for sib_id in sibling_ids:
            sib_vec = vectors.get(sib_id)
            if sib_vec is None:
                continue
            sim = cosine_similarity(new_vec, sib_vec)
            if sim >= threshold:
                similar_pairs.append((sib_id, sim))
        similar_pairs.sort(key=lambda x: x[1], reverse=True)
        return similar_pairs[:max_edges]

    async def _event_entities_for_semantic_pairs(
        self,
        *,
        event_id: str,
        similar_pairs: List[Tuple[str, float]],
    ) -> Dict[str, List[str]]:
        similar_sib_ids = [s[0] for s in similar_pairs]
        return await self._l1_store.get_event_entity_ids([event_id] + similar_sib_ids)

    async def _upsert_semantic_context_edges(
        self,
        *,
        event_id: str,
        entity_ids: List[str],
        observed_at: float,
        similar_pairs: List[Tuple[str, float]],
        event_entities: Dict[str, List[str]],
        projection_leases: tuple[L2ProjectionLease, ...],
    ) -> int:
        new_entities = set(event_entities.get(event_id, entity_ids))
        edge_count = 0
        for sib_id, sim in similar_pairs:
            pairs = self._semantic_context_pairs_for_sibling(
                new_entities=new_entities,
                sibling_entities=set(event_entities.get(sib_id, [])),
            )
            for pair in pairs:
                if await self._upsert_semantic_context_edge(
                    event_id=event_id,
                    sibling_event_id=sib_id,
                    observed_at=observed_at,
                    similarity=sim,
                    pair=pair,
                    projection_leases=projection_leases,
                ):
                    edge_count += 1
        return edge_count

    @staticmethod
    def _semantic_context_pairs_for_sibling(
        *,
        new_entities: Set[str],
        sibling_entities: Set[str],
    ) -> List[Tuple[str, str, str, str]]:
        shared = new_entities & sibling_entities
        if not shared:
            return []
        return _select_cross_entity_pairs(
            new_entities - shared,
            sibling_entities - shared,
            shared,
        )

    async def _upsert_semantic_context_edge(
        self,
        *,
        event_id: str,
        sibling_event_id: str,
        observed_at: float,
        similarity: float,
        pair: Tuple[str, str, str, str],
        projection_leases: tuple[L2ProjectionLease, ...],
    ) -> bool:
        subj_id, obj_id, subj_type, obj_type = pair
        try:
            await self._l2_store.upsert_knowledge_edge(
                subject_id=subj_id,
                subject_type=subj_type,
                predicate=SEMANTIC_EDGE_PREDICATE,
                object_id=obj_id,
                object_type=obj_type,
                fact_kind=SEMANTIC_EDGE_FACT_KIND,
                evidence_event_ids=[event_id, sibling_event_id],
                confidence=similarity,
                observed_at=observed_at,
                source_type="entity_semantic_builder",
                extraction_method="embedding_similarity",
                evidence_text=f"Cosine similarity {similarity:.3f} within shared entity scope",
                projection_leases=projection_leases,
            )
            return True
        except ProjectionAttemptFencedError:
            raise
        except Exception as exc:
            logger.debug("Failed to upsert semantic edge: %s", exc)
            return False


def _select_cross_entity_pairs(
    new_only: Set[str],
    sib_only: Set[str],
    shared: Set[str],
) -> List[Tuple[str, str, str, str]]:
    """Select entity pairs for semantic edges.

    Strategy:
    - If both events have unique entities, connect them cross-wise.
    - If one side has no unique entities, connect the other side's
      unique entities to a shared entity (propagate through the scope).

    Returns list of (subject_id, object_id, subject_type, object_type).
    """
    pairs: List[Tuple[str, str, str, str]] = []

    if new_only and sib_only:
        # Cross-entity: new-exclusive → sib-exclusive
        for n_eid in new_only:
            for s_eid in sib_only:
                pairs.append((n_eid, s_eid, _type_from_id(n_eid), _type_from_id(s_eid)))
    elif new_only and shared:
        # Connect new-exclusive entities to the shared scope entity
        scope_entity = next(iter(shared))
        for n_eid in new_only:
            pairs.append((n_eid, scope_entity, _type_from_id(n_eid), _type_from_id(scope_entity)))
    elif sib_only and shared:
        scope_entity = next(iter(shared))
        for s_eid in sib_only:
            pairs.append((scope_entity, s_eid, _type_from_id(scope_entity), _type_from_id(s_eid)))

    return pairs


def _type_from_id(entity_id: str) -> str:
    """Extract entity type from a prefixed entity ID like 'person:abc123'."""
    if ":" in entity_id:
        return entity_id.split(":", 1)[0]
    return "entity"
