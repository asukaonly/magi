"""Layer handlers for hybrid memory retrieval.

Each handler wraps the corresponding memory store and executes
queries based on structured LayerQueryPlan conditions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
from .handler_base import RRFSearchHandler, rrf_fuse
from .l2_handler import L2Handler
from .l3_handler import L3Handler
from .l4_handler import L4Handler
from .protocols import L1StoreProtocol

logger = logging.getLogger(__name__)


class L1Handler(RRFSearchHandler):
    """Execute L1 event store queries with triple-path RRF fusion."""

    layer_name = "L1"

    def __init__(
        self,
        l1_store: L1StoreProtocol,
        config: Optional[RetrievalConfig] = None,
        *,
        l2_store: Any = None,
    ) -> None:
        super().__init__(l1_store, config)
        self._l2_store = l2_store

    def with_config(self, config: RetrievalConfig) -> "L1Handler":
        """Return a new L1Handler sharing stores but with *config*."""
        return L1Handler(self._store, config, l2_store=self._l2_store)

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

        # Resolve seed event_ids → entity_ids
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
        )

        if not result.scored_event_ids:
            # Fall back to discovered entities → event lookup
            if result.discovered_entities:
                try:
                    top_entities = sorted(
                        result.discovered_entities.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:20]
                    entity_ids_to_lookup = [eid for eid, _ in top_entities]
                    rows = await self._store.find_events_by_entities(
                        entity_ids_to_lookup,
                        exclude_event_ids=seed_event_ids,
                        limit=limit,
                    )
                    return [eid for eid, _ in rows]
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
        event IDs.  When *user_id* is provided the sqlite-vec partition key
        filters results at the index level so all returned chunks belong to
        the target user namespace.

        With sentence-level chunking each event produces many chunks (~10),
        so we over-fetch raw chunks and deduplicate by event to maintain
        session diversity.
        """
        try:
            # Over-fetch chunks to ensure enough unique events survive dedup.
            # With ~10 chunks/event, we need ~10x the desired event count.
            chunk_density_multiplier = 10
            vec_limit = limit * chunk_density_multiplier
            hits = await self._store.vector_search(
                query=query, limit=vec_limit, user_id=user_id,
            )
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
        return await self._store.filter_ids_by_user(event_ids, user_id)

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

        return await self._store.fetch_events(
            event_ids,
            session_id=session_id,
            user_id=user_id,
            event_types=conditions.event_types or None,
            source_filters=conditions.source_filters or None,
            domain_filters=conditions.domain_filters or None,
            exclude_domain=MemoryDomain.RUNTIME_TELEMETRY.label if not conditions.domain_filters else None,
            time_start=time_range.start if time_range else None,
            time_end=time_range.end if time_range else None,
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
