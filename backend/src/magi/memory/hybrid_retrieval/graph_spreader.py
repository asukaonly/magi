"""Graph spreading activation over L2 knowledge graph edges.

Performs BFS from seed entities, traversing ``knowledge_graph`` edges
up to a configurable depth, and collects both discovered entities and
the L1 evidence event IDs embedded in each edge.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class SpreadingResult:
    """Outcome of a graph spreading activation pass."""

    # event_id → cumulative activation score from all paths that touched it
    scored_event_ids: Dict[str, float] = field(default_factory=dict)
    # entity_id → cumulative activation score
    discovered_entities: Dict[str, float] = field(default_factory=dict)
    hops_executed: int = 0
    edges_traversed: int = 0


class GraphSpreader:
    """BFS spreading activation over the L2 knowledge graph.

    Starting from a set of seed entity IDs, the spreader traverses edges
    in ``knowledge_graph`` (via the L2 cognition store) recording:

    * **discovered entities** reachable within *max_hops*, scored by
      accumulated activation that decays per hop.
    * **evidence event_ids** extracted from ``evidence_event_ids`` on
      each traversed edge, scored by the activation of the edge that
      surfaced them.

    The ``scored_event_ids`` in the result can be used directly as a
    ranked list for RRF fusion in L1Handler.
    """

    def __init__(
        self,
        l2_store: Any,
        *,
        max_hops: int = 2,
        max_neighbors_per_node: int = 10,
        max_total_entities: int = 50,
        decay: float = 0.5,
    ) -> None:
        self._store = l2_store
        self._max_hops = max_hops
        self._max_neighbors = max_neighbors_per_node
        self._max_entities = max_total_entities
        self._decay = decay

    async def spread(
        self,
        seed_entity_ids: List[str],
        *,
        exclude_event_ids: Optional[Set[str]] = None,
    ) -> SpreadingResult:
        """Run BFS spreading from *seed_entity_ids*.

        Returns a :class:`SpreadingResult` with scored event IDs and
        discovered entities.
        """
        if not seed_entity_ids or self._store is None:
            return SpreadingResult()

        exclude = exclude_event_ids or set()
        # entity_id → best activation seen so far
        activation: Dict[str, float] = {eid: 1.0 for eid in seed_entity_ids}
        event_scores: Dict[str, float] = {}
        frontier: Set[str] = set(seed_entity_ids)
        visited: Set[str] = set()
        total_edges = 0

        for hop in range(self._max_hops):
            if not frontier:
                break

            batch_ids = list(frontier)
            try:
                batch_rels = await self._store.batch_get_relationships(
                    entity_ids=batch_ids,
                    direction="both",
                    status="active",
                    limit_per_entity=self._max_neighbors,
                )
            except Exception as exc:
                logger.warning("Graph spreading hop %d failed: %s", hop, exc)
                break

            visited.update(frontier)
            next_frontier: Set[str] = set()

            for source_id in batch_ids:
                edges = batch_rels.get(source_id, [])
                source_activation = activation.get(source_id, 0.0)
                hop_decay = self._decay ** (hop + 1)

                for edge in edges:
                    total_edges += 1
                    confidence = float(edge.get("confidence") or 0.5)
                    obs_count = int(edge.get("observation_count") or 1)
                    edge_weight = confidence * math.log1p(obs_count)

                    # Determine the neighbor entity
                    subject_id = edge.get("subject_id", "")
                    object_id = edge.get("object_id", "")
                    neighbor_id = object_id if subject_id == source_id else subject_id

                    # Accumulate activation on neighbor
                    neighbor_score = source_activation * hop_decay * edge_weight
                    activation[neighbor_id] = activation.get(neighbor_id, 0.0) + neighbor_score

                    if neighbor_id not in visited and len(activation) < self._max_entities:
                        next_frontier.add(neighbor_id)

                    # Collect evidence event IDs from the edge
                    evidence_raw = edge.get("evidence_event_ids")
                    evidence_ids = _parse_evidence_ids(evidence_raw)
                    for eid in evidence_ids:
                        if eid not in exclude:
                            event_scores[eid] = event_scores.get(eid, 0.0) + neighbor_score

            frontier = next_frontier

        # Build result excluding seed entities from discovered set
        seed_set = set(seed_entity_ids)
        discovered = {
            eid: score
            for eid, score in activation.items()
            if eid not in seed_set
        }

        return SpreadingResult(
            scored_event_ids=event_scores,
            discovered_entities=discovered,
            hops_executed=min(self._max_hops, len(visited)),
            edges_traversed=total_edges,
        )


def _parse_evidence_ids(raw: Any) -> List[str]:
    """Parse evidence_event_ids which may be a JSON string or a list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Malformed evidence_event_ids value: %r", raw[:200] if len(raw) > 200 else raw)
    return []
