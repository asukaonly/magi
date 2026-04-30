"""Execution path helpers for hybrid retrieval service queries."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional, Protocol, cast

from .answerability import has_temporal_anchor
from .handlers import L1Handler, L2Handler, L3Handler, L4Handler
from .intent_decider import enrich_l2_conditions
from .models import (
    IntentDeciderInput,
    L1Conditions,
    L2Conditions,
    LayerQueryPlan,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
    TimeRange,
)
from .service_policy import (
    comparison_backstop_queries,
    plan_signature,
    rule_backstop_reason,
)

logger = logging.getLogger(__name__)


async def _execute_plan(plan: LayerQueryPlan, **kwargs: Any) -> Any:
    from . import service as service_module

    return await service_module.execute_plan(plan, **kwargs)


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

    def _merge_result(self, payload: RetrievalPayload, layer: str, result: Any) -> None: ...

    def _count_results(self, payload: RetrievalPayload) -> int: ...


class HybridRetrievalExecutionMixin:
    """Execute retrieval plans, backstops, fallbacks, and query expansion."""

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

        primary_plans = self._augment_primary_plans(
            [p for p in decision.plans if not p.is_fallback],
            request=request,
            payload=payload,
        )
        logger.debug(
            "Primary plans prepared | plan_count=%d layers=%s",
            len(primary_plans),
            [(p.layer, p.is_fallback, getattr(p.conditions, "content_query", "")[:60]) for p in primary_plans],
        )
        await self._execute_and_merge_plans(
            primary_plans, payload, l1=l1, request=request, label="Primary plan",
        )

        if host._config.query_expansion_enabled and host._llm_provider_bridge:
            await self._run_query_expansion(
                original_query=request.query,
                request=request,
                payload=payload,
                time_range=decision.time_range,
                l1=l1,
            )

        await self._run_backstops(
            request, decision, intent_input, payload,
            l1=l1, primary_plans=primary_plans,
        )
        await self._run_fallback_if_needed(
            decision, payload, l1=l1, request=request,
        )

        if (mode_plan is not None and mode_plan.mode == "activity_summary"
                and host._l3 is not None and request.summary_categories):
            await host._supplement_activity_summary(
                request=request,
                payload=payload,
                time_range=decision.time_range,
            )

        return await host._apply_post_processing(payload, request=request, mode_plan=mode_plan)

    async def _execute_and_merge_plans(
        self,
        plans: List[LayerQueryPlan],
        payload: RetrievalPayload,
        *,
        l1: Optional[L1Handler],
        request: RetrievalQuery,
        label: str = "Plan",
    ) -> None:
        """Execute layer query plans in parallel and merge results into *payload*."""
        if not plans:
            return
        host = cast(_HybridRetrievalExecutionHost, self)
        results = await asyncio.gather(
            *[
                _execute_plan(
                    plan,
                    l1=l1, l2=host._l2, l3=host._l3, l4=host._l4,
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

    async def _run_backstops(
        self,
        request: RetrievalQuery,
        decision: Any,
        intent_input: IntentDeciderInput,
        payload: RetrievalPayload,
        *,
        l1: Optional[L1Handler],
        primary_plans: List[LayerQueryPlan],
    ) -> None:
        """Run rule-based and comparison backstops when primary results are insufficient."""
        host = cast(_HybridRetrievalExecutionHost, self)
        backstop_reason = self._rule_backstop_reason(
            query=request.query,
            payload=payload,
            decision_source=decision.source,
        )
        if backstop_reason is not None:
            rule_decision = host._intent_decider._rule_engine.evaluate(intent_input)
            existing_signatures = {self._plan_signature(p) for p in primary_plans}
            rule_primary_plans = [
                plan
                for plan in rule_decision.plans
                if not plan.is_fallback and self._plan_signature(plan) not in existing_signatures
            ]
            if not payload.l1_events:
                rule_l1_fallback_plans = [
                    plan
                    for plan in rule_decision.plans
                    if plan.is_fallback and getattr(plan, "layer", "") == "L1"
                    and self._plan_signature(plan) not in existing_signatures
                ]
                rule_primary_plans.extend(rule_l1_fallback_plans)
            await self._execute_and_merge_plans(
                rule_primary_plans, payload, l1=l1, request=request, label="Rule backstop plan",
            )
            if rule_primary_plans:
                payload.trace["rule_backstop_triggered"] = True
                payload.trace["rule_backstop_reason"] = backstop_reason
                payload.trace["rule_backstop_count"] = host._count_results(payload)

        backstop_queries = self._comparison_backstop_queries(
            query=request.query,
            payload=payload,
            decision_source=decision.source,
        )
        if backstop_queries:
            comparison_plans = [
                LayerQueryPlan(
                    layer="L1",
                    conditions=L1Conditions(
                        content_query=content_query,
                        source_filters=request.source_filters or None,
                        domain_filters=request.domain_filters or None,
                        limit=request.limit,
                    ),
                    is_fallback=False,
                )
                for content_query in backstop_queries
            ]
            await self._execute_and_merge_plans(
                comparison_plans, payload, l1=l1, request=request, label="Comparison backstop plan",
            )
            payload.trace["comparison_backstop_triggered"] = True
            payload.trace["comparison_backstop_count"] = host._count_results(payload)

    async def _run_fallback_if_needed(
        self,
        decision: Any,
        payload: RetrievalPayload,
        *,
        l1: Optional[L1Handler],
        request: RetrievalQuery,
    ) -> None:
        """Run fallback plans when primary + backstop results are insufficient or low-confidence."""
        host = cast(_HybridRetrievalExecutionHost, self)
        primary_count = host._count_results(payload)
        payload.trace["primary_count"] = primary_count

        should_fallback = primary_count < host._config.fallback_trigger_threshold
        if (
            not should_fallback
            and host._config.confidence_fallback_enabled
            and payload.l1_events
        ):
            top_k = min(host._config.confidence_fallback_top_k, len(payload.l1_events))
            avg_score = sum(
                float(e.get("retrieval_score") or 0.0)
                for e in payload.l1_events[:top_k]
            ) / top_k
            if avg_score < host._config.confidence_fallback_min_score:
                should_fallback = True
                payload.trace["confidence_fallback_triggered"] = True
                payload.trace["confidence_fallback_avg_score"] = round(avg_score, 6)

        if should_fallback:
            fallback_plans = [p for p in decision.plans if p.is_fallback]
            await self._execute_and_merge_plans(
                fallback_plans, payload, l1=l1, request=request, label="Fallback plan",
            )
            if fallback_plans:
                payload.trace["fallback_triggered"] = True

    @staticmethod
    def _plan_signature(plan: Any) -> tuple[str, str, bool]:
        """Build a stable identity for a layer query plan."""
        return plan_signature(plan)

    def _augment_primary_plans(
        self,
        primary_plans: list[LayerQueryPlan],
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
    ) -> list[LayerQueryPlan]:
        """Add service-level evidence plans for semantic affinity queries when needed."""
        seen_signatures = {self._plan_signature(plan) for plan in primary_plans}
        augmented_plans = list(primary_plans)
        added_joint_l1_plan = False

        for plan in primary_plans:
            joint_l1_plan = self._build_joint_l1_evidence_plan(plan, request=request)
            if joint_l1_plan is None:
                continue
            signature = self._plan_signature(joint_l1_plan)
            if signature in seen_signatures:
                continue
            augmented_plans.append(joint_l1_plan)
            seen_signatures.add(signature)
            added_joint_l1_plan = True

        if added_joint_l1_plan:
            payload.trace["joint_l1_affinity_evidence"] = True

        has_l1 = any(p.layer == "L1" for p in augmented_plans)
        if not has_l1:
            l1_plan = LayerQueryPlan(
                layer="L1",
                conditions=L1Conditions(
                    content_query=request.query,
                    source_filters=request.source_filters or None,
                    domain_filters=request.domain_filters or None,
                    limit=request.limit,
                ),
                is_fallback=False,
            )
            augmented_plans.append(l1_plan)
            payload.trace["l1_always_injected"] = True

        has_l2 = any(p.layer == "L2" for p in augmented_plans)
        if not has_l2 and has_temporal_anchor(request.query):
            l2_conditions = L2Conditions(
                content_query=request.query,
                subject_hint="self",
                include_tom_snapshot=True,
                include_relationships=True,
                include_assertions=True,
            )
            enrich_l2_conditions(l2_conditions, request.query)
            l2_plan = LayerQueryPlan(
                layer="L2",
                conditions=l2_conditions,
                is_fallback=False,
            )
            augmented_plans.append(l2_plan)
            payload.trace["l2_temporal_injected"] = True

        return augmented_plans

    @staticmethod
    def _build_joint_l1_evidence_plan(
        plan: LayerQueryPlan,
        *,
        request: RetrievalQuery,
    ) -> LayerQueryPlan | None:
        """Build an auxiliary L1 evidence plan for time-bounded interaction affinity queries."""
        if plan.layer != "L2" or not isinstance(plan.conditions, L2Conditions):
            return None

        semantic_frame = plan.conditions.semantic_frame
        if semantic_frame is None:
            return None
        if semantic_frame.query_family != "affinity":
            return None
        if not any(constraint.scope == "interaction" for constraint in semantic_frame.constraints):
            return None
        if plan.time_range is None or (plan.time_range.start is None and plan.time_range.end is None):
            return None

        return LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(
                content_query=request.query,
                source_filters=request.source_filters or None,
                domain_filters=request.domain_filters or None,
                limit=request.limit,
            ),
            time_range=plan.time_range,
            is_fallback=False,
        )

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

        host = cast(_HybridRetrievalExecutionHost, self)
        effective_l1 = l1 if l1 is not None else host._l1

        expander = QueryExpander(
            host._llm_provider_bridge,
            timeout_seconds=host._config.query_expansion_timeout_seconds,
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
                    limit=request.limit,
                ),
                time_range=time_range,
                is_fallback=False,
            )
            for eq in expanded_queries
        ]
        expansion_results = await asyncio.gather(
            *[
                _execute_plan(
                    plan,
                    l1=effective_l1, l2=host._l2, l3=host._l3, l4=host._l4,
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

    @staticmethod
    def _rule_backstop_reason(
        *,
        query: str,
        payload: RetrievalPayload,
        decision_source: str,
    ) -> str | None:
        return rule_backstop_reason(query=query, payload=payload, decision_source=decision_source)

    @staticmethod
    def _comparison_backstop_queries(
        *,
        query: str,
        payload: RetrievalPayload,
        decision_source: str,
    ) -> list[str]:
        return comparison_backstop_queries(query=query, payload=payload, decision_source=decision_source)


__all__ = ["HybridRetrievalExecutionMixin"]