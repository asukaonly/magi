"""L1 graph spreading activation path."""

from __future__ import annotations

import logging
from typing import Any, List, Mapping

from .governed_l2_recall import governed_temporal_bounds
from .models import TimeRange

logger = logging.getLogger(__name__)


class L1GraphSpreadingMixin:
    """Expand L1 event seeds through the L2 knowledge graph."""

    async def _graph_spreading_path(
        self,
        seed_event_ids: List[str],
        limit: int,
        *,
        time_range: TimeRange | None,
        context_scope: Mapping[str, Any] | None,
    ) -> List[str]:
        """Graph spreading activation via L2 knowledge graph BFS."""
        from .graph_spreader import GraphSpreader

        cfg = self._config
        spreader = GraphSpreader(
            self._l2_store,
            max_hops=cfg.graph_spreading_max_hops,
            max_neighbors_per_node=cfg.graph_spreading_max_neighbors,
            max_total_entities=cfg.graph_spreading_max_entities,
            decay=cfg.graph_spreading_decay,
        )

        seed_entity_ids: List[str] = []
        try:
            seed_entity_ids = await self._store.resolve_event_entities(seed_event_ids)
        except Exception as exc:
            logger.warning("Graph spreading seed resolution failed: %s", exc)
            return []

        if not seed_entity_ids:
            return []

        result = await spreader.spread(
            seed_entity_ids,
            exclude_event_ids=set(seed_event_ids),
            context_scope=context_scope,
            temporal_bounds=governed_temporal_bounds(time_range),
        )

        if not result.scored_event_ids:
            if result.discovered_entities:
                try:
                    top_entities = sorted(
                        result.discovered_entities.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:20]
                    entity_ids_to_lookup = [entity_id for entity_id, _ in top_entities]
                    rows = await self._store.find_events_by_entities(
                        entity_ids_to_lookup,
                        exclude_event_ids=seed_event_ids,
                        limit=limit,
                    )
                    return [event_id for event_id, _ in rows]
                except Exception as exc:
                    logger.warning("Graph spreading entity-to-event lookup failed: %s", exc)
            return []

        scored = sorted(result.scored_event_ids.items(), key=lambda x: x[1], reverse=True)
        return [event_id for event_id, _ in scored[:limit]]

__all__ = ["L1GraphSpreadingMixin"]
