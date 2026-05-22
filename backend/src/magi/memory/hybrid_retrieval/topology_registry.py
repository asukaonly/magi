"""Data-driven registry for answer_kind topology dispatch.

Phase 2B: replaces the if-else chains in `_topology_channel` with a single
``TopologySpec`` per answer_kind, executed uniformly by ``_execute_topology``.
Adding a new answer_kind requires only a registry entry, not a new handler
function.

Each spec describes:
- The primary edges to fetch from the user (or a constrained set of objects)
- An optional "bridge" hop (e.g. presence → person identity, place → parent
  place). These fields are kept on the spec so a future consumer (UI identity
  chip, projection layer) can opt into bridge resolution; the executor itself
  no longer performs the resolution because Phase 5's entity_catalog
  canonical-name resolution supersedes the previous ``_resolved_identity``
  sidecar (which had no production reader).
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
    """Execute a topology query: primary edge fetch only.

    Two modes:
    - ``candidate_object_ids is None``: fetch user→primary via
      ``batch_get_relationships`` with predicate/object_type filters.
    - ``candidate_object_ids`` provided (constraint preprocessing already
      narrowed candidates): fetch user→each candidate via per-object
      ``get_relationships``.

    Note: ``spec.bridge_predicate``/``bridge_object_types``/
    ``bridge_skip_evidence_filter`` are retained on the registry so a
    future consumer (UI identity chip, projection layer) can opt into
    bridge resolution. The executor itself no longer attaches a
    ``_resolved_identity`` sidecar — Phase 5's ``entity_catalog`` canonical
    name resolution superseded that sidecar (no production reader existed).
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

    # Bridge resolution (PRESENCE_OF, LOCATED_IN) previously attached
    # _resolved_identity to primary edges, but no production consumer reads
    # that field. Phase 5 uses entity_catalog instead. The bridge config in
    # TopologySpec is kept so a future consumer (UI identity chip, projection
    # layer) can opt in.
    return primary_edges
