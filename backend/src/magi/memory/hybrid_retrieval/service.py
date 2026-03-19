"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .handlers import L1Handler, L2Handler, L3Handler, L4Handler, execute_plan
from .intent_decider import IntentDecider, LLMIntentDecider, RuleBasedIntentDecider
from .models import (
    IntentDeciderInput,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
)
from .result_fusion import ResultFusion

logger = logging.getLogger(__name__)


class HybridRetrievalService:
    """Intent-driven hybrid retrieval across L0-L4 memory layers."""

    def __init__(
        self,
        unified_memory: Any,
        *,
        config: Optional[RetrievalConfig] = None,
        llm_provider_bridge: Any = None,
    ) -> None:
        self._memory = unified_memory
        self._config = config or RetrievalConfig()
        self._result_fusion = ResultFusion(self._config)

        # Build handlers from available stores
        self._l1 = L1Handler(unified_memory.l1, self._config) if unified_memory.l1 else None
        self._l2 = (
            L2Handler(unified_memory.l2, entity_catalog=getattr(unified_memory, "l2_entity_catalog", None))
            if unified_memory.l2
            else None
        )
        self._l3 = L3Handler(unified_memory.l3, self._config) if unified_memory.l3 else None
        self._l4 = L4Handler(unified_memory.l4, self._config) if unified_memory.l4 else None

        # Build intent decider
        rule_engine = RuleBasedIntentDecider()
        llm_decider = None
        if llm_provider_bridge and self._config.intent_decider_llm_enabled:
            llm_decider = LLMIntentDecider(
                llm_provider_bridge,
                timeout_seconds=self._config.intent_decider_llm_timeout_seconds,
            )

        self._intent_decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=self._config.intent_decider_llm_enabled,
            shadow_eval_enabled=self._config.intent_shadow_eval_enabled,
        )

    async def query(self, request: RetrievalQuery) -> RetrievalPayload:
        """Execute a layer-aware retrieval query."""
        payload = RetrievalPayload(
            trace={
                "query": request.query,
                "query_mode": request.query_mode,
                "sources": request.source_filters,
                "domains": request.domain_filters,
            }
        )

        # 1. L0 unconditional
        if request.session_id and self._memory.l0 is not None:
            payload.l0_workbench = await self._load_l0(request.session_id)

        # 2. Intent decision
        intent_input = IntentDeciderInput(
            query=request.query,
            user_id=request.user_id,
            session_id=request.session_id,
            raw_time_range=request.time_range if request.time_range else None,
            source_filters=request.source_filters,
            domain_filters=request.domain_filters,
            query_mode_hint=request.query_mode,
        )
        decision = await self._intent_decider.decide(intent_input)
        payload.trace["intent_source"] = decision.source
        payload.trace["intent_reasoning"] = decision.reasoning

        # 3. Execute primary plans in parallel
        primary_plans = [p for p in decision.plans if not p.is_fallback]
        if primary_plans:
            primary_results = await asyncio.gather(
                *[
                    execute_plan(
                        plan,
                        l1=self._l1, l2=self._l2, l3=self._l3, l4=self._l4,
                        session_id=request.session_id,
                        user_id=request.user_id,
                    )
                    for plan in primary_plans
                ],
                return_exceptions=True,
            )
            for plan, result in zip(primary_plans, primary_results):
                if isinstance(result, Exception):
                    logger.warning("Primary plan %s failed: %s", plan.layer, result)
                    continue
                self._merge_result(payload, plan.layer, result)

        # 4. Fallback if primary results are insufficient
        primary_count = self._count_results(payload)
        payload.trace["primary_count"] = primary_count

        if primary_count < self._config.fallback_trigger_threshold:
            fallback_plans = [p for p in decision.plans if p.is_fallback]
            if fallback_plans:
                fallback_results = await asyncio.gather(
                    *[
                        execute_plan(
                            plan,
                            l1=self._l1, l2=self._l2, l3=self._l3, l4=self._l4,
                            session_id=request.session_id,
                            user_id=request.user_id,
                        )
                        for plan in fallback_plans
                    ],
                    return_exceptions=True,
                )
                for plan, result in zip(fallback_plans, fallback_results):
                    if isinstance(result, Exception):
                        logger.warning("Fallback plan %s failed: %s", plan.layer, result)
                        continue
                    self._merge_result(payload, plan.layer, result)
                payload.trace["fallback_triggered"] = True

        # 5. Result fusion (dedup + token budget)
        payload = self._result_fusion.apply(payload, max_tokens=self._config.default_max_tokens)

        return payload

    async def _load_l0(self, session_id: str) -> List[Dict[str, Any]]:
        """Load L0 workbench data."""
        try:
            workbench = await self._memory.l0.get_workbench(session_id)
            if workbench.get("session") is not None:
                return [
                    {
                        "session": workbench["session"],
                        "goals": workbench.get("goal_stack", [])[:3],
                        "active_entities": workbench.get("active_entities", [])[:5],
                        "temporary_tactics": workbench.get("temporary_tactics", [])[:5],
                    }
                ]
        except Exception:
            logger.debug("L0 workbench load failed", exc_info=True)
        return []

    @staticmethod
    def _merge_result(payload: RetrievalPayload, layer: str, result: Any) -> None:
        """Merge handler result into payload."""
        if layer == "L1":
            payload.l1_events.extend(result if isinstance(result, list) else [])
        elif layer == "L2":
            if isinstance(result, dict):
                payload.l2_entity_cards.extend(result.get("entity_cards", []))
                payload.l2_relationships.extend(result.get("relationships", []))
                payload.l2_assertions.extend(result.get("assertions", []))
                if isinstance(result.get("trace"), dict):
                    payload.trace["l2_query_trace"] = result["trace"]
        elif layer == "L3":
            payload.l3_reflections.extend(result if isinstance(result, list) else [])
        elif layer == "L4":
            payload.l4_procedures.extend(result if isinstance(result, list) else [])

    @staticmethod
    def _count_results(payload: RetrievalPayload) -> int:
        """Count total non-L0 results."""
        return (
            len(payload.l1_events)
            + len(payload.l2_entity_cards)
            + len(payload.l2_relationships)
            + len(payload.l2_assertions)
            + len(payload.l3_reflections)
            + len(payload.l4_procedures)
        )
