"""Knowledge hybrid retriever: multi-channel relationship retrieval.

Channels:
1. Structured graph — direct SPO queries with grounding plan filters
2. Edge vector — semantic search with structural re-scoring
3. Topology — bounded multi-hop patterns (identity→presence→platform, place→containing place)

All channels run concurrently via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .grounding import L2GroundingPlan
from .temporal import build_knowledge_temporal_clause, compute_temporal_score

logger = logging.getLogger(__name__)


async def retrieve_knowledge(
    plan: L2GroundingPlan,
    store: Any,
    *,
    embedding_service: Any = None,
    edge_vector_index: Any = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Run multi-channel knowledge retrieval and merge results.

    Channels run concurrently. Each returns scored relationship dicts.
    Results are merged by triple_id (prefer lower vector_distance when duplicated).
    """
    tasks = [
        _structured_graph_channel(plan, store, limit=limit),
        _edge_vector_channel(plan, store, embedding_service, edge_vector_index, limit=limit),
        _topology_channel(plan, store, limit=limit),
    ]

    graph_results, vector_results, topo_results = await asyncio.gather(*tasks)

    merged = _merge_channels(graph_results, vector_results, topo_results)

    for edge in merged:
        edge["_temporal_score"] = compute_temporal_score(
            plan.temporal_context,
            first_observed=edge.get("first_observed_at"),
            last_observed=edge.get("last_observed_at"),
        )
        edge["_subject_match_score"] = _score_subject_match(edge, plan)
        edge["_predicate_match_score"] = _score_predicate_match(edge, plan)
        edge["_object_constraint_score"] = _score_object_constraints(edge, plan)
        edge["_candidate_kind"] = "knowledge_edge"

    return merged[:limit]


# ---------------------------------------------------------------------------
# Channel 1: Structured graph
# ---------------------------------------------------------------------------


