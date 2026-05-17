"""L3 summary retrieval handler."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .handler_base import RRFSearchHandler
from .models import L3Conditions, RetrievalConfig, TimeRange
from .protocols import L3StoreProtocol

logger = logging.getLogger(__name__)


class L3Handler(RRFSearchHandler):
    """Execute L3 summary store queries with triple-path RRF fusion."""

    layer_name = "L3"

    def __init__(self, l3_store: L3StoreProtocol, config: Optional[RetrievalConfig] = None) -> None:
        super().__init__(l3_store, config)

    async def execute(
        self,
        conditions: L3Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L3 using BM25 + vector + keyword, fused via RRF.

        ``summary_type`` is still applied as a hard filter — types are a
        narrow controlled vocabulary the host owns and a wrong value
        almost certainly means the caller asked for a different store
        shape. ``summary_category`` is applied as a *soft* preference:
        the chat LLM may pick an imperfect category for a query, so we
        retrieve broadly and then boost matching items during reranking.
        This keeps recall intact when the LLM mis-classifies.
        """
        if not conditions.content_query:
            return []
        summary_type = conditions.summary_types[0] if conditions.summary_types else None
        summary_category = conditions.summary_categories[0] if conditions.summary_categories else None
        cfg = self._config

        fetch_k = max(conditions.limit * cfg.rrf_over_fetch_multiplier, cfg.rrf_over_fetch_minimum)
        adjuster: Optional[Callable[[List[Dict[str, Any]], Dict[str, float]], Dict[str, float]]] = None
        fetch_k_multiplier = 1.0
        if summary_category:
            adjuster = self._build_category_booster(
                summary_category, cfg.l3_category_soft_boost
            )
            fetch_k_multiplier = cfg.l3_category_fetch_k_multiplier
        return await self._rrf_execute(
            content_query=conditions.content_query,
            limit=conditions.limit,
            bm25_coro=self._bm25_path(conditions.content_query, summary_type, None, fetch_k),
            vector_coro=self._vector_path(conditions.content_query, summary_type, None, fetch_k),
            keyword_coro=self._keyword_path(conditions.content_query, summary_type, None, fetch_k),
            hydrate_coro_fn=lambda ids: self._fetch_by_ids(ids, summary_type, None),
            time_range=time_range,
            fetch_k_multiplier=fetch_k_multiplier,
            fused_score_adjuster=adjuster,
        )

    @staticmethod
    def _build_category_booster(
        requested_category: str,
        boost_factor: float,
    ) -> Callable[[List[Dict[str, Any]], Dict[str, float]], Dict[str, float]]:
        """Return an adjuster that multiplies fused score for category matches.

        Why not pre-filter? When the chat LLM mis-classifies (e.g. picks
        ``browser_activity`` for a gaming query), a hard WHERE filter
        zeros out the entire L3 path and forces a noisier L1 fallback.
        A multiplicative boost keeps every candidate visible to the
        reranker while still moving correct-category matches up.
        """

        target = str(requested_category)
        scale = max(boost_factor, 1.0)

        def adjust(
            results: List[Dict[str, Any]],
            scores: Dict[str, float],
        ) -> Dict[str, float]:
            if scale == 1.0 or not target:
                return scores
            adjusted = dict(scores)
            for item in results:
                category = str(item.get("summary_category") or "")
                if category != target:
                    continue
                summary_id = str(item.get("summary_id") or "")
                if summary_id and summary_id in adjusted:
                    adjusted[summary_id] = adjusted[summary_id] * scale
            return adjusted

        return adjust

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
            results = await self._store.vector_search(
                query=query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=limit,
            )
            return [result["summary_id"] for result in results]
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
            return await self._store.keyword_search(
                query=query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("L3 keyword path failed: %s", exc)
            return []

    async def _fetch_by_ids(
        self,
        summary_ids: List[str],
        summary_type: Optional[str],
        summary_category: Optional[str],
    ) -> List[Dict[str, Any]]:
        return await self._store.fetch_by_ids(
            summary_ids,
            summary_type=summary_type,
            summary_category=summary_category,
        )

    @staticmethod
    def _filter_by_time(results: List[Dict[str, Any]], time_range: TimeRange) -> List[Dict[str, Any]]:
        filtered = []
        for result in results:
            if time_range.start and result.get("period_end", 0) < time_range.start:
                continue
            if time_range.end and result.get("period_start", float("inf")) > time_range.end:
                continue
            filtered.append(result)
        return filtered


__all__ = ["L3Handler"]