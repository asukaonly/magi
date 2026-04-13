"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from ...config import AppConfig
from .answerability import (
    extract_comparison_spans,
    extract_query_tokens,
    extract_quoted_spans,
    has_temporal_anchor,
)
from .handlers import L1Handler, L2Handler, L3Handler, L4Handler, execute_plan
from .intent_decider import IntentDecider, LLMIntentDecider, RuleBasedIntentDecider, enrich_l2_conditions
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
from .reranker import build_retrieval_reranker
from .result_fusion import ResultFusion
from .timeline_condense import build_timeline_summary

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


class HybridRetrievalService:
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
        payload = RetrievalPayload(
            trace={
                "query": request.query,
                "recall_intent": request.recall_intent,
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
            recall_intent_hint=request.recall_intent,
            query_mode_hint=request.query_mode,
            l1_limit=request.limit,
        )
        decision = await self._intent_decider.decide(intent_input)
        payload.trace["intent_source"] = decision.source
        payload.trace["intent_reasoning"] = decision.reasoning

        # 2b. Adaptive parameter tuning based on intent signals
        effective_query_mode = request.query_mode
        effective_recall_intent = request.recall_intent
        saved_l1_config = None
        saved_l1_reranker = None
        if effective_query_mode or effective_recall_intent:
            from .adaptive_params import adapt_config

            adapted = adapt_config(
                self._config,
                query_mode=effective_query_mode,
                recall_intent=effective_recall_intent,
            )
            if adapted is not self._config and self._l1 is not None:
                # Save original config/reranker so we can restore after this query
                saved_l1_config = self._l1._config
                saved_l1_reranker = self._l1._reranker
                self._l1._config = adapted
                self._l1._reranker = build_retrieval_reranker(adapted)
                payload.trace["adaptive_params_applied"] = True
                payload.trace["adaptive_query_mode"] = effective_query_mode
                payload.trace["adaptive_recall_intent"] = effective_recall_intent

        try:
            return await self._execute_query(request, decision, intent_input, payload)
        finally:
            # Restore L1 handler config so concurrent/subsequent queries are not affected
            if saved_l1_config is not None and self._l1 is not None:
                self._l1._config = saved_l1_config
                self._l1._reranker = saved_l1_reranker

    async def _execute_query(
        self,
        request: RetrievalQuery,
        decision: Any,
        intent_input: IntentDeciderInput,
        payload: RetrievalPayload,
    ) -> RetrievalPayload:
        """Inner query execution, separated so adaptive config can be restored via try/finally."""
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
                result_len = len(result) if isinstance(result, list) else (len(result.get("entity_cards", [])) if isinstance(result, dict) else 0)
                logger.debug(
                    "Primary plan %s merge | result_type=%s result_len=%d",
                    plan.layer, type(result).__name__, result_len,
                )
                self._merge_result(payload, plan.layer, result)

        # 3b. Query expansion — run additional L1 plans with reformulated queries
        if self._config.query_expansion_enabled and self._llm_provider_bridge:
            await self._run_query_expansion(
                original_query=request.query,
                request=request,
                payload=payload,
                time_range=decision.time_range,
            )

        # 4. Fallback if primary results are insufficient
        primary_count = self._count_results(payload)
        backstop_reason = self._rule_backstop_reason(
            query=request.query,
            payload=payload,
            decision_source=decision.source,
        )
        if backstop_reason is not None:
            rule_decision = self._intent_decider._rule_engine.evaluate(intent_input)
            rule_primary_plans = [
                plan
                for plan in rule_decision.plans
                if not plan.is_fallback and self._plan_signature(plan) not in {self._plan_signature(existing) for existing in primary_plans}
            ]
            # When L1 events are empty, also include L1 fallback plans from
            # the rule engine so the backstop does not rely solely on L2 data.
            if not payload.l1_events:
                rule_l1_fallback_plans = [
                    plan
                    for plan in rule_decision.plans
                    if plan.is_fallback and getattr(plan, "layer", "") == "L1"
                    and self._plan_signature(plan) not in {self._plan_signature(existing) for existing in primary_plans}
                ]
                rule_primary_plans.extend(rule_l1_fallback_plans)
            if rule_primary_plans:
                rule_primary_results = await asyncio.gather(
                    *[
                        execute_plan(
                            plan,
                            l1=self._l1, l2=self._l2, l3=self._l3, l4=self._l4,
                            session_id=request.session_id,
                            user_id=request.user_id,
                        )
                        for plan in rule_primary_plans
                    ],
                    return_exceptions=True,
                )
                for plan, result in zip(rule_primary_plans, rule_primary_results):
                    if isinstance(result, Exception):
                        logger.warning("Rule backstop plan %s failed: %s", plan.layer, result)
                        continue
                    self._merge_result(payload, plan.layer, result)
                primary_count = self._count_results(payload)
                payload.trace["rule_backstop_triggered"] = True
                payload.trace["rule_backstop_reason"] = backstop_reason
                payload.trace["rule_backstop_count"] = primary_count

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
            comparison_results = await asyncio.gather(
                *[
                    execute_plan(
                        plan,
                        l1=self._l1, l2=self._l2, l3=self._l3, l4=self._l4,
                        session_id=request.session_id,
                        user_id=request.user_id,
                    )
                    for plan in comparison_plans
                ],
                return_exceptions=True,
            )
            for plan, result in zip(comparison_plans, comparison_results):
                if isinstance(result, Exception):
                    logger.warning("Comparison backstop plan %s failed: %s", plan.layer, result)
                    continue
                self._merge_result(payload, plan.layer, result)
            primary_count = self._count_results(payload)
            payload.trace["comparison_backstop_triggered"] = True
            payload.trace["comparison_backstop_count"] = primary_count

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

        # Save pre-truncation L1 events for evidence bundling (fusion
        # truncates the list, but bundles need full session coverage).
        pre_fusion_l1_events = list(payload.l1_events)

        # 5. Result fusion (dedup + token budget)
        payload = self._result_fusion.apply(payload, max_tokens=self._config.default_max_tokens)

        # 6. Cross-layer manifest selection (optional LLM step)
        if self._config.manifest_selector_enabled:
            payload = await self._manifest_selector.select(
                payload, query=request.query, llm_bridge=self._llm_provider_bridge,
            )

        payload.l1_evidence_bundles = await self._build_l1_evidence_bundles(
            pre_fusion_l1_events,
            query=request.query,
        )
        payload.trace["l1_evidence_bundle_count"] = len(payload.l1_evidence_bundles)
        payload.l1_timeline_summary = build_timeline_summary(
            question=request.query,
            evidence_bundles=payload.l1_evidence_bundles,
        )
        payload.trace["l1_timeline_summary_count"] = len(payload.l1_timeline_summary)
        payload.trace["l2_entity_card_count"] = len(payload.l2_entity_cards)
        payload.trace["l2_relationship_count"] = len(payload.l2_relationships)
        payload.trace["l2_assertion_count"] = len(payload.l2_assertions)

        return payload

    @staticmethod
    def _plan_signature(plan: Any) -> tuple[str, str, bool]:
        """Build a stable identity for a layer query plan."""
        content_query = getattr(getattr(plan, "conditions", None), "content_query", "") or ""
        return (str(getattr(plan, "layer", "")), str(content_query), bool(getattr(plan, "is_fallback", False)))

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

        if l1_store and (self._l1 is None or self._l1._store is not l1_store):
            self._l1 = L1Handler(l1_store, self._config, l2_store=l2_store)
        elif not l1_store:
            self._l1 = None

        if l2_store and (self._l2 is None):
            self._l2 = self._build_l2_handler(self._memory)
        elif not l2_store:
            self._l2 = None

        if l3_store and (self._l3 is None or self._l3._store is not l3_store):
            self._l3 = L3Handler(l3_store, self._config)
        elif not l3_store:
            self._l3 = None

        if l4_store and (self._l4 is None or self._l4._store is not l4_store):
            self._l4 = L4Handler(l4_store, self._config)
        elif not l4_store:
            self._l4 = None

    @staticmethod
    def _build_l2_handler(memory: Any) -> L2Handler:
        """Construct L2Handler with embedding infra when available."""
        catalog = getattr(memory, "l2_entity_catalog", None)
        embedding_service = getattr(catalog, "_embedding_service", None) if catalog else None
        edge_vector_index = None
        if embedding_service is not None:
            from ..embedding.sqlite_vec_index import SqliteVecIndex

            db_path = str(getattr(catalog, "db_path", ""))
            if db_path:
                edge_vector_index = SqliteVecIndex(
                    db_path=db_path,
                    registry_table="l2_edge_vectors",
                    entity_column="entity_id",
                    vec_table_prefix="l2_edge_vec",
                )
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
        return (
            len(payload.l1_events)
            + len(payload.l2_entity_cards)
            + len(payload.l2_relationships)
            + len(payload.l2_assertions)
            + len(payload.l3_reflections)
            + len(payload.l4_procedures)
        )

    async def _run_query_expansion(
        self,
        *,
        original_query: str,
        request: RetrievalQuery,
        payload: RetrievalPayload,
        time_range: Optional[TimeRange] = None,
    ) -> None:
        """Generate expanded query variants and run additional L1 plans."""
        from .query_expander import QueryExpander

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
                    l1=self._l1, l2=self._l2, l3=self._l3, l4=self._l4,
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
        if decision_source != "llm":
            return None
        if HybridRetrievalService._count_results(payload) == 0:
            return "empty_primary"

        # L2 entity cards alone are not actionable evidence; if no other layer
        # produced concrete data, fall back so L1 full-text search can try.
        actionable_count = (
            len(payload.l1_events)
            + len(payload.l2_relationships)
            + len(payload.l2_assertions)
            + len(payload.l3_reflections)
            + len(payload.l4_procedures)
        )
        if actionable_count == 0:
            return "l2_entity_card_only"

        # When the LLM routed entirely to L2 and L1 has no events, the
        # knowledge graph data alone may be insufficient.  Trigger the
        # backstop so L1 full-text search fills the conversation-context gap.
        if not payload.l1_events:
            return "l1_empty_with_l2_data"

        coverage_spans = extract_quoted_spans(query)
        missing_reason = "missing_quoted_coverage"
        if not coverage_spans:
            coverage_spans = extract_comparison_spans(query)
            missing_reason = "missing_comparison_coverage"
        if not coverage_spans:
            return None

        normalized_events = [
            {
                "event_id": str(event.get("event_id") or ""),
                "content": " ".join(extract_query_tokens(str(event.get("content") or ""))),
                "raw_content": str(event.get("content") or ""),
            }
            for event in payload.l1_events
        ]
        if not normalized_events:
            return missing_reason

        span_matches = {
            span: {
                event["event_id"] or f"idx:{index}"
                for index, event in enumerate(normalized_events)
                if span in event["content"]
            }
            for span in coverage_spans
        }
        if any(not matched_event_ids for matched_event_ids in span_matches.values()):
            return missing_reason
        if missing_reason == "missing_comparison_coverage":
            anchored_span_matches = {
                span: {
                    event["event_id"] or f"idx:{index}"
                    for index, event in enumerate(normalized_events)
                    if span in event["content"] and has_temporal_anchor(event["raw_content"])
                }
                for span in coverage_spans
            }
            if any(not matched_event_ids for matched_event_ids in anchored_span_matches.values()):
                return missing_reason
            distinct_match_count = len({event_id for matched_event_ids in anchored_span_matches.values() for event_id in matched_event_ids})
            if distinct_match_count < len(coverage_spans):
                return missing_reason
        return None

    @staticmethod
    def _comparison_backstop_queries(
        *,
        query: str,
        payload: RetrievalPayload,
        decision_source: str,
    ) -> list[str]:
        comparison_spans = extract_comparison_spans(query)
        if not comparison_spans:
            # Fallback: extract quoted entity names (e.g. 'The Crown' or "Game of Thrones")
            comparison_spans = extract_quoted_spans(query)
        if not comparison_spans:
            return []
        if HybridRetrievalService._count_results(payload) > 0:
            backstop_reason = HybridRetrievalService._rule_backstop_reason(
                query=query,
                payload=payload,
                decision_source=decision_source,
            )
            if backstop_reason not in ("missing_comparison_coverage", "missing_quoted_coverage"):
                return []

        temporal_tokens = [
            token
            for token in extract_query_tokens(query)
            if token in {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
        ]
        temporal_suffix = " ".join(dict.fromkeys(temporal_tokens))
        queries: list[str] = []
        for span in comparison_spans:
            candidate_query = " ".join(part for part in (span, temporal_suffix) if part).strip()
            if candidate_query and candidate_query not in queries:
                queries.append(candidate_query)
        return queries

    async def _build_l1_evidence_bundles(
        self,
        hits: List[Dict[str, Any]],
        *,
        query: str = "",
    ) -> List[Dict[str, Any]]:
        """Group L1 hits into session-local evidence bundles with lightweight neighbors."""
        if not hits or getattr(self._memory, "l1", None) is None:
            return []

        grouped_hits: Dict[str, List[Dict[str, Any]]] = {}
        for hit in hits:
            session_id = str(hit.get("session_id") or "").strip()
            if not session_id:
                continue
            grouped_hits.setdefault(session_id, []).append(hit)

        neighbor_window = self._bundle_neighbor_window(query)
        bundles: List[Dict[str, Any]] = []

        # Load session events in parallel instead of sequentially
        session_ids = list(grouped_hits.keys())
        session_limits = [max(len(grouped_hits[sid]) * 8, 24) for sid in session_ids]
        session_events_list = await asyncio.gather(
            *(
                self._load_session_events(sid, limit=lim)
                for sid, lim in zip(session_ids, session_limits)
            ),
        )

        for session_id, session_events in zip(session_ids, session_events_list):
            session_hits = grouped_hits[session_id]
            bundle_events, neighbor_expansion_applied = self._select_bundle_events(
                session_events=session_events,
                session_hits=session_hits,
                neighbor_window=neighbor_window,
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
        neighbor_window: int = 1,
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
            if any(abs(turn_number - hit_turn_number) <= max(neighbor_window, 0) for hit_turn_number in hit_turn_numbers):
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
    def _bundle_neighbor_window(_query: str) -> int:
        """Return the neighbor turn window for evidence bundle assembly."""
        return 5

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
