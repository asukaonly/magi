"""Benchmark-facing reader that queries memory without chat rendering."""

from __future__ import annotations

from typing import Any

from ..hybrid_retrieval import build_query
from .contracts import EvalMemoryQuery, EvalMemoryQueryResult
from .trace import build_eval_query_result


class EvalMemoryReader:
    """Read memory through the retrieval layer using eval namespaces as scope."""

    def __init__(self, retrieval_service: Any) -> None:
        self._retrieval_service = retrieval_service

    async def query_memory(self, query: EvalMemoryQuery) -> EvalMemoryQueryResult:
        request = build_query(
            query=query.query,
            user_id=query.namespace,
            session_id=None,
            time_range={},
            query_mode=None if query.mode == "auto" else query.mode,
            source_filters=[],
            domain_filters=[],
            limit=query.top_k,
        )
        payload = await self._retrieval_service.query(request)
        return build_eval_query_result(payload)
