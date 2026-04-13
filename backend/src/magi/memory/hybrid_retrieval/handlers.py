"""Layer handlers for hybrid memory retrieval.

Each handler wraps the corresponding memory store and executes
queries based on structured LayerQueryPlan conditions.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .answerability import (
    extract_query_tokens,
    extract_quoted_spans,
)
from .models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    RetrievalConfig,
    TimeRange,
)
from .l2_handler import L2Handler
from .reranker import build_retrieval_reranker

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


# ---------------------------------------------------------------------------
# Abstract base for BM25 + vector + keyword → RRF fusion handlers
# ---------------------------------------------------------------------------


class RRFSearchHandler(abc.ABC):
    """Template for handlers that fuse BM25, vector, and keyword paths via RRF.

    Subclasses override the three search paths and the hydration step.
    """

    layer_name: str = "?"

    def __init__(self, store: Any, config: Optional[RetrievalConfig] = None) -> None:
        self._store = store
        self._config = config or RetrievalConfig()
        self._reranker = build_retrieval_reranker(self._config)

    async def _rrf_execute(
        self,
        *,
        content_query: str,
        limit: int,
        bm25_coro,
        vector_coro,
        keyword_coro,
        hydrate_coro_fn,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Shared RRF fusion skeleton used by all subclasses."""
        if not content_query:
            return []

        cfg = self._config
        fetch_k = max(limit * cfg.rrf_over_fetch_multiplier, cfg.rrf_over_fetch_minimum)

        results_or_errors = await asyncio.gather(
            bm25_coro, vector_coro, keyword_coro, return_exceptions=True,
        )

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("%s search path %d failed: %s", self.layer_name, i, res)

        if not bm25_ids and not vec_ids and not kw_ids:
            return []

        cfg = self._config
        fused = rrf_fuse(
            [bm25_ids, vec_ids, kw_ids],
            [cfg.rrf_weight_bm25, cfg.rrf_weight_vector, cfg.rrf_weight_keyword],
            k=cfg.rrf_k,
        )

        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []

        results = await hydrate_coro_fn(top_ids)

        if time_range and results:
            results = self._filter_by_time(results, time_range)

        reranked = await self._reranker.rerank(
            layer=self.layer_name,
            results=results,
            query=content_query,
            fused_scores=dict(fused),
        )
        return reranked[:limit]

    @staticmethod
    def _filter_by_time(
        results: List[Dict[str, Any]],
        time_range: TimeRange,
    ) -> List[Dict[str, Any]]:
        """Default time-range filter using timestamp/created_at."""
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

