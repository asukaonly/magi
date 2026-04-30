"""L1 retrieval execution orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .handler_base import rrf_fuse
from .models import L1Conditions, TimeRange

logger = logging.getLogger(__name__)


class L1ExecutionMixin:
    """Coordinate L1 retrieval paths, RRF fusion, hydration, and reranking."""

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

        ranked_lists, weights = await self._collect_candidate_lists(
            conditions, time_range, fetch_k, session_id=session_id, user_id=user_id,
        )
        if not any(ids for ids in ranked_lists):
            return []

        fused = rrf_fuse(ranked_lists, weights, k=cfg.rrf_k)
        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []
        logger.debug(
            "L1 RRF fusion completed | top_ids_count=%d top_ids_sample=%s",
            len(top_ids), top_ids[:5],
        )

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

        seed_ids: List[str] = list(dict.fromkeys(
            bm25_ids[:10] + vec_ids[:10] + kw_ids[:10] + temporal_bm25_ids[:10]
        ))
        entity_ids: List[str] = []
        if seed_ids:
            try:
                entity_ids = await self._store.expand_by_entities(seed_ids, limit=fetch_k)
            except Exception as exc:
                logger.warning("L1 entity expansion failed: %s", exc)

        graph_ids: List[str] = []
        if cfg.graph_spreading_enabled and self._l2_store is not None and seed_ids:
            try:
                graph_ids = await self._graph_spreading_path(seed_ids, fetch_k)
            except Exception as exc:
                logger.warning("L1 graph spreading failed: %s", exc)

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
            [event.get("event_id") for event in final[:5]],
        )
        return final


__all__ = ["L1ExecutionMixin"]
