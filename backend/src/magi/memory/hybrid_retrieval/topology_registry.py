"""Pure data registry of answer_kind edge-fetch topologies (RFC #65).

Each ``TopologySpec`` entry declaratively describes what edges to fetch for an
answer_kind.  Execution is handled by ``execute_graph_traversal`` in
``traversal.py``; this module is intentionally free of any async/IO logic.

Adding a new answer_kind requires only a new registry entry here — no new
handler code.

Each spec describes:
- The primary edges to fetch from the user (or a constrained set of objects)
- An optional "bridge" hop (e.g. presence → person identity, place → parent
  place). These fields are retained so a future consumer (UI identity chip,
  projection layer) can opt into bridge resolution.  The traversal executor
  itself does not perform bridge resolution; Phase 5's ``entity_catalog``
  canonical-name resolution supersedes the previous ``_resolved_identity``
  sidecar (which had no production reader).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
