"""Data-driven registry for answer_kind topology dispatch.

Phase 2B: replaces the if-else chains in `_topology_channel` and
`L2SemanticRelationshipMixin._execute_semantic_relationship_plan` with a
single ``TopologySpec`` per answer_kind, executed uniformly by
``_execute_topology``. Adding a new answer_kind requires only a registry
entry, not a new handler function.

Each spec describes:
- The primary edges to fetch from the user (or a constrained set of objects)
- An optional "bridge" hop (e.g. presence → person identity, place → parent place)
- Whether the bridge should bypass the question's evidence-class filter
  (true for identity-system edges that are not user preferences)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TopologySpec:
    """Declarative description of an answer_kind's edge-fetch topology."""

    primary_predicates: tuple[str, ...]
    primary_object_types: tuple[str, ...]
    bridge_predicate: Optional[str]
    bridge_object_types: tuple[str, ...]
    bridge_skip_evidence_filter: bool


ANSWER_KIND_TOPOLOGIES: dict[str, TopologySpec] = {
    "creator": TopologySpec(
        primary_predicates=("FOLLOWS", "LIKES", "INTERESTED_IN", "DISLIKES"),
        primary_object_types=("presence", "person"),
        bridge_predicate="PRESENCE_OF",
        bridge_object_types=("person",),
        bridge_skip_evidence_filter=True,
    ),
    "place": TopologySpec(
        primary_predicates=("VISITED", "LIKES", "DISLIKES"),
        primary_object_types=("place",),
        bridge_predicate="LOCATED_IN",
        bridge_object_types=("place",),
        bridge_skip_evidence_filter=True,
    ),
    "topic": TopologySpec(
        primary_predicates=("LIKES", "DISLIKES", "INTERESTED_IN", "FOLLOWS"),
        primary_object_types=("topic",),
        bridge_predicate=None,
        bridge_object_types=(),
        bridge_skip_evidence_filter=False,
    ),
    "software": TopologySpec(
        primary_predicates=("USES", "LIKES", "DISLIKES", "INTERESTED_IN"),
        primary_object_types=("software",),
        bridge_predicate=None,
        bridge_object_types=(),
        bridge_skip_evidence_filter=False,
    ),
    "person": TopologySpec(
        primary_predicates=("KNOWS", "INTERACTED_WITH", "FAMILY_OF"),
        primary_object_types=("person", "presence"),
        bridge_predicate="PRESENCE_OF",
        bridge_object_types=("person",),
        bridge_skip_evidence_filter=True,
    ),
}


async def _execute_topology(
    *,
    spec: TopologySpec,
    plan: Any,  # L2GroundingPlan — typed as Any to avoid circular import
    store: Any,
    limit: int = 20,
    candidate_object_ids: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Execute a topology query: primary edge fetch + optional bridge resolution.

    Two modes:
    - ``candidate_object_ids is None``: fetch user→primary via
      ``batch_get_relationships`` with predicate/object_type filters.
    - ``candidate_object_ids`` provided (constraint preprocessing already
      narrowed candidates): fetch user→each candidate via per-object
      ``get_relationships``.

    Bridge resolution (when ``spec.bridge_predicate`` is set) issues a second
    ``batch_get_relationships`` against the primary edge objects, attaching
    ``_resolved_identity`` to each primary edge whose object_type matches the
    primary spec. If ``spec.bridge_skip_evidence_filter`` is True, the bridge
    call omits ``evidence_classes`` (identity bridges are system-asserted).
    """
    subject_ids = list(plan.subject_entity_ids)
    if not subject_ids:
        return []

    evidence_classes = (
        list(plan.allowed_evidence_classes)
        if plan.allowed_evidence_classes
        else None
    )

    # ---- Primary edge fetch ----
    primary_edges: list[dict[str, Any]] = []
    if candidate_object_ids is None:
        batch_result = await store.batch_get_relationships(
            entity_ids=subject_ids,
            direction="outgoing",
            status_filters=["active"],
            predicates=list(spec.primary_predicates),
            object_types=list(spec.primary_object_types),
            limit_per_entity=limit,
            evidence_classes=evidence_classes,
        )
        for rels in batch_result.values():
            primary_edges.extend(rels)
    else:
        for cid in candidate_object_ids[:limit]:
            rels = await store.get_relationships(
                subject_id=subject_ids[0],
                object_id=cid,
                predicates=list(spec.primary_predicates),
                status_filters=["active"],
                limit=5,
                evidence_classes=evidence_classes,
            )
            primary_edges.extend(rels)

    # ---- Optional bridge resolution ----
    if spec.bridge_predicate and primary_edges:
        bridge_subject_ids = [
            edge["object_id"]
            for edge in primary_edges
            if edge.get("object_type") in spec.primary_object_types
        ]
        if bridge_subject_ids:
            bridge_evidence = (
                None if spec.bridge_skip_evidence_filter else evidence_classes
            )
            bridge_result = await store.batch_get_relationships(
                entity_ids=bridge_subject_ids,
                direction="outgoing",
                status_filters=["active"],
                predicates=[spec.bridge_predicate],
                object_types=list(spec.bridge_object_types),
                limit_per_entity=1,
                evidence_classes=bridge_evidence,
            )
            bridge_lookup: dict[str, dict[str, Any]] = {}
            for rels in bridge_result.values():
                for rel in rels:
                    bridge_lookup[rel["subject_id"]] = {
                        "object_id": rel["object_id"],
                        "object_type": rel.get("object_type", spec.bridge_object_types[0]),
                        "object": rel.get("object", rel["object_id"]),
                    }
            for edge in primary_edges:
                if (
                    edge.get("object_type") in spec.primary_object_types
                    and edge["object_id"] in bridge_lookup
                ):
                    edge["_resolved_identity"] = bridge_lookup[edge["object_id"]]

    return primary_edges
