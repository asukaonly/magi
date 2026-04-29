"""Shared RRF fusion utilities for hybrid retrieval layer handlers."""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import RetrievalConfig, TimeRange
from .reranker import build_retrieval_reranker

logger = logging.getLogger(__name__)


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


class RRFSearchHandler(abc.ABC):
    """Template for handlers that fuse BM25, vector, and keyword paths via RRF.

    Subclasses override the three search paths and the hydration step.
    """

    layer_name: str = "?"

    def __init__(self, store: Any, config: Optional[RetrievalConfig] = None) -> None:
        self._store = store
        self._config = config or RetrievalConfig()
        self._reranker = build_retrieval_reranker(self._config)

    @property
    def store(self) -> Any:
        """Read-only access to the underlying store instance."""
        return self._store

    def with_config(self, config: RetrievalConfig) -> "RRFSearchHandler":
        """Return a new handler sharing the same store but with *config*."""
        return self.__class__(self._store, config)

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
        for result in results:
            timestamp = result.get("timestamp") or result.get("created_at")
            if timestamp is None:
                filtered.append(result)
                continue
            if time_range.start and timestamp < time_range.start:
                continue
            if time_range.end and timestamp > time_range.end:
                continue
            filtered.append(result)
        return filtered


__all__ = ["RRFSearchHandler", "rrf_fuse"]