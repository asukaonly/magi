"""Execution path orchestration for hybrid retrieval service queries."""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol, cast

from ...utils.diagnostic_logging import full_content_logging_enabled
from .handlers import L1Handler, L2Handler, L3Handler, L4Handler
from .models import IntentDeciderInput, RetrievalConfig, RetrievalPayload, RetrievalQuery, TimeRange
from .service_backstops import HybridRetrievalBackstopMixin
from .service_plan_augmentation import HybridRetrievalPlanAugmentationMixin
from .service_plan_execution import HybridRetrievalPlanExecutionMixin, execute_layer_plan
from .service_query_expansion import HybridRetrievalQueryExpansionMixin

logger = logging.getLogger(__name__)

_execute_plan = execute_layer_plan


class _HybridRetrievalExecutionHost(Protocol):
    _config: RetrievalConfig
    _llm_provider_bridge: Any
    _intent_decider: Any
    _l1: L1Handler | None
    _l2: L2Handler | None
    _l3: L3Handler | None
    _l4: L4Handler | None

    async def _apply_post_processing(
        self,
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        mode_plan: Any = None,
    ) -> RetrievalPayload: ...

    async def _supplement_activity_summary(
        self,
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
        time_range: TimeRange | None,
    ) -> None: ...


class HybridRetrievalExecutionMixin(
    HybridRetrievalPlanExecutionMixin,
    HybridRetrievalPlanAugmentationMixin,
    HybridRetrievalQueryExpansionMixin,
    HybridRetrievalBackstopMixin,
):
    """Coordinate primary retrieval execution, expansion, backstops, and post-processing."""

    async def _execute_query(
        self,
        request: RetrievalQuery,
        decision: Any,
        intent_input: IntentDeciderInput,
        payload: RetrievalPayload,
        *,
        effective_l1: Optional[L1Handler] = None,
        mode_plan: Any = None,
    ) -> RetrievalPayload:
        """Inner query execution."""
        host = cast(_HybridRetrievalExecutionHost, self)
        l1 = effective_l1 if effective_l1 is not None else host._l1

        primary_plans = self._prepare_primary_plans(
            decision,
            request=request,
            payload=payload,
        )
        await self._execute_primary_plans(primary_plans, payload, l1=l1, request=request)
        await self._maybe_run_query_expansion(host, decision, request, payload, l1=l1)
        await self._run_retrieval_backstops(
            decision,
            intent_input,
            payload,
            l1=l1,
            request=request,
            primary_plans=primary_plans,
        )
        await self._maybe_supplement_activity_summary(
            host,
            decision,
            mode_plan,
            request,
            payload,
        )
        return await host._apply_post_processing(payload, request=request, mode_plan=mode_plan)

    def _prepare_primary_plans(
        self,
        decision: Any,
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
    ) -> list[Any]:
        primary_plans = self._augment_primary_plans(
            [p for p in decision.plans if not p.is_fallback],
            request=request,
            payload=payload,
            time_range=decision.time_range,
        )
        plan_summaries = (
            [
                (
                    p.layer,
                    p.is_fallback,
                    getattr(p.conditions, "content_query", "")[:60],
                )
                for p in primary_plans
            ]
            if full_content_logging_enabled()
            else [(p.layer, p.is_fallback) for p in primary_plans]
        )
        logger.debug(
            "Primary plans prepared | plan_count=%d layers=%s",
            len(primary_plans),
            plan_summaries,
        )
        return primary_plans

    async def _execute_primary_plans(
        self,
        primary_plans: list[Any],
        payload: RetrievalPayload,
        *,
        l1: L1Handler | None,
        request: RetrievalQuery,
    ) -> None:
        await self._execute_and_merge_plans(
            primary_plans,
            payload,
            l1=l1,
            request=request,
            label="Primary plan",
        )

    async def _maybe_run_query_expansion(
        self,
        host: _HybridRetrievalExecutionHost,
        decision: Any,
        request: RetrievalQuery,
        payload: RetrievalPayload,
        *,
        l1: L1Handler | None,
    ) -> None:
        if host._config.query_expansion_enabled and host._llm_provider_bridge:
            await self._run_query_expansion(
                original_query=request.query,
                request=request,
                payload=payload,
                time_range=decision.time_range,
                l1=l1,
            )

    async def _run_retrieval_backstops(
        self,
        decision: Any,
        intent_input: IntentDeciderInput,
        payload: RetrievalPayload,
        *,
        l1: L1Handler | None,
        request: RetrievalQuery,
        primary_plans: list[Any],
    ) -> None:
        await self._run_backstops(
            request,
            decision,
            intent_input,
            payload,
            l1=l1,
            primary_plans=primary_plans,
        )
        await self._run_fallback_if_needed(
            decision,
            payload,
            l1=l1,
            request=request,
        )

    async def _maybe_supplement_activity_summary(
        self,
        host: _HybridRetrievalExecutionHost,
        decision: Any,
        mode_plan: Any,
        request: RetrievalQuery,
        payload: RetrievalPayload,
    ) -> None:
        if (
            mode_plan is not None
            and mode_plan.mode == "activity_summary"
            and host._l3 is not None
            and request.summary_categories
        ):
            await host._supplement_activity_summary(
                request=request,
                payload=payload,
                time_range=decision.time_range,
            )


__all__ = ["HybridRetrievalExecutionMixin"]
