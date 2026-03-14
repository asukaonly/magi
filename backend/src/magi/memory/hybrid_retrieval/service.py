"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

from typing import Any, Dict, List

from .models import RetrievalPayload, RetrievalQuery


class HybridRetrievalService:
    """Route a query to the most relevant memory layers."""

    def __init__(self, unified_memory) -> None:
        self._memory = unified_memory

    async def query(self, request: RetrievalQuery) -> RetrievalPayload:
        """Execute a layer-aware retrieval query."""
        payload = RetrievalPayload(
            trace={
                "query_mode": request.query_mode,
                "query": request.query,
                "sources": request.source_filters,
                "domains": request.domain_filters,
            }
        )

        if request.session_id and self._memory.l0 is not None:
            workbench = await self._memory.l0.get_workbench(request.session_id)
            if workbench["session"] is not None:
                payload.l0_workbench = [
                    {
                        "session": workbench["session"],
                        "goals": workbench["goal_stack"][:3],
                        "active_entities": workbench["active_entities"][:5],
                        "temporary_tactics": workbench["temporary_tactics"][:5],
                    }
                ]

        if request.query_mode == "detail":
            payload.l1_events = await self._query_l1(request)
            payload.l2_entity_cards = await self._query_l2_entities(request)
            return payload

        if request.query_mode == "summary":
            payload.l3_reflections = await self._query_l3(request)
            if not payload.l3_reflections:
                payload.l1_events = await self._query_l1(request)
            return payload

        if request.query_mode in {"experience", "strategy"}:
            payload.l4_procedures = await self._query_l4(request)
            if not payload.l4_procedures:
                payload.l1_events = await self._query_l1(request)
            return payload

        if request.query_mode == "graph":
            payload.l2_entity_cards = await self._query_l2_entities(request)
            payload.l2_relationships = await self._query_l2_relationships(request)
            if not payload.l2_relationships:
                payload.l1_events = await self._query_l1(request)
            return payload

        return payload

    async def _query_l1(self, request: RetrievalQuery) -> List[Dict[str, Any]]:
        if self._memory.l1 is None:
            return []
        events = await self._memory.l1.query_events(
            session_id=request.session_id,
            user_id=request.user_id,
            limit=max(request.limit * 5, 20),
        )
        query_tokens = [token for token in request.query.lower().split() if token]
        filtered = [
            event
            for event in events
            if event["memory_domain"] != "runtime_telemetry"
            and all(token in event["raw_content"].lower() for token in query_tokens)
        ]
        return filtered[: request.limit]

    async def _query_l2_entities(self, request: RetrievalQuery) -> List[Dict[str, Any]]:
        if self._memory.l2 is None or not request.user_id:
            return []
        snapshot = await self._memory.l2.get_tom_snapshot(entity_id=f"user:{request.user_id}", entity_type="user")
        return [snapshot] if snapshot else []

    async def _query_l2_relationships(self, request: RetrievalQuery) -> List[Dict[str, Any]]:
        if self._memory.l2 is None:
            return []
        return await self._memory.l2.get_relationships(limit=request.limit)

    async def _query_l3(self, request: RetrievalQuery) -> List[Dict[str, Any]]:
        if self._memory.l3 is None:
            return []
        return await self._memory.l3.search_summaries(query=request.query, limit=request.limit)

    async def _query_l4(self, request: RetrievalQuery) -> List[Dict[str, Any]]:
        if self._memory.l4 is None:
            return []
        return await self._memory.l4.query_strategies(query=request.query, limit=request.limit)
