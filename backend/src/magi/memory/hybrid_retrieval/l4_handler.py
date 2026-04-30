"""L4 procedural memory retrieval handler."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .handler_base import RRFSearchHandler
from .models import L4Conditions, RetrievalConfig, TimeRange
from .protocols import L4StoreProtocol

logger = logging.getLogger(__name__)


class L4Handler(RRFSearchHandler):
    """Execute L4 procedural memory queries with BM25 + keyword fusion.

    The procedural_skills table is small (one row per tool/workflow, typically
    <1000 rows).  BM25 + keyword provides equivalent recall to triple-path
    RRF without the per-query embedding cost that the vector path incurs.
    """

    layer_name = "L4"

    def __init__(self, l4_store: L4StoreProtocol, config: Optional[RetrievalConfig] = None) -> None:
        super().__init__(l4_store, config)

    async def execute(
        self,
        conditions: L4Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L4 using BM25 + keyword, fused via RRF."""
        if not conditions.content_query:
            return []
        cfg = self._config
        fetch_k = max(conditions.limit * cfg.rrf_over_fetch_multiplier, cfg.rrf_over_fetch_minimum)
        return await self._rrf_execute(
            content_query=conditions.content_query,
            limit=conditions.limit,
            bm25_coro=self._bm25_path(conditions.content_query, fetch_k),
            vector_coro=self._noop_vector(),
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

    @staticmethod
    async def _noop_vector() -> List[str]:
        """Disabled: procedural_skills is too small to justify per-query embedding."""
        return []

    async def _keyword_path(self, query: str, limit: int) -> List[str]:
        try:
            return await self._store.keyword_search(query, limit=limit)
        except Exception as exc:
            logger.warning("L4 keyword path failed: %s", exc)
            return []

    async def _fetch_by_ids(self, skill_ids: List[str]) -> List[Dict[str, Any]]:
        return await self._store.fetch_by_ids(skill_ids)


__all__ = ["L4Handler"]