async def _structured_graph_channel(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Query the knowledge graph using grounded SPO constraints."""
    tc = plan.temporal_context
    tc_sql, tc_params = build_knowledge_temporal_clause(tc)
    clause_arg = (tc_sql, tc_params) if tc_sql else None

    predicates = plan.expanded_predicates or None
    object_types = _extract_object_types(plan)
    status_filters = ["active"]
    evidence_classes = _evidence_classes_for(plan)

    subject_ids = plan.subject_entity_ids
    if subject_ids:
        batch_result = await store.batch_get_relationships(
            entity_ids=subject_ids,
            direction=plan.relation_direction,
            status_filters=status_filters,
            predicates=predicates,
            object_types=object_types,
            limit_per_entity=limit,
            temporal_clause=clause_arg,
            evidence_classes=evidence_classes,
        )
        relationships: list[dict[str, Any]] = []
        for rels in batch_result.values():
            relationships.extend(rels)
        _tag_channel(relationships, "structured_graph")
        return relationships

    results = await store.get_relationships(
        predicates=predicates,
        status_filters=status_filters,
        object_types=object_types,
        limit=limit,
        temporal_clause=clause_arg,
        evidence_classes=evidence_classes,
    )
    _tag_channel(results, "structured_graph")
    return results


# ---------------------------------------------------------------------------
# Channel 2: Edge vector
# ---------------------------------------------------------------------------


async def _edge_vector_channel(
    plan: L2GroundingPlan,
    store: Any,
    embedding_service: Any,
    edge_vector_index: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search edge vectors by query embedding, then re-score with grounding plan."""
    if embedding_service is None or edge_vector_index is None:
        return []

    query_parts: list[str] = []
    for c in plan.subject_candidates:
        if c.surface and c.surface != "self":
            query_parts.append(c.surface)
    for c in plan.predicate_candidates:
        from ..l2.predicate_catalog import get_natural_label

        label = get_natural_label(c.predicate, "en")
        if label:
            query_parts.append(label)
        else:
            query_parts.append(c.predicate.lower().replace("_", " "))
    for c in plan.object_candidates:
        if c.surface:
            query_parts.append(c.surface)

    if not query_parts:
        return []

    query_text = " ".join(query_parts)
    try:
        embedding = await embedding_service.embed_text(query_text)
    except Exception:
        logger.debug("Edge vector embedding failed", exc_info=True)
        return []

    if embedding is None:
        return []

    from ..embedding.embedding_text_builders import L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION

    if hasattr(embedding_service, "result_for_index"):
        embedding = embedding_service.result_for_index(
            embedding,
            text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
        )

    results = await store.search_edges_by_embedding(
        vector_index=edge_vector_index,
        embedding=embedding,
        limit=limit * 2,
        status_filters=["active"],
    )
    _tag_channel(results, "edge_vector")
    return results


# ---------------------------------------------------------------------------
# Channel 3: Topology
# ---------------------------------------------------------------------------


async def _topology_channel(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Handle bounded multi-hop topology patterns.

    Patterns:
    - creator: user→FOLLOWS/LIKES→presence, presence→PRESENCE_OF→person
    - place: user→VISITED→place, place→LOCATED_IN→parent_place
    """
    answer_kind = plan.answer_kind
    subject_ids = plan.subject_entity_ids

    if not subject_ids:
        return []

    if answer_kind == "creator":
        return await _topology_creator(plan, store, limit=limit)
    if answer_kind == "place":
        return await _topology_place(plan, store, limit=limit)

    return []


async def _topology_creator(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Creator topology: user → FOLLOWS/LIKES → presence/person, resolve via PRESENCE_OF.

    Delegates to ``_execute_topology`` with the registry spec.
    """
    from .topology_registry import ANSWER_KIND_TOPOLOGIES, _execute_topology
    results = await _execute_topology(
        spec=ANSWER_KIND_TOPOLOGIES["creator"],
        plan=plan,
        store=store,
        limit=limit,
    )
    _tag_channel(results, "topology")
    return results


async def _topology_place(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Place topology: find places within a target location.

    Constraint preprocessing: extract location_constraint from plan and pre-fetch
    candidate place IDs via LOCATED_IN. Then delegate user→candidate fetch +
    bridge resolution to ``_execute_topology``.
    """
    from .topology_registry import ANSWER_KIND_TOPOLOGIES, _execute_topology

    location_constraint = None
    for constraint in plan.object_constraints:
        if constraint.field in ("located_in", "location"):
            location_constraint = constraint.value
            break
    if not location_constraint:
        return []

    # Constraint pre-filter: LOCATED_IN is a geographic containment fact, not
    # the answer edge; do NOT forward evidence_classes here.
    location_rels = await store.get_relationships(
        predicates=["LOCATED_IN"],
        object_id=str(location_constraint),
        status_filters=["active"],
        limit=limit * 3,
    )
    candidate_ids = [r["subject_id"] for r in location_rels]
    if not candidate_ids:
        return []

    results = await _execute_topology(
        spec=ANSWER_KIND_TOPOLOGIES["place"],
        plan=plan,
        store=store,
        limit=limit,
        candidate_object_ids=candidate_ids,
    )
    _tag_channel(results, "topology")
    return results


# ---------------------------------------------------------------------------
# Merge and scoring helpers
# ---------------------------------------------------------------------------


def _merge_channels(
    *channel_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge results from multiple channels, deduplicating by triple_id."""
    seen: dict[str, dict[str, Any]] = {}
    for channel in channel_results:
        for edge in channel:
            tid = edge.get("triple_id", "")
            if not tid:
                continue
            if tid in seen:
                existing = seen[tid]
                existing.setdefault("_channels", [])
                new_channel = edge.get("_channel", "")
                if new_channel and new_channel not in existing["_channels"]:
                    existing["_channels"].append(new_channel)
                if "vector_distance" in edge:
                    existing_dist = existing.get("vector_distance")
                    if existing_dist is None or edge["vector_distance"] < existing_dist:
                        existing["vector_distance"] = edge["vector_distance"]
            else:
                edge.setdefault("_channels", [edge.get("_channel", "structured_graph")])
                seen[tid] = edge
    return list(seen.values())


def _tag_channel(results: list[dict[str, Any]], channel: str) -> None:
    for r in results:
        r["_channel"] = channel


def _evidence_classes_for(plan: L2GroundingPlan) -> list[str] | None:
    """Materialize plan.allowed_evidence_classes as a list for SQL `IN`.

    Returns ``None`` when the plan didn't opt in, preserving pre-existing
    behavior for callers that don't constrain by evidence class.
    """
    if not plan.allowed_evidence_classes:
        return None
    return list(plan.allowed_evidence_classes)


def _extract_object_types(plan: L2GroundingPlan) -> list[str] | None:
    types: list[str] = []
    for constraint in plan.object_constraints:
        if constraint.field == "object_type":
            types.append(str(constraint.value))
    return types if types else None


def _score_subject_match(edge: dict[str, Any], plan: L2GroundingPlan) -> float:
    if not plan.subject_entity_ids:
        return 0.5
    subject_id = edge.get("subject_id", "")
    if subject_id in plan.subject_entity_ids:
        return 1.0
    return 0.0


def _score_predicate_match(edge: dict[str, Any], plan: L2GroundingPlan) -> float:
    if not plan.predicate_candidates:
        return 0.5
    predicate = edge.get("predicate", "")
    expanded = plan.expanded_predicates
    if predicate in expanded:
        return 1.0
    return 0.2


def _score_object_constraints(edge: dict[str, Any], plan: L2GroundingPlan) -> float:
    if not plan.object_constraints:
        return 1.0
    score = 1.0
    for constraint in plan.object_constraints:
        if constraint.field == "object_type":
            if edge.get("object_type") != constraint.value:
                score *= 0.3 if constraint.confidence > 0.8 else 0.6
    return score


__all__ = ["retrieve_knowledge"]