class L1Handler(RRFSearchHandler):
    """Execute L1 event store queries with triple-path RRF fusion."""

    layer_name = "L1"

    def __init__(
        self,
        l1_store: Any,
        config: Optional[RetrievalConfig] = None,
        *,
        l2_store: Any = None,
    ) -> None:
        super().__init__(l1_store, config)
        self._l2_store = l2_store

    async def execute(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query L1 using BM25 + vector + keyword + entity expansion, fused via RRF."""
        if not conditions.content_query:
            return []
        cfg = self._config
        fetch_k = max(conditions.limit * cfg.rrf_over_fetch_multiplier, cfg.rrf_over_fetch_minimum)

        # Phase 1+2: Collect ranked candidate lists from all retrieval paths
        ranked_lists, weights = await self._collect_candidate_lists(
            conditions, time_range, fetch_k, session_id=session_id, user_id=user_id,
        )
        if not any(ids for ids in ranked_lists):
            return []

        # Phase 3: N-way RRF fusion
        fused = rrf_fuse(ranked_lists, weights, k=cfg.rrf_k)
        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []
        logger.debug(
            "L1 RRF fusion completed | top_ids_count=%d top_ids_sample=%s",
            len(top_ids), top_ids[:5],
        )

        # Phase 4: Hydrate, filter, rerank
        return await self._hydrate_and_rerank(
            top_ids, fused, conditions, time_range,
            session_id=session_id, user_id=user_id,
        )

    async def _collect_candidate_lists(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        fetch_k: int,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Sequence[str]], List[float]]:
        """Run all retrieval paths and return (ranked_lists, weights) for RRF fusion."""
        cfg = self._config

        retrieval_coros = [
            self._bm25_path(conditions.content_query, fetch_k, user_id=user_id),
            self._vector_path(conditions.content_query, fetch_k, user_id=user_id),
            self._keyword_path(conditions, fetch_k, session_id=session_id, user_id=user_id),
        ]
        has_temporal = time_range is not None and (time_range.start is not None or time_range.end is not None)
        if has_temporal:
            retrieval_coros.append(
                self._temporal_bm25_path(conditions.content_query, fetch_k, time_range, user_id=user_id),
            )

        results_or_errors = await asyncio.gather(*retrieval_coros, return_exceptions=True)

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []
        temporal_bm25_ids: List[str] = []
        if has_temporal:
            temporal_bm25_ids = results_or_errors[3] if isinstance(results_or_errors[3], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L1 search path %d failed: %s", i, res)

        logger.info(
            "L1 retrieval paths completed | content_query=%r user_id=%s "
            "bm25_count=%d vec_count=%d kw_count=%d temporal_bm25_count=%d fetch_k=%d",
            conditions.content_query, user_id,
            len(bm25_ids), len(vec_ids), len(kw_ids), len(temporal_bm25_ids), fetch_k,
        )

        # Entity co-occurrence expansion using top seed IDs
        seed_ids: List[str] = list(dict.fromkeys(
            bm25_ids[:10] + vec_ids[:10] + kw_ids[:10] + temporal_bm25_ids[:10]
        ))
        entity_ids: List[str] = []
        if seed_ids:
            try:
                entity_ids = await self._store.expand_by_entities(seed_ids, limit=fetch_k)
            except Exception as exc:
                logger.warning("L1 entity expansion failed: %s", exc)

        # Graph spreading activation (L2 knowledge graph BFS)
        graph_ids: List[str] = []
        if cfg.graph_spreading_enabled and self._l2_store is not None and seed_ids:
            try:
                graph_ids = await self._graph_spreading_path(seed_ids, fetch_k)
            except Exception as exc:
                logger.warning("L1 graph spreading failed: %s", exc)

        # Assemble ranked lists + weights for RRF
        ranked_lists: List[Sequence[str]] = [bm25_ids, vec_ids, kw_ids]
        weights = [cfg.rrf_weight_bm25, cfg.rrf_weight_vector, cfg.rrf_weight_keyword]
        if entity_ids:
            ranked_lists.append(entity_ids)
            weights.append(cfg.rrf_weight_entity)
        if graph_ids:
            ranked_lists.append(graph_ids)
            weights.append(cfg.rrf_weight_graph)
        if temporal_bm25_ids:
            ranked_lists.append(temporal_bm25_ids)
            weights.append(cfg.rrf_weight_temporal_bm25)

        return ranked_lists, weights

    async def _hydrate_and_rerank(
        self,
        top_ids: List[str],
        fused: List[Tuple[str, float]],
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch full event rows, apply filters, and rerank."""
        results = await self._fetch_and_filter(
            event_ids=top_ids, conditions=conditions, time_range=time_range,
            session_id=session_id, user_id=user_id,
        )

        logger.debug(
            "L1 fetch_and_filter completed | input_count=%d output_count=%d "
            "session_id=%s user_id=%s time_range=%s source_filters=%s domain_filters=%s",
            len(top_ids), len(results),
            session_id, user_id, time_range,
            conditions.source_filters, conditions.domain_filters,
        )

        reranked = await self._reranker.rerank(
            layer=self.layer_name,
            results=results,
            query=conditions.content_query,
            fused_scores=dict(fused),
        )
        final = reranked[:conditions.limit]
        logger.debug(
            "L1 execute returning | reranked_count=%d limit=%d final_count=%d "
            "final_event_ids=%s",
            len(reranked), conditions.limit, len(final),
            [e.get("event_id") for e in final[:5]],
        )
        return final

    async def _graph_spreading_path(self, seed_event_ids: List[str], limit: int) -> List[str]:
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

        # Resolve seed event_ids → entity_ids via l1_event_entities
        seed_entity_ids: List[str] = []
        try:
            ph = ", ".join("?" for _ in seed_event_ids)
            async with sqlite_connection_async(self._store.db_path) as db:
                async with db.execute(
                    f"SELECT DISTINCT entity_id FROM l1_event_entities WHERE event_id IN ({ph})",
                    tuple(seed_event_ids),
                ) as cursor:
                    seed_entity_ids = [row[0] for row in await cursor.fetchall()]
        except Exception as exc:
            logger.warning("Graph spreading seed resolution failed: %s", exc)
            return []

        if not seed_entity_ids:
            return []

        result = await spreader.spread(
            seed_entity_ids,
            exclude_event_ids=set(seed_event_ids),
        )

        if not result.scored_event_ids:
            # Fall back to discovered entities → l1_event_entities lookup
            if result.discovered_entities:
                try:
                    top_entities = sorted(
                        result.discovered_entities.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:20]
                    entity_ids_to_lookup = [eid for eid, _ in top_entities]
                    eph = ", ".join("?" for _ in entity_ids_to_lookup)
                    async with sqlite_connection_async(self._store.db_path) as db:
                        async with db.execute(
                            f"SELECT event_id, COUNT(DISTINCT entity_id) AS shared"
                            f" FROM l1_event_entities"
                            f" WHERE entity_id IN ({eph})"
                            f" GROUP BY event_id"
                            f" ORDER BY shared DESC"
                            f" LIMIT ?",
                            (*entity_ids_to_lookup, limit),
                        ) as cursor:
                            rows = await cursor.fetchall()
                    exclude = set(seed_event_ids)
                    return [r[0] for r in rows if r[0] not in exclude][:limit]
                except Exception as exc:
                    logger.warning("Graph spreading entity→event lookup failed: %s", exc)
            return []

        # Sort by activation score descending
        scored = sorted(result.scored_event_ids.items(), key=lambda x: x[1], reverse=True)
        return [eid for eid, _ in scored[:limit]]

    async def _bm25_path(self, query: str, limit: int, *, user_id: Optional[str] = None) -> List[str]:
        """BM25 search via FTS5, optionally scoped to *user_id*."""
        try:
            hits = await self._store.bm25_search(query, limit=limit, user_id=user_id)
            return [event_id for event_id, _score in hits]
        except Exception as exc:
            logger.warning("BM25 path failed: %s", exc)
            return []

    async def _temporal_bm25_path(
        self,
        query: str,
        limit: int,
        time_range: TimeRange,
        *,
        user_id: Optional[str] = None,
    ) -> List[str]:
        """Time-constrained BM25 search to boost recall for temporal queries.

        Uses strict matching (exact tokens first, no OR fallback) to avoid
        noise from short prefix stems flooding RRF fusion.
        """
        try:
            hits = await self._store.bm25_search(
                query,
                limit=limit,
                user_id=user_id,
                start_time=time_range.start,
                end_time=time_range.end,
                strict=True,
            )
            return [event_id for event_id, _score in hits]
        except Exception as exc:
            logger.warning("Temporal BM25 path failed: %s", exc)
            return []

    async def _vector_path(self, query: str, limit: int, *, user_id: Optional[str] = None) -> List[str]:
        """Vector similarity search via sqlite-vec.

        Resolves chunk-level entity IDs returned by the vector index back to
        event IDs.  When *user_id* is provided, only events belonging to that
        user are returned (via a post-filter against ``fact_events``).
        """
        try:
            # Over-fetch when user_id filtering will discard cross-namespace hits
            vec_limit = limit * 10 if user_id else limit
            hits = await self._store._semantic_search_event_hits(query=query, limit=vec_limit)
            if not hits:
                return []

            # Resolve chunk_ids (e.g. "evt_xxx::chunk-0") → event_ids ("evt_xxx")
            seen: set[str] = set()
            event_ids: List[str] = []
            for hit in hits:
                eid = hit.entity_id.split("::")[0] if "::" in hit.entity_id else hit.entity_id
                if eid not in seen:
                    seen.add(eid)
                    event_ids.append(eid)

            if user_id and event_ids:
                event_ids = await self._filter_ids_by_user(event_ids, user_id)

            return event_ids
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
                query=conditions.content_query or None,
                limit=limit,
            )
            quoted_phrases = extract_quoted_spans(conditions.content_query)
            if quoted_phrases:
                matched_scored: list[tuple[int, str]] = []
                for event in events:
                    normalized_content = " ".join(extract_query_tokens(event.get("content", "")))
                    quote_hits = sum(1 for phrase in quoted_phrases if phrase and phrase in normalized_content)
                    if quote_hits > 0:
                        matched_scored.append((quote_hits, str(event.get("event_id") or "")))
                matched_scored.sort(key=lambda item: item[0], reverse=True)
                return [event_id for _, event_id in matched_scored if event_id]

            query_tokens = [t for t in conditions.content_query.lower().split() if t]
            matched = [
                e["event_id"]
                for e in events
                if all(tok in e.get("content", "").lower() for tok in query_tokens)
            ]
            return matched
        except Exception as exc:
            logger.warning("Keyword path failed: %s", exc)
            return []

    async def _filter_ids_by_user(self, event_ids: List[str], user_id: str) -> List[str]:
        """Return the subset of *event_ids* that belong to *user_id*."""
        if not event_ids:
            return []
        placeholders = ", ".join("?" for _ in event_ids)
        query = (
            f"SELECT event_id FROM fact_events"
            f" WHERE event_id IN ({placeholders}) AND user_id = ? AND deleted_at IS NULL"
        )
        args = [*event_ids, user_id]
        async with sqlite_connection_async(self._store.db_path) as db:
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        valid = {str(row[0]) for row in rows}
        return [eid for eid in event_ids if eid in valid]

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

        # Temporal pre-filter: push time_range into SQL to avoid
        # wasting hydration slots on out-of-range events.
        if time_range:
            if time_range.start is not None:
                query += " AND timestamp >= ?"
                args.append(time_range.start)
            if time_range.end is not None:
                query += " AND timestamp <= ?"
                args.append(time_range.end)

        async with sqlite_connection_async(self._store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        events_by_id = {str(row["event_id"]): self._store._row_to_dict(row) for row in rows}

        # Preserve RRF rank ordering
        results = [events_by_id[eid] for eid in event_ids if eid in events_by_id]

        # Time range is already enforced via SQL WHERE clauses above;
        # no redundant Python post-filter needed.
        return results

class L3Handler(RRFSearchHandler):
    """Execute L3 summary store queries with triple-path RRF fusion."""

    layer_name = "L3"

    def __init__(self, l3_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        super().__init__(l3_store, config)

    async def execute(
        self,
        conditions: L3Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L3 using BM25 + vector + keyword, fused via RRF."""
        if not conditions.content_query:
            return []
        summary_type = conditions.summary_types[0] if conditions.summary_types else None
        summary_category = conditions.summary_categories[0] if conditions.summary_categories else None
        cfg = self._config
        fetch_k = max(conditions.limit * cfg.rrf_over_fetch_multiplier, cfg.rrf_over_fetch_minimum)
        return await self._rrf_execute(
            content_query=conditions.content_query,
            limit=conditions.limit,
            bm25_coro=self._bm25_path(conditions.content_query, summary_type, summary_category, fetch_k),
            vector_coro=self._vector_path(conditions.content_query, summary_type, summary_category, fetch_k),
            keyword_coro=self._keyword_path(conditions.content_query, summary_type, summary_category, fetch_k),
            hydrate_coro_fn=lambda ids: self._fetch_by_ids(ids, summary_type, summary_category),
            time_range=time_range,
        )

    async def _bm25_path(
        self,
        query: str,
        summary_type: Optional[str],
        summary_category: Optional[str],
        limit: int,
    ) -> List[str]:
        try:
            hits = await self._store.bm25_search(
                query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=limit,
            )
            return [sid for sid, _score in hits]
        except Exception as exc:
            logger.warning("L3 BM25 path failed: %s", exc)
            return []

    async def _vector_path(
        self,
        query: str,
        summary_type: Optional[str],
        summary_category: Optional[str],
        limit: int,
    ) -> List[str]:
        try:
            results = await self._store._semantic_search_summaries(
                query=query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=limit,
            )
            return [r["summary_id"] for r in results]
        except Exception as exc:
            logger.warning("L3 vector path failed: %s", exc)
            return []

    async def _keyword_path(
        self,
        query: str,
        summary_type: Optional[str],
        summary_category: Optional[str],
        limit: int,
    ) -> List[str]:
        try:
            sql = "SELECT summary_id FROM summaries WHERE content LIKE ? ESCAPE '\\'"
            escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args: list[Any] = [f"%{escaped_query}%"]
            if summary_type:
                sql += " AND summary_type = ?"
                args.append(summary_type)
            if summary_category:
                sql += " AND summary_category = ?"
                args.append(summary_category)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            args.append(limit)
            async with sqlite_connection_async(self._store.db_path) as db:
                async with db.execute(sql, tuple(args)) as cursor:
                    rows = await cursor.fetchall()
            return [str(row[0]) for row in rows]
        except Exception as exc:
            logger.warning("L3 keyword path failed: %s", exc)
            return []

    async def _fetch_by_ids(
        self,
        summary_ids: List[str],
        summary_type: Optional[str],
        summary_category: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not summary_ids:
            return []

        placeholders = ", ".join("?" for _ in summary_ids)
        sql = f"SELECT * FROM summaries WHERE summary_id IN ({placeholders})"
        args: list[Any] = list(summary_ids)
        if summary_type:
            sql += " AND summary_type = ?"
            args.append(summary_type)
        if summary_category:
            sql += " AND summary_category = ?"
            args.append(summary_category)
        async with sqlite_connection_async(self._store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        by_id = {str(row["summary_id"]): self._store._row_to_dict(row) for row in rows}
        return [by_id[sid] for sid in summary_ids if sid in by_id]

    @staticmethod
    def _filter_by_time(results: List[Dict[str, Any]], time_range: TimeRange) -> List[Dict[str, Any]]:
        filtered = []
        for r in results:
            if time_range.start and r.get("period_end", 0) < time_range.start:
                continue
            if time_range.end and r.get("period_start", float("inf")) > time_range.end:
                continue
            filtered.append(r)
        return filtered


class L4Handler(RRFSearchHandler):
    """Execute L4 procedural memory queries with triple-path RRF fusion."""

    layer_name = "L4"

    def __init__(self, l4_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        super().__init__(l4_store, config)

    async def execute(
        self,
        conditions: L4Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L4 using BM25 + vector + keyword, fused via RRF."""
        if not conditions.content_query:
            return []
        cfg = self._config
        fetch_k = max(conditions.limit * cfg.rrf_over_fetch_multiplier, cfg.rrf_over_fetch_minimum)
        return await self._rrf_execute(
            content_query=conditions.content_query,
            limit=conditions.limit,
            bm25_coro=self._bm25_path(conditions.content_query, fetch_k),
            vector_coro=self._vector_path(conditions.content_query, fetch_k),
            keyword_coro=self._keyword_path(conditions.content_query, fetch_k),
            hydrate_coro_fn=self._fetch_by_ids,
        )

    async def _bm25_path(self, query: str, limit: int) -> List[str]:
        try:
            hits = await self._store.bm25_search(query, limit=limit)
            return [sid for sid, _score in hits]
        except Exception as exc:
            logger.warning("L4 BM25 path failed: %s", exc)
            return []

    async def _vector_path(self, query: str, limit: int) -> List[str]:
        try:
            results = await self._store._semantic_query_strategies(query=query, limit=limit)
            return [r["skill_id"] for r in results]
        except Exception as exc:
            logger.warning("L4 vector path failed: %s", exc)
            return []

    async def _keyword_path(self, query: str, limit: int) -> List[str]:
        try:
            escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like_query = f"%{escaped_query}%"
            async with sqlite_connection_async(self._store.db_path) as db:
                async with db.execute(
                    """
                    SELECT skill_id FROM procedural_skills
                    WHERE skill_name LIKE ? ESCAPE '\\' OR COALESCE(optimized_prompt, '') LIKE ? ESCAPE '\\'
                    ORDER BY success_rate DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (like_query, like_query, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [str(row[0]) for row in rows]
        except Exception as exc:
            logger.warning("L4 keyword path failed: %s", exc)
            return []

    async def _fetch_by_ids(self, skill_ids: List[str]) -> List[Dict[str, Any]]:
        if not skill_ids:
            return []

        placeholders = ", ".join("?" for _ in skill_ids)
        async with sqlite_connection_async(self._store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM procedural_skills WHERE skill_id IN ({placeholders})",
                tuple(skill_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        by_id = {str(row["skill_id"]): self._store._row_to_dict(row) for row in rows}
        return [by_id[sid] for sid in skill_ids if sid in by_id]


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
        return await l2.execute(plan.conditions, time_range, user_id=user_id)
    elif plan.layer == "L3" and l3 is not None:
        assert isinstance(plan.conditions, L3Conditions)
        return await l3.execute(plan.conditions, time_range)
    elif plan.layer == "L4" and l4 is not None:
        assert isinstance(plan.conditions, L4Conditions)
        return await l4.execute(plan.conditions, time_range)
    else:
        logger.warning("No handler available for layer %s", plan.layer)
        return [] if plan.layer != "L2" else {"entity_cards": [], "relationships": []}
