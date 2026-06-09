"""Generalized L2 graph traversal: plan contract + typed executor (RFC #65).

P0 scope: a single-hop, typed (predicate/object_type) edge fetch that subsumes
the structured-graph and topology channels' fetch logic. Soft edges, hop2, decay
and ranking_mode are carried on the plan but unused until later phases. This
module is intentionally free of any ``L2GroundingPlan`` dependency — callers map
their grounded plan into a ``TraversalPlan`` and pass execution context as kwargs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class HopSpec:
    """One hop's edge selector: which predicates/types define this hop's answer."""

    predicates: tuple[str, ...] = ()
    object_types: tuple[str, ...] = ()
    include_soft_edges: bool = False


@dataclass
class TraversalPlan:
    """Per-query, derived plan for graph traversal (replaces answer_kind→frozen spec)."""

    seed_entity_ids: list[str] = field(default_factory=list)
    subject_scope: str = "none"
    hop1: HopSpec = field(default_factory=HopSpec)
    hop2: Optional[HopSpec] = None
    max_hops: int = 1
    ranking_mode: str = "confidence"
    decay: float = 0.5
    limit: int = 20
    # provenance: which resolver layer filled each field ("llm"|"embedding"|"keyword_fallback")
    resolution_source: dict[str, str] = field(default_factory=dict)


__all__ = ["HopSpec", "TraversalPlan", "execute_graph_traversal"]


async def execute_graph_traversal(
    traversal: TraversalPlan,
    store: Any,
    *,
    relation_direction: str = "outgoing",
    temporal_clause: Optional[tuple[str, list[Any]]] = None,
    evidence_classes: Optional[list[str]] = None,
    candidate_object_ids: Optional[list[str]] = None,
    per_candidate_limit: int = 5,
) -> list[dict[str, Any]]:
    """Execute a single typed hop, returning raw edge dicts.

    Modes:
    - candidate_object_ids given → per-object ``get_relationships`` (constraint
      preprocessing already narrowed objects, e.g. place LOCATED_IN→cafes).
    - subject_ids present → ``batch_get_relationships`` (the common recall path).
    - no subject → ``get_relationships`` unbounded fallback.

    Abstain (RFC #65/#67): no predicate AND no object_type AND no candidate set →
    a pure subject dump (whole-profile junk); return [] and defer to edge_vector.
    """
    hop = traversal.hop1
    predicates = list(hop.predicates) or None
    object_types = list(hop.object_types) or None
    limit = traversal.limit
    subject_ids = traversal.seed_entity_ids

    # Candidate-object mode (objects already narrowed by constraint preprocessing).
    if candidate_object_ids is not None:
        if not subject_ids:
            return []
        edges: list[dict[str, Any]] = []
        # Cap candidates at `limit`, mirroring the original topology executor
        # (preserved behavior; do not change in P0).
        for cid in candidate_object_ids[:limit]:
            # temporal_clause intentionally omitted here: object set already narrowed
            # by constraint preprocessing (matches original place-topology path).
            rels = await store.get_relationships(
                subject_id=subject_ids[0],  # single-subject context (preserved from original)
                object_id=cid,
                predicates=predicates,
                status_filters=["active"],
                limit=per_candidate_limit,
                evidence_classes=evidence_classes,
            )
            edges.extend(rels)
        return edges

    # Abstain: neither a predicate nor an object-type constraint → topically
    # unfiltered subject dump. The typed channel's value is exact matching.
    if predicates is None and object_types is None:
        return []

    if subject_ids:
        batch_result = await store.batch_get_relationships(
            entity_ids=subject_ids,
            direction=relation_direction,
            status_filters=["active"],
            predicates=predicates,
            object_types=object_types,
            limit_per_entity=limit,
            temporal_clause=temporal_clause,
            evidence_classes=evidence_classes,
        )
        edges = []
        for rels in batch_result.values():
            edges.extend(rels)
        return edges

    return await store.get_relationships(
        predicates=predicates,
        status_filters=["active"],
        object_types=object_types,
        limit=limit,
        temporal_clause=temporal_clause,
        evidence_classes=evidence_classes,
    )
