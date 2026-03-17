"""Layer handlers for hybrid memory retrieval.

Each handler wraps the corresponding memory store and executes
queries based on structured LayerQueryPlan conditions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    TimeRange,
)

logger = logging.getLogger(__name__)


class L1Handler:
    """Execute L1 event store queries from structured conditions."""

    def __init__(self, l1_store: Any) -> None:
        self._store = l1_store

    async def execute(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query L1 events using vector search + optional time/source/domain filters."""
        if not conditions.content_query:
            return []

        # Primary: vector search via search_events
        results = await self._store.search_events(
            query=conditions.content_query,
            session_id=session_id,
            user_id=user_id,
            event_type=conditions.event_types[0] if conditions.event_types else None,
            source_filters=conditions.source_filters,
            domain_filters=conditions.domain_filters,
            limit=conditions.limit,
        )

        # Apply time_range post-filter if present
        if time_range and results:
            results = self._filter_by_time(results, time_range)

        return results

    @staticmethod
    def _filter_by_time(
        results: List[Dict[str, Any]],
        time_range: TimeRange,
    ) -> List[Dict[str, Any]]:
        """Post-filter results by time range."""
        filtered = []
        for r in results:
            ts = r.get("timestamp") or r.get("created_at")
            if ts is None:
                filtered.append(r)
                continue
            if time_range.start and ts < time_range.start:
                continue
            if time_range.end and ts > time_range.end:
                continue
            filtered.append(r)
        return filtered


class L2Handler:
    """Execute L2 knowledge graph queries from structured conditions."""

    def __init__(self, l2_store: Any) -> None:
        self._store = l2_store

    async def execute(
        self,
        conditions: L2Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> Dict[str, Any]:
        """Query L2 for entity cards and relationships."""
        results: Dict[str, Any] = {"entity_cards": [], "relationships": []}

        if conditions.include_tom_snapshot and conditions.entities:
            for entity in conditions.entities:
                snapshot = await self._store.get_tom_snapshot(
                    entity_id=entity,
                    entity_type="user",
                )
                if snapshot:
                    results["entity_cards"].append(snapshot)

        if conditions.include_relationships:
            if conditions.entities:
                for entity in conditions.entities:
                    rels = await self._store.get_relationships(
                        subject_id=entity,
                        limit=conditions.limit,
                    )
                    results["relationships"].extend(rels)
            else:
                rels = await self._store.get_relationships(limit=conditions.limit)
                results["relationships"] = rels

        return results


class L3Handler:
    """Execute L3 summary store queries from structured conditions."""

    def __init__(self, l3_store: Any) -> None:
        self._store = l3_store

    async def execute(
        self,
        conditions: L3Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L3 summaries using existing search_summaries."""
        if not conditions.content_query:
            return []

        summary_type = conditions.summary_types[0] if conditions.summary_types else None

        results = await self._store.search_summaries(
            query=conditions.content_query,
            summary_type=summary_type,
            limit=conditions.limit,
        )

        return results


class L4Handler:
    """Execute L4 procedural memory queries from structured conditions."""

    def __init__(self, l4_store: Any) -> None:
        self._store = l4_store

    async def execute(
        self,
        conditions: L4Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L4 strategies using existing query_strategies."""
        if not conditions.content_query:
            return []

        return await self._store.query_strategies(
            query=conditions.content_query,
            limit=conditions.limit,
        )


async def execute_plan(
    plan: LayerQueryPlan,
    *,
    l1: Optional[L1Handler] = None,
    l2: Optional[L2Handler] = None,
    l3: Optional[L3Handler] = None,
    l4: Optional[L4Handler] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Any:
    """Dispatch a single LayerQueryPlan to the appropriate handler."""
    time_range = plan.time_range

    if plan.layer == "L1" and l1 is not None:
        assert isinstance(plan.conditions, L1Conditions)
        return await l1.execute(plan.conditions, time_range, session_id=session_id, user_id=user_id)
    elif plan.layer == "L2" and l2 is not None:
        assert isinstance(plan.conditions, L2Conditions)
        return await l2.execute(plan.conditions, time_range)
    elif plan.layer == "L3" and l3 is not None:
        assert isinstance(plan.conditions, L3Conditions)
        return await l3.execute(plan.conditions, time_range)
    elif plan.layer == "L4" and l4 is not None:
        assert isinstance(plan.conditions, L4Conditions)
        return await l4.execute(plan.conditions, time_range)
    else:
        logger.warning("No handler available for layer %s", plan.layer)
        return [] if plan.layer != "L2" else {"entity_cards": [], "relationships": []}
