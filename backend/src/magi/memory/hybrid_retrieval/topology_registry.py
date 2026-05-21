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
        primary_predicates=("VISITED",),
        primary_object_types=("place",),
        bridge_predicate="LOCATED_IN",
        bridge_object_types=("place",),
        bridge_skip_evidence_filter=True,
    ),
    "topic": TopologySpec(
        primary_predicates=("LIKES", "INTERESTED_IN", "FOLLOWS"),
        primary_object_types=("topic",),
        bridge_predicate=None,
        bridge_object_types=(),
        bridge_skip_evidence_filter=False,
    ),
    "software": TopologySpec(
        primary_predicates=("USES", "LIKES", "INTERESTED_IN"),
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
    """Stub — implemented in Task 3."""
    raise NotImplementedError("Task 3 implements _execute_topology")
