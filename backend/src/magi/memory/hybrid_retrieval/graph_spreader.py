"""Graph spreading activation over L2 knowledge graph edges.

Performs BFS from seed entities, traversing ``knowledge_graph`` edges
up to a configurable depth, and collects both discovered entities and
the L1 evidence event IDs embedded in each edge.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .governed_l2_recall import (
    GovernedL2RecallView,
    GovernedTemporalBounds,
    governed_temporal_bounds,
)

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


@dataclass
class _SpreadState:
    activation: Dict[str, float]
    event_scores: Dict[str, float]
    frontier: Set[str]
    visited: Set[str] = field(default_factory=set)
    total_edges: int = 0


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
        context_scope: Mapping[str, Any] | None = None,
        temporal_bounds: GovernedTemporalBounds | None = None,
    ) -> SpreadingResult:
        """Run BFS spreading from *seed_entity_ids*.

        Returns a :class:`SpreadingResult` with scored event IDs and
        discovered entities.
        """
        if not seed_entity_ids or self._store is None:
            return SpreadingResult()

        exclude = exclude_event_ids or set()
        state = _SpreadState(
            activation={eid: 1.0 for eid in seed_entity_ids},
            event_scores={},
            frontier=set(seed_entity_ids),
        )
        bounds = temporal_bounds or governed_temporal_bounds(None)
        relationship_store = GovernedL2RecallView(
            self._store,
            context_scope=context_scope,
            effective_at=bounds.effective_at,
            effective_range=bounds.effective_range,
            include_relationship_history=bounds.include_history,
        )

        for hop in range(self._max_hops):
            if not state.frontier:
                break
            if not await self._spread_hop(
                state,
                hop=hop,
                exclude=exclude,
                relationship_store=relationship_store,
            ):
                break

        return self._build_result(seed_entity_ids, state)

    async def _spread_hop(
        self,
        state: _SpreadState,
        *,
        hop: int,
        exclude: Set[str],
        relationship_store: GovernedL2RecallView,
    ) -> bool:
        batch_ids = list(state.frontier)
        batch_rels = await self._load_hop_relationships(
            batch_ids,
            hop,
            relationship_store=relationship_store,
        )
        if batch_rels is None:
            return False

        state.visited.update(state.frontier)
        next_frontier: Set[str] = set()
        hop_decay = self._decay ** (hop + 1)
        for source_id in batch_ids:
            self._spread_source_edges(
                state=state,
                source_id=source_id,
                edges=batch_rels.get(source_id, []),
                hop_decay=hop_decay,
                next_frontier=next_frontier,
                exclude=exclude,
            )
        state.frontier = next_frontier
        return True

    async def _load_hop_relationships(
        self,
        batch_ids: List[str],
        hop: int,
        *,
        relationship_store: GovernedL2RecallView,
    ) -> Dict[str, List[Dict[str, Any]]] | None:
        try:
            return await relationship_store.batch_get_relationships(
                entity_ids=batch_ids,
                direction="both",
                status="active",
                limit_per_entity=self._max_neighbors,
            )
        except Exception as exc:
            logger.warning("Graph spreading hop %d failed: %s", hop, exc)
            return None

    def _spread_source_edges(
        self,
        *,
        state: _SpreadState,
        source_id: str,
        edges: List[Dict[str, Any]],
        hop_decay: float,
        next_frontier: Set[str],
        exclude: Set[str],
    ) -> None:
        source_activation = state.activation.get(source_id, 0.0)
        for edge in edges:
            self._spread_edge(
                state=state,
                source_id=source_id,
                source_activation=source_activation,
                hop_decay=hop_decay,
                edge=edge,
                next_frontier=next_frontier,
                exclude=exclude,
            )

    def _spread_edge(
        self,
        *,
        state: _SpreadState,
        source_id: str,
        source_activation: float,
        hop_decay: float,
        edge: Dict[str, Any],
        next_frontier: Set[str],
        exclude: Set[str],
    ) -> None:
        state.total_edges += 1
        neighbor_id = self._neighbor_entity_id(source_id, edge)
        neighbor_score = source_activation * hop_decay * _edge_weight(edge)
        state.activation[neighbor_id] = state.activation.get(neighbor_id, 0.0) + neighbor_score
        if neighbor_id not in state.visited and len(state.activation) < self._max_entities:
            next_frontier.add(neighbor_id)
        self._collect_edge_evidence_scores(
            edge=edge,
            event_scores=state.event_scores,
            neighbor_score=neighbor_score,
            exclude=exclude,
        )

    def _neighbor_entity_id(self, source_id: str, edge: Dict[str, Any]) -> str:
        subject_id = edge.get("subject_id", "")
        object_id = edge.get("object_id", "")
        return object_id if subject_id == source_id else subject_id

    def _collect_edge_evidence_scores(
        self,
        *,
        edge: Dict[str, Any],
        event_scores: Dict[str, float],
        neighbor_score: float,
        exclude: Set[str],
    ) -> None:
        for event_id in _parse_evidence_ids(edge.get("evidence_event_ids")):
            if event_id not in exclude:
                event_scores[event_id] = event_scores.get(event_id, 0.0) + neighbor_score

    def _build_result(
        self,
        seed_entity_ids: List[str],
        state: _SpreadState,
    ) -> SpreadingResult:
        seed_set = set(seed_entity_ids)
        discovered = {eid: score for eid, score in state.activation.items() if eid not in seed_set}

        return SpreadingResult(
            scored_event_ids=state.event_scores,
            discovered_entities=discovered,
            hops_executed=min(self._max_hops, len(state.visited)),
            edges_traversed=state.total_edges,
        )


def _edge_weight(edge: Dict[str, Any]) -> float:
    confidence = float(edge.get("confidence") or 0.5)
    obs_count = int(edge.get("observation_count") or 1)
    return confidence * math.log1p(obs_count)


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
            logger.warning(
                "Malformed evidence_event_ids value: %r", raw[:200] if len(raw) > 200 else raw
            )
    return []
