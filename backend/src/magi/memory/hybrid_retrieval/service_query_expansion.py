"""Query expansion helpers for hybrid retrieval service queries."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, cast, Any

from .handlers import L1Handler
from .models import L1Conditions, LayerQueryPlan, RetrievalPayload, RetrievalQuery, TimeRange
from .service_plan_execution import execute_layer_plan

logger = logging.getLogger(__name__)


class HybridRetrievalQueryExpansionMixin:
    """Generate expanded query variants and run additional L1 evidence plans."""

    async def _run_query_expansion(
        self,
        *,
        original_query: str,
        request: RetrievalQuery,
        payload: RetrievalPayload,
        time_range: Optional[TimeRange] = None,
        l1: Optional[L1Handler] = None,
    ) -> None:
        """Generate expanded query variants and run additional L1 plans."""
        from .query_expander import QueryExpander

        host = cast(Any, self)
        effective_l1 = l1 if l1 is not None else host._l1

        expander = QueryExpander(
            host._llm_provider_bridge,
            timeout_seconds=host._config.query_expansion_timeout_seconds,
            max_expansions=host._config.query_expansion_max_expansions,
        )
        expanded_queries = await expander.expand(original_query)
        if not expanded_queries:
            return

        payload.trace["query_expansion_queries"] = expanded_queries

        expansion_plans = [
            LayerQueryPlan(
                layer="L1",
                conditions=L1Conditions(
                    content_query=eq,
                    source_filters=request.source_filters or None,
                    domain_filters=request.domain_filters or None,
                    context_scope=dict(request.context_scope or {}),
                    limit=request.limit,
                ),
                time_range=time_range,
                is_fallback=False,
            )
            for eq in expanded_queries
        ]
        expansion_results = await asyncio.gather(
            *[
                execute_layer_plan(
                    plan,
                    l1=effective_l1,
                    l2=host._l2,
                    l3=host._l3,
                    l4=host._l4,
                    session_id=request.session_id,
                    user_id=request.user_id,
                )
                for plan in expansion_plans
            ],
            return_exceptions=True,
        )
        added = 0
        for plan, result in zip(expansion_plans, expansion_results):
            if isinstance(result, Exception):
                logger.warning("Query expansion plan failed: %s", result)
                continue
            if isinstance(result, list):
                added += len(result)
            host._merge_result(payload, plan.layer, result)
        payload.trace["query_expansion_added"] = added


__all__ = ["HybridRetrievalQueryExpansionMixin"]
