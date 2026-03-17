"""Layer handlers for hybrid memory retrieval.

Each handler wraps the corresponding memory store and executes
queries based on structured LayerQueryPlan conditions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    RetrievalConfig,
    TimeRange,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RRF fusion utility
# ---------------------------------------------------------------------------


def rrf_fuse(
    ranked_lists: Sequence[Sequence[str]],
    weights: Sequence[float],
    k: int = 60,
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion over multiple ranked ID lists.

    score(d) = Σ w_r / (k + rank_r(d))

    where rank_r(d) is 1-based position in ranked list r.

    Returns (id, score) pairs sorted by descending score.
    """
    scores: Dict[str, float] = {}
    for ranked_ids, weight in zip(ranked_lists, weights):
        for rank_1based, doc_id in enumerate(ranked_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank_1based)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class L1Handler:
    """Execute L1 event store queries with triple-path RRF fusion."""

    def __init__(self, l1_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        self._store = l1_store
        self._config = config or RetrievalConfig()

    async def execute(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query L1 using BM25 + vector + keyword, fused via RRF."""
        if not conditions.content_query:
            return []

        fetch_k = max(conditions.limit * 5, 20)

        # Three concurrent search paths
        bm25_task = asyncio.ensure_future(self._bm25_path(conditions.content_query, fetch_k))
        vec_task = asyncio.ensure_future(self._vector_path(conditions.content_query, fetch_k))
        kw_task = asyncio.ensure_future(self._keyword_path(conditions, fetch_k, session_id=session_id, user_id=user_id))

        results_or_errors = await asyncio.gather(bm25_task, vec_task, kw_task, return_exceptions=True)

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L1 search path %d failed: %s", i, res)

        if not bm25_ids and not vec_ids and not kw_ids:
            return []

        # RRF fusion
        cfg = self._config
        fused = rrf_fuse(
            [bm25_ids, vec_ids, kw_ids],
            [cfg.rrf_weight_bm25, cfg.rrf_weight_vector, cfg.rrf_weight_keyword],
            k=cfg.rrf_k,
        )

        # Take top IDs up to fetch_k for hydration
        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []

        # Hydrate full events and apply filters
        results = await self._fetch_and_filter(
            event_ids=top_ids,
            conditions=conditions,
            time_range=time_range,
            session_id=session_id,
            user_id=user_id,
        )

        return results[:conditions.limit]

    async def _bm25_path(self, query: str, limit: int) -> List[str]:
        """BM25 search via FTS5."""
        try:
            hits = await self._store.bm25_search(query, limit=limit)
            return [event_id for event_id, _score in hits]
        except Exception as exc:
            logger.warning("BM25 path failed: %s", exc)
            return []

    async def _vector_path(self, query: str, limit: int) -> List[str]:
        """Vector similarity search via sqlite-vec."""
        try:
            hits = await self._store._semantic_search_event_hits(query=query, limit=limit)
            return [hit.entity_id for hit in hits]
        except Exception as exc:
            logger.warning("Vector path failed: %s", exc)
            return []

    async def _keyword_path(
        self,
        conditions: L1Conditions,
        limit: int,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[str]:
        """SQL LIKE keyword search via query_events + in-memory token filtering."""
        try:
            events = await self._store.query_events(
                session_id=session_id,
                user_id=user_id,
                event_type=conditions.event_types[0] if conditions.event_types else None,
                source_filters=conditions.source_filters,
                limit=limit,
            )
            query_tokens = [t for t in conditions.content_query.lower().split() if t]
            matched = [
                e["event_id"]
                for e in events
                if all(tok in e.get("raw_content", "").lower() for tok in query_tokens)
            ]
            return matched
        except Exception as exc:
            logger.warning("Keyword path failed: %s", exc)
            return []

    async def _fetch_and_filter(
        self,
        *,
        event_ids: List[str],
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Fetch full event dicts for given IDs and apply post-filters."""
        from ..event_contracts import MemoryDomain

        if not event_ids:
            return []

        import aiosqlite

        query = "SELECT * FROM fact_events WHERE deleted_at IS NULL"
        args: list[Any] = []
        placeholders = ", ".join("?" for _ in event_ids)
        query += f" AND event_id IN ({placeholders})"
        args.extend(event_ids)

        if session_id:
            query += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            args.append(user_id)
        if conditions.event_types:
            et_ph = ", ".join("?" for _ in conditions.event_types)
            query += f" AND event_type IN ({et_ph})"
            args.extend(conditions.event_types)
        if conditions.source_filters:
            sf_ph = ", ".join("?" for _ in conditions.source_filters)
            query += f" AND source IN ({sf_ph})"
            args.extend(conditions.source_filters)
        if conditions.domain_filters:
            domain_ints = []
            for df in conditions.domain_filters:
                try:
                    domain_ints.append(int(MemoryDomain.from_value(df)))
                except (ValueError, KeyError):
                    pass
            if domain_ints:
                df_ph = ", ".join("?" for _ in domain_ints)
                query += f" AND memory_domain IN ({df_ph})"
                args.extend(domain_ints)
        else:
            query += " AND memory_domain != ?"
            args.append(int(MemoryDomain.RUNTIME_TELEMETRY))

        async with aiosqlite.connect(self._store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        events_by_id = {str(row["event_id"]): self._store._row_to_dict(row) for row in rows}

        # Preserve RRF rank ordering
        results = [events_by_id[eid] for eid in event_ids if eid in events_by_id]

        # Time range post-filter
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
