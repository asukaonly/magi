"""Plan execution helpers for hybrid retrieval service queries."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, cast

from .handlers import L1Handler
from .models import LayerQueryPlan, RetrievalPayload, RetrievalQuery

logger = logging.getLogger(__name__)


async def execute_layer_plan(plan: LayerQueryPlan, **kwargs: Any) -> Any:
    from . import service as service_module

    return await service_module.execute_plan(plan, **kwargs)


class HybridRetrievalPlanExecutionMixin:
    """Execute layer query plans in parallel and merge their results."""

    async def _execute_and_merge_plans(
        self,
        plans: list[LayerQueryPlan],
        payload: RetrievalPayload,
        *,
        l1: Optional[L1Handler],
        request: RetrievalQuery,
        label: str = "Plan",
    ) -> None:
        """Execute layer query plans in parallel and merge results into *payload*."""
        if not plans:
            return
        host = cast(Any, self)
        results = await asyncio.gather(
            *[
                execute_layer_plan(
                    plan,
                    l1=l1,
                    l2=host._l2,
                    l3=host._l3,
                    l4=host._l4,
                    session_id=request.session_id,
                    user_id=request.user_id,
                )
                for plan in plans
            ],
            return_exceptions=True,
        )
        for plan, result in zip(plans, results):
            if isinstance(result, Exception):
                logger.warning("%s %s failed: %s", label, plan.layer, result)
                continue
            host._merge_result(payload, plan.layer, result)


__all__ = ["HybridRetrievalPlanExecutionMixin", "execute_layer_plan"]
