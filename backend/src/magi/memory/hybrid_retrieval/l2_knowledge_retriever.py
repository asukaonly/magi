"""Knowledge hybrid retriever: multi-channel relationship retrieval.

Channels:
1. Structured graph — direct SPO queries with grounding plan filters
2. Edge vector — semantic search with structural re-scoring
3. Topology — bounded multi-hop patterns (identity→presence→platform, place→containing place)

All channels run concurrently via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .grounding import L2GroundingPlan
from .soft_edges import SEMANTIC_EDGE_PREDICATE
from .temporal import build_knowledge_temporal_clause, compute_temporal_score
from .traversal import HopSpec, TraversalPlan, execute_graph_traversal

logger = logging.getLogger(__name__)


async def retrieve_knowledge(
    plan: L2GroundingPlan,
    store: Any,
    *,
    embedding_service: Any = None,
    edge_vector_index: Any = None,
    l1_store: Any = None,
    user_id: str | None = None,
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

    if user_id and l1_store is not None:
        graph_results = await _filter_edges_by_l1_user_scope(
            graph_results, l1_store, user_id
        )
        vector_results = await _filter_edges_by_l1_user_scope(
            vector_results, l1_store, user_id
        )
        topo_results = await _filter_edges_by_l1_user_scope(
            topo_results, l1_store, user_id
        )

    merged = _merge_channels(graph_results, vector_results, topo_results)

    for edge in merged:
        first_observed = edge.get("first_observed_at")
        last_observed = edge.get("last_observed_at")
        if (
            edge.get("_governed_valid_at") is not None
            and plan.temporal_context is not None
            and plan.temporal_context.mode == "during"
        ):
            # Corrections turn an edge into an explicit validity interval.
            # Evidence timestamps are not the interval and must not hide either
            # side of a change that occurs inside a range query.
            first_observed = edge.get("valid_from") or first_observed
            last_observed = (
                edge.get("valid_to")
                or plan.temporal_context.end
                or last_observed
            )
        edge["_temporal_score"] = compute_temporal_score(
            plan.temporal_context,
            first_observed=first_observed,
            last_observed=last_observed,
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
    """Query the knowledge graph using grounded SPO constraints.

    P0: builds a TraversalPlan from the grounding plan and delegates the fetch
    to the shared ``execute_graph_traversal``. Behavior (store calls/kwargs) is
    preserved; the abstain rule (RFC #65/#67) lives in the executor.
    """
    tc_sql, tc_params = build_knowledge_temporal_clause(plan.temporal_context)
    clause_arg = (tc_sql, tc_params) if tc_sql else None

    object_types = _extract_object_types(plan)
    object_ids = _extract_explicit_object_ids(plan)

    hop2 = None
    max_hops = 1
    if plan.hop2_target_type:
        hop2 = HopSpec(object_types=(plan.hop2_target_type,), include_soft_edges=True)
        max_hops = 2

    traversal = TraversalPlan(
        seed_entity_ids=list(plan.subject_entity_ids),
        subject_scope=plan.subject_scope,
        hop1=HopSpec(
            predicates=tuple(plan.expanded_predicates),
            object_types=tuple(object_types) if object_types else (),
            include_soft_edges=plan.allow_soft_edges,
        ),
        hop2=hop2,
        max_hops=max_hops,
        limit=limit,
    )

    results = await execute_graph_traversal(
        traversal,
        store,
        relation_direction=plan.relation_direction,
        temporal_clause=clause_arg,
        evidence_classes=_evidence_classes_for(plan),
        candidate_object_ids=object_ids,
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
    # RFC #65 P2: soft edges enter only via the deliberate traversal sparse-fallback,
    # never incidentally by vector similarity here.
    results = [e for e in results if e.get("predicate") != SEMANTIC_EDGE_PREDICATE]
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
    """Bounded topology patterns, dispatched by answer_kind (P0: 1-hop)."""
    if not plan.subject_entity_ids:
        return []
    if plan.answer_kind == "creator":
        return await _topology_creator(plan, store, limit=limit)
    if plan.answer_kind == "place":
        return await _topology_place(plan, store, limit=limit)
    return []


def _topology_traversal(plan: L2GroundingPlan, answer_kind: str, *, limit: int) -> TraversalPlan:
    """Build a TraversalPlan from the (data-only) topology registry spec."""
    from .topology_registry import ANSWER_KIND_TOPOLOGIES

    spec = ANSWER_KIND_TOPOLOGIES[answer_kind]
    return TraversalPlan(
        seed_entity_ids=list(plan.subject_entity_ids),
        subject_scope=plan.subject_scope,
        hop1=HopSpec(
            predicates=spec.primary_predicates,
            object_types=spec.primary_object_types,
        ),
        limit=limit,
    )


async def _topology_creator(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Creator: user → FOLLOWS/LIKES/INTERESTED_IN/DISLIKES → presence/person."""
    traversal = _topology_traversal(plan, "creator", limit=limit)
    results = await execute_graph_traversal(
        traversal,
        store,
        relation_direction="outgoing",
        evidence_classes=_evidence_classes_for(plan),
    )
    _tag_channel(results, "topology")
    return results


async def _topology_place(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Place: LOCATED_IN pre-filter → user→{candidate places} recall."""
    location_constraint = None
    for constraint in plan.object_constraints:
        if constraint.field in ("located_in", "location"):
            location_constraint = constraint.value
            break
    if not location_constraint:
        return []

    # Geographic containment lookup — auxiliary, MUST NOT carry evidence_classes.
    location_rels = await store.get_relationships(
        predicates=["LOCATED_IN"],
        object_id=str(location_constraint),
        status_filters=["active"],
        limit=limit * 3,
    )
    candidate_ids = [r["subject_id"] for r in location_rels]
    if not candidate_ids:
        return []

    traversal = _topology_traversal(plan, "place", limit=limit)
    results = await execute_graph_traversal(
        traversal,
        store,
        relation_direction="outgoing",
        evidence_classes=_evidence_classes_for(plan),
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
            candidate_id = str(
                edge.get("_governed_version_id") or edge.get("triple_id") or ""
            )
            if not candidate_id:
                continue
            if candidate_id in seen:
                existing = seen[candidate_id]
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
                seen[candidate_id] = edge
    return list(seen.values())


def _tag_channel(results: list[dict[str, Any]], channel: str) -> None:
    for r in results:
        r["_channel"] = channel


async def _filter_edges_by_l1_user_scope(
    edges: list[dict[str, Any]],
    l1_store: Any,
    user_id: str,
) -> list[dict[str, Any]]:
    """Keep only L2 edges owned by the current user or a governed correction."""
    if not edges:
        return []

    edge_evidence: list[tuple[dict[str, Any], list[str]]] = []
    all_event_ids: list[str] = []
    for edge in edges:
        evidence_ids = _parse_evidence_ids(edge.get("evidence_event_ids"))
        edge_evidence.append((edge, evidence_ids))
        all_event_ids.extend(evidence_ids)

    unique_event_ids = list(dict.fromkeys(all_event_ids))
    if not unique_event_ids:
        return _governed_evidence_free_corrections(edge_evidence)

    filter_ids_by_user = getattr(l1_store, "filter_ids_by_user", None)
    if not callable(filter_ids_by_user):
        return _governed_evidence_free_corrections(edge_evidence)

    try:
        scoped_ids = await filter_ids_by_user(unique_event_ids, user_id)
    except Exception:
        logger.warning("Failed to filter L2 edges by L1 user scope", exc_info=True)
        return _governed_evidence_free_corrections(edge_evidence)

    scoped = set(scoped_ids)
    return [
        edge
        for edge, evidence_ids in edge_evidence
        if (not evidence_ids and _is_evidence_free_governed_user_correction(edge))
        or any(event_id in scoped for event_id in evidence_ids)
    ]


def _governed_evidence_free_corrections(
    edge_evidence: list[tuple[dict[str, Any], list[str]]],
) -> list[dict[str, Any]]:
    """Keep only locally governed corrections when ordinary ownership is unknown."""
    return [
        edge
        for edge, evidence_ids in edge_evidence
        if not evidence_ids and _is_evidence_free_governed_user_correction(edge)
    ]


def _is_evidence_free_governed_user_correction(edge: dict[str, Any]) -> bool:
    """Recognize authoritative local corrections that legitimately have no L1 event."""
    return (
        edge.get("_governed_valid_at") is not None
        and str(edge.get("source_type") or "") == "user_correction"
        and str(edge.get("extraction_method") or "") == "explicit"
        and str(edge.get("evidence_class") or "") == "user_self_report"
        and str(edge.get("authority_ref") or "").startswith("correction:")
    )


def _parse_evidence_ids(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(item) for item in raw if item]
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []


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


def _extract_explicit_object_ids(plan: L2GroundingPlan) -> list[str] | None:
    entity_ids: list[str] = []
    for candidate in plan.object_candidates:
        if candidate.source == "vector":
            continue
        if candidate.entity_id and candidate.entity_id not in entity_ids:
            entity_ids.append(candidate.entity_id)
    return entity_ids or None


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
