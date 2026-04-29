"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from ...config import AppConfig
from .answerability import (
    has_temporal_anchor,
)
from .handlers import L1Handler, L2Handler, L3Handler, L4Handler, execute_plan
from .evidence.session_bundles import EvidenceBundleMixin
from .intent_decider import IntentDecider, LLMIntentDecider, RuleBasedIntentDecider, enrich_l2_conditions
from .mode_registry import MODE_REGISTRY, VALID_MODES
from .router import normalize_query_mode
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
from .manifest_selector import ManifestSelector
from .result_fusion import ResultFusion
from .timeline_condense import build_timeline_summary
from .service_policy import (
    comparison_backstop_queries,
    count_payload_results,
    plan_signature,
    rule_backstop_reason,
)

logger = logging.getLogger(__name__)

def build_retrieval_config_from_app_config(app_config: AppConfig) -> RetrievalConfig:
    """Build retrieval config from the runtime app config."""
    reranker = app_config.agent.memory.reranker
    qe = app_config.agent.memory.query_expansion
    gs = app_config.agent.memory.graph_spreading
    return RetrievalConfig(
        reranker_top_k=reranker.top_k,
        cross_encoder_enabled=reranker.cross_encoder.enabled,
        cross_encoder_model_id=reranker.cross_encoder.managed_model_id,
        query_expansion_enabled=qe.enabled,
        graph_spreading_enabled=gs.enabled,
    )


