"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

import asyncio
import logging
import re
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
        self._refresh_handlers()
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
        payload.l1_evidence_bundles = await self._build_l1_evidence_bundles(payload.l1_events)
        payload.trace["l1_evidence_bundle_count"] = len(payload.l1_evidence_bundles)

        return payload

    def _refresh_handlers(self) -> None:
        """Refresh layer handlers in case stores are initialized after service construction."""
        self._l1 = L1Handler(self._memory.l1, self._config) if getattr(self._memory, "l1", None) else None
        self._l2 = (
            L2Handler(self._memory.l2, entity_catalog=getattr(self._memory, "l2_entity_catalog", None))
            if getattr(self._memory, "l2", None)
            else None
        )
        self._l3 = L3Handler(self._memory.l3, self._config) if getattr(self._memory, "l3", None) else None
        self._l4 = L4Handler(self._memory.l4, self._config) if getattr(self._memory, "l4", None) else None

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
            + len(payload.l1_evidence_bundles)
            + len(payload.l2_entity_cards)
            + len(payload.l2_relationships)
            + len(payload.l2_assertions)
            + len(payload.l3_reflections)
            + len(payload.l4_procedures)
        )

    async def _build_l1_evidence_bundles(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group L1 hits into session-local evidence bundles with lightweight neighbors."""
        if not hits or getattr(self._memory, "l1", None) is None:
            return []

        grouped_hits: Dict[str, List[Dict[str, Any]]] = {}
        for hit in hits:
            session_id = str(hit.get("session_id") or "").strip()
            if not session_id:
                continue
            grouped_hits.setdefault(session_id, []).append(hit)

        bundles: List[Dict[str, Any]] = []
        for session_id, session_hits in grouped_hits.items():
            session_events = await self._load_session_events(session_id, limit=max(len(session_hits) * 6, 12))
            bundle_events, neighbor_expansion_applied = self._select_bundle_events(
                session_events=session_events,
                session_hits=session_hits,
            )
            bundles.append(
                {
                    "session_id": session_id,
                    "hit_event_ids": [str(hit.get("event_id") or "") for hit in session_hits if hit.get("event_id")],
                    "hit_turn_ids": [str(hit.get("turn_id") or "") for hit in session_hits if hit.get("turn_id")],
                    "events": bundle_events,
                    "neighbor_expansion_applied": neighbor_expansion_applied,
                }
            )

        bundles.sort(
            key=lambda item: max((float(event.get("timestamp") or 0.0) for event in item["events"]), default=0.0),
            reverse=True,
        )
        return bundles

    async def _load_session_events(self, session_id: str, *, limit: int) -> List[Dict[str, Any]]:
        """Load a bounded set of events for a single session."""
        store = getattr(self._memory, "l1", None)
        if store is None:
            return []
        try:
            events = await store.query_events(session_id=session_id, limit=limit)
        except Exception:
            logger.debug("Failed to load session-local L1 events for evidence bundle", exc_info=True)
            return []
        return sorted(events, key=lambda event: float(event.get("timestamp") or 0.0))

    def _select_bundle_events(
        self,
        *,
        session_events: List[Dict[str, Any]],
        session_hits: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], bool]:
        """Select hit-centered session events, expanding to adjacent turns when possible."""
        if not session_events:
            return list(session_hits), False

        hit_event_ids = {str(hit.get("event_id") or "") for hit in session_hits}
        hit_turn_numbers = {
            turn_number
            for hit in session_hits
            for turn_number in [self._parse_turn_number(str(hit.get("turn_id") or ""))]
            if turn_number is not None
        }

        selected: List[Dict[str, Any]] = []
        for event in session_events:
            event_id = str(event.get("event_id") or "")
            if event_id in hit_event_ids:
                selected.append(event)
                continue
            turn_number = self._parse_turn_number(str(event.get("turn_id") or ""))
            if turn_number is None or not hit_turn_numbers:
                continue
            if any(abs(turn_number - hit_turn_number) <= 1 for hit_turn_number in hit_turn_numbers):
                selected.append(event)

        unique_events: List[Dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        for event in selected:
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            unique_events.append(event)
        unique_events.sort(key=lambda event: float(event.get("timestamp") or 0.0))
        neighbor_expansion_applied = len(unique_events) > len(session_hits)
        return unique_events or list(session_hits), neighbor_expansion_applied

    @staticmethod
    def _parse_turn_number(turn_id: str) -> int | None:
        """Extract a numeric turn suffix from session turn ids like `session:turn-3`."""
        match = re.search(r"turn-(\d+)$", str(turn_id or ""))
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None