class HybridRetrievalService(EvidenceBundleMixin):
    """Intent-driven hybrid retrieval across L0-L4 memory layers."""

    def __init__(
        self,
        unified_memory: Any,
        *,
        config: Optional[RetrievalConfig] = None,
        config_getter: Callable[[], RetrievalConfig] | None = None,
        llm_provider_bridge: Any = None,
    ) -> None:
        self._memory = unified_memory
        self._config = config or RetrievalConfig()
        self._config_getter = config_getter
        self._llm_provider_bridge = llm_provider_bridge
        self._result_fusion = ResultFusion(self._config)
        self._manifest_selector = ManifestSelector(self._config)

        # Build handlers from available stores
        l2_store = unified_memory.l2 if unified_memory.l2 else None
        self._l1 = (
            L1Handler(unified_memory.l1, self._config, l2_store=l2_store)
            if unified_memory.l1
            else None
        )
        self._l2 = (
            self._build_l2_handler(unified_memory)
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
        self._refresh_runtime_config()
        self._refresh_handlers()

        # 1. Resolve query mode — normalize legacy names first
        resolved_mode = normalize_query_mode(request.query_mode)
        mode_explicit = resolved_mode is not None and resolved_mode in VALID_MODES
        if not mode_explicit:
            resolved_mode = "exact_fact"
        raw_query_mode = str(request.query_mode or "").strip().lower()
        intent_query_mode_hint = "graph" if raw_query_mode == "graph" else (resolved_mode if mode_explicit else None)

        mode_plan = MODE_REGISTRY[resolved_mode]

        payload = RetrievalPayload(
            trace={
                "query": request.query,
                "query_mode": resolved_mode,
                "sources": request.source_filters,
                "domains": request.domain_filters,
            }
        )

        # 2. L0 unconditional
        if request.session_id and self._memory.l0 is not None:
            payload.l0_workbench = await self._load_l0(request.session_id)

        # 3. Intent decision
        intent_input = IntentDeciderInput(
            query=request.query,
            user_id=request.user_id,
            session_id=request.session_id,
            raw_time_range=request.time_range if request.time_range else None,
            source_filters=request.source_filters,
            domain_filters=request.domain_filters,
            summary_categories=list(request.summary_categories or []),
            query_mode_hint=intent_query_mode_hint,
            l1_limit=request.limit,
        )
        decision = await self._intent_decider.decide(intent_input)
        payload.trace["intent_source"] = decision.source
        payload.trace["intent_reasoning"] = decision.reasoning

        # 4. Build mode-adapted L1 handler with RRF weights from mode plan
        #    Only apply RRF overrides when query_mode was explicitly provided
        #    by the caller (tool call / API). Auto-classified modes use default
        #    weights to avoid keyword-heuristic errors distorting retrieval.
        effective_l1 = self._l1
        if mode_explicit and mode_plan.rrf_profile and self._l1 is not None:
            from dataclasses import replace as dc_replace

            adapted_config = dc_replace(
                self._config,
                **{k: v for k, v in mode_plan.rrf_profile.items() if hasattr(self._config, k)},
            )
            if adapted_config is not self._config:
                effective_l1 = self._l1.with_config(adapted_config)
                payload.trace["mode_rrf_applied"] = True
        payload.trace["mode_explicit"] = mode_explicit

        return await self._execute_query(
            request, decision, intent_input, payload,
            effective_l1=effective_l1,
            mode_plan=mode_plan,
        )

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
        """Inner query execution.

        *effective_l1* is the L1 handler to use for this query; it may
        differ from ``self._l1`` when mode-based RRF tuning creates
        a per-query handler copy.
        """
        l1 = effective_l1 if effective_l1 is not None else self._l1

        # 3. Execute primary plans in parallel
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

        # 3b. Query expansion — run additional L1 plans with reformulated queries
        if self._config.query_expansion_enabled and self._llm_provider_bridge:
            await self._run_query_expansion(
                original_query=request.query,
                request=request,
                payload=payload,
                time_range=decision.time_range,
                l1=l1,
            )

        # 4. Backstops + fallbacks
        await self._run_backstops(
            request, decision, intent_input, payload,
            l1=l1, primary_plans=primary_plans,
        )
        await self._run_fallback_if_needed(
            decision, payload, l1=l1, request=request,
        )

        # 4c. Activity summary supplement — fetch L3 by category directly.
        if (mode_plan is not None and mode_plan.mode == "activity_summary"
                and self._l3 is not None and request.summary_categories):
            await self._supplement_activity_summary(
                request=request,
                payload=payload,
                time_range=decision.time_range,
            )

        # 5+6. Post-processing (fusion, manifest selection, evidence bundles)
        return await self._apply_post_processing(payload, request=request, mode_plan=mode_plan)

    async def _supplement_activity_summary(
        self,
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
        time_range: Any,
    ) -> None:
        """Backfill L3 reflections by summary_category for activity_summary queries."""
        l3_store = getattr(self._l3, "_store", None)
        if l3_store is None:
            return
        period_start = getattr(time_range, "start", None) if time_range is not None else None
        period_end = getattr(time_range, "end", None) if time_range is not None else None
        try:
            summaries = await l3_store.list_summaries_by_category(
                summary_categories=list(request.summary_categories),
                period_start=period_start,
                period_end=period_end,
                limit=request.limit,
            )
        except Exception as exc:
            logger.warning("Activity summary supplement failed: %s", exc)
            return
        if not summaries:
            return
        existing_ids = {str(item.get("summary_id") or "") for item in payload.l3_reflections}
        for summary in summaries:
            sid = str(summary.get("summary_id") or "")
            if sid and sid in existing_ids:
                continue
            payload.l3_reflections.append(summary)

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
        results = await asyncio.gather(
            *[
                execute_plan(
                    plan,
                    l1=l1, l2=self._l2, l3=self._l3, l4=self._l4,
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
            self._merge_result(payload, plan.layer, result)

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
        backstop_reason = self._rule_backstop_reason(
            query=request.query,
            payload=payload,
            decision_source=decision.source,
        )
        if backstop_reason is not None:
            rule_decision = self._intent_decider._rule_engine.evaluate(intent_input)
            existing_signatures = {self._plan_signature(p) for p in primary_plans}
            rule_primary_plans = [
                plan
                for plan in rule_decision.plans
                if not plan.is_fallback and self._plan_signature(plan) not in existing_signatures
            ]
            # When L1 events are empty, also include L1 fallback plans from
            # the rule engine so the backstop does not rely solely on L2 data.
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
                payload.trace["rule_backstop_count"] = self._count_results(payload)

        comparison_backstop_queries = self._comparison_backstop_queries(
            query=request.query,
            payload=payload,
            decision_source=decision.source,
        )
        if comparison_backstop_queries:
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
                for content_query in comparison_backstop_queries
            ]
            await self._execute_and_merge_plans(
                comparison_plans, payload, l1=l1, request=request, label="Comparison backstop plan",
            )
            payload.trace["comparison_backstop_triggered"] = True
            payload.trace["comparison_backstop_count"] = self._count_results(payload)

    async def _run_fallback_if_needed(
        self,
        decision: Any,
        payload: RetrievalPayload,
        *,
        l1: Optional[L1Handler],
        request: RetrievalQuery,
    ) -> None:
        """Run fallback plans when primary + backstop results are insufficient or low-confidence."""
        primary_count = self._count_results(payload)
        payload.trace["primary_count"] = primary_count

        should_fallback = primary_count < self._config.fallback_trigger_threshold
        # Confidence-aware fallback: even if we have enough results, if the
        # top-K scores are too low the answers may be irrelevant.
        if (
            not should_fallback
            and self._config.confidence_fallback_enabled
            and payload.l1_events
        ):
            top_k = min(self._config.confidence_fallback_top_k, len(payload.l1_events))
            avg_score = sum(
                float(e.get("retrieval_score") or 0.0)
                for e in payload.l1_events[:top_k]
            ) / top_k
            if avg_score < self._config.confidence_fallback_min_score:
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

    async def _apply_post_processing(
        self,
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        mode_plan: Any = None,
    ) -> RetrievalPayload:
        """Apply fusion, manifest selection, evidence bundling, and timeline summary."""
        # Save pre-truncation L1 events for evidence bundling (fusion
        # truncates the list, but bundles need full session coverage).
        pre_fusion_l1_events = list(payload.l1_events)

        # Result fusion (dedup + token budget)
        payload = self._result_fusion.apply(payload, max_tokens=self._config.default_max_tokens)

        # Cross-layer manifest selection (optional LLM step)
        if self._config.manifest_selector_enabled:
            payload = await self._manifest_selector.select(
                payload, query=request.query, llm_bridge=self._llm_provider_bridge,
            )

        payload.l1_evidence_bundles = await self._build_l1_evidence_bundles(
            pre_fusion_l1_events,
            query=request.query,
        )
        payload.trace["l1_evidence_bundle_count"] = len(payload.l1_evidence_bundles)
        payload.trace["l1_evidence_bundle_sessions_total"] = len(
            {str(h.get("session_id") or "").strip() for h in pre_fusion_l1_events if h.get("session_id")}
        )
        payload.l1_timeline_summary = build_timeline_summary(
            question=request.query,
            evidence_bundles=payload.l1_evidence_bundles,
        )
        payload.trace["l1_timeline_summary_count"] = len(payload.l1_timeline_summary)
        payload.trace["l2_entity_card_count"] = len(payload.l2_entity_cards)
        payload.trace["l2_relationship_count"] = len(payload.l2_relationships)
        payload.trace["l2_assertion_count"] = len(payload.l2_assertions)

        # Evidence assembly + reducer (mode-driven pipeline)
        if mode_plan is not None:
            from .evidence import ASSEMBLER_REGISTRY
            from .reducers import REDUCER_REGISTRY

            assembler = ASSEMBLER_REGISTRY.get(mode_plan.evidence_shape)
            reducer = REDUCER_REGISTRY.get(mode_plan.reducer_type)
            if assembler is not None and reducer is not None:
                evidence = assembler.assemble(payload, request)
                reduced = reducer.reduce(evidence)
                payload.trace["evidence_shape"] = mode_plan.evidence_shape
                payload.trace["reducer_type"] = mode_plan.reducer_type
                payload.trace["evidence_reduced"] = reduced

        return payload

    @staticmethod
    def _plan_signature(plan: Any) -> tuple[str, str, bool]:
        """Build a stable identity for a layer query plan."""
        return plan_signature(plan)

    def _refresh_handlers(self) -> None:
        """Rebuild layer handlers only when the underlying stores change.

        The previous implementation unconditionally rebuilt every handler on
        each ``query()`` call, wasting object creation and discarding any
        per-query config overrides applied earlier.  This version checks
        whether the store references have actually changed before rebuilding.
        """
        l1_store = getattr(self._memory, "l1", None)
        l2_store = getattr(self._memory, "l2", None)
        l3_store = getattr(self._memory, "l3", None)
        l4_store = getattr(self._memory, "l4", None)

        if l1_store and (self._l1 is None or self._l1.store is not l1_store):
            self._l1 = L1Handler(l1_store, self._config, l2_store=l2_store)
        elif not l1_store:
            self._l1 = None

        if l2_store and (self._l2 is None or self._l2.store is not l2_store):
            self._l2 = self._build_l2_handler(self._memory)
        elif not l2_store:
            self._l2 = None

        if l3_store and (self._l3 is None or self._l3.store is not l3_store):
            self._l3 = L3Handler(l3_store, self._config)
        elif not l3_store:
            self._l3 = None

        if l4_store and (self._l4 is None or self._l4.store is not l4_store):
            self._l4 = L4Handler(l4_store, self._config)
        elif not l4_store:
            self._l4 = None

    @staticmethod
    def _build_l2_handler(memory: Any) -> L2Handler:
        """Construct L2Handler with embedding infra when available."""
        catalog = getattr(memory, "l2_entity_catalog", None)
        embedding_service = getattr(catalog, "embedding_service", None) if catalog else None
        edge_vector_index = None
        if embedding_service is not None:
            try:
                edge_vector_index = catalog.edge_vector_index
            except Exception:
                logger.warning("Failed to get L2 edge vector index", exc_info=True)
        return L2Handler(
            memory.l2,
            entity_catalog=catalog,
            embedding_service=embedding_service,
            edge_vector_index=edge_vector_index,
        )

    def _refresh_runtime_config(self) -> None:
        """Refresh retrieval config from the runtime getter if one is available."""
        if self._config_getter is None:
            return
        next_config = self._config_getter()
        if next_config == self._config:
            return
        self._config = next_config
        self._result_fusion = ResultFusion(self._config)
        self._manifest_selector = ManifestSelector(self._config)

    def _augment_primary_plans(
        self,
        primary_plans: list[LayerQueryPlan],
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
    ) -> list[LayerQueryPlan]:
        """Add service-level evidence plans for semantic affinity queries when needed.

        Also guarantees that at least one L1 plan is always present so
        entity-expansion retrieval is never skipped.
        """
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

        # Ensure L1 always participates (entity co-occurrence expansion)
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

        # Inject L2 plan when the query contains temporal markers but the
        # intent decider (typically the LLM) routed to L1-only.  L2
        # knowledge-graph edges carry timestamps and can directly answer
        # "time + fact" questions (e.g. "What did I buy 10 days ago?").
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

    async def _load_l0(self, session_id: str) -> List[Dict[str, Any]]:
        """Load L0 workbench data."""
        try:
            projection = await self._memory.l0.get_prompt_workbench_projection(session_id)
            if projection.session is not None:
                return [projection.to_retrieval_entry()]
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
                payload.l2_episodes.extend(result.get("episodes", []))
                payload.l2_state_facts.extend(result.get("state_facts", []))
                payload.l2_state_history.extend(result.get("state_history", []))
                if isinstance(result.get("trace"), dict):
                    payload.trace["l2_query_trace"] = result["trace"]
        elif layer == "L3":
            payload.l3_reflections.extend(result if isinstance(result, list) else [])
        elif layer == "L4":
            payload.l4_procedures.extend(result if isinstance(result, list) else [])

    @staticmethod
    def _count_results(payload: RetrievalPayload) -> int:
        """Count total non-L0 retrieval results.

        Only counts items populated during the retrieval phase.
        ``l1_evidence_bundles`` and ``l1_timeline_summary`` are assembled
        *after* retrieval and should not influence fallback decisions.
        """
        return count_payload_results(payload)

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

        effective_l1 = l1 if l1 is not None else self._l1

        expander = QueryExpander(
            self._llm_provider_bridge,
            timeout_seconds=self._config.query_expansion_timeout_seconds,
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
                execute_plan(
                    plan,
                    l1=effective_l1, l2=self._l2, l3=self._l3, l4=self._l4,
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
            self._merge_result(payload, plan.layer, result)
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
