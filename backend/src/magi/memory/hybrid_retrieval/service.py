"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

import logging
from dataclasses import replace as dc_replace
from typing import Any, Callable, Dict, List, Optional

from ...config import AppConfig
from .handlers import L1Handler, L2Handler, L3Handler, L4Handler, execute_plan
from .evidence.session_bundles import EvidenceBundleMixin
from .indexical_resolver import resolve as resolve_indexical
from .intent_decider import IntentDecider, LLMIntentDecider, RuleBasedIntentDecider
from .mode_inference import infer_query_mode
from .mode_registry import MODE_REGISTRY, VALID_MODES
from .router import normalize_query_mode
from .models import (
    IntentDeciderInput,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
)
from .manifest_selector import ManifestSelector
from .result_fusion import ResultFusion
from .service_execution import HybridRetrievalExecutionMixin
from .service_postprocessing import HybridRetrievalPostProcessingMixin

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


class HybridRetrievalService(
    EvidenceBundleMixin,
    HybridRetrievalPostProcessingMixin,
    HybridRetrievalExecutionMixin,
):
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

    @property
    def memory_db_path(self) -> Optional[str]:
        """Path to the shared memory SQLite database.

        Exposed for downstream consumers (e.g. the memory_query tool) that
        need to perform direct lookups against catalog tables alongside the
        retrieval payload. Returns ``None`` when the underlying unified
        memory does not expose a database path (e.g. test doubles).
        """
        return getattr(self._memory, "memory_db_path", None)

    async def query(self, request: RetrievalQuery) -> RetrievalPayload:
        """Execute a layer-aware retrieval query."""
        self._refresh_runtime_config()
        self._refresh_handlers()

        # Capture original caller intent BEFORE any inference / indexical
        # override mutates request.query_mode. This flag — combined with the
        # indexical-override flag below — gates RRF profile selection further
        # down. Heuristic-inferred modes (Phase 4) must NOT distort RRF
        # weights; only caller-authored modes (or the high-confidence
        # indexical resolver) are authoritative enough to swap profiles.
        caller_supplied_query_mode = bool(request.query_mode)

        # 0. Indexical resolution — must run BEFORE the intent decider so its
        #    overrides are authoritative. When a query contains an indexical
        #    cue (e.g. '当时', 'just now') AND conversation context exists,
        #    force episode_recall mode (which routes to L1 conversation_only
        #    via mode_plan.l1_retrieval_scopes). dataclasses.replace keeps the
        #    caller's request object untouched.
        #
        #    Design correction (2026-05-22): the resolver no longer mutates
        #    request.time_range. '当时/那时/上次' typically reference deep
        #    historical context, not the immediate prior turn ±2min. L1
        #    content matching (BM25 + vector) finds the actually-referenced
        #    events across all conversation history. See
        #    indexical_resolver.py module docstring for the full rationale.
        indexical = resolve_indexical(
            query=request.query,
            conversation_context=request.conversation_context,
        )
        indexical_trace: Dict[str, Any] = {}
        if indexical.is_indexical:
            request = dc_replace(
                request,
                query_mode=indexical.force_mode,
            )
            indexical_trace["indexical_resolved"] = True
            indexical_trace["indexical_cue"] = indexical.cue_matched
        elif indexical.cue_matched:
            indexical_trace["indexical_cue_orphaned"] = indexical.cue_matched

        # 0b. Mode source resolution — runs AFTER the indexical block so the
        #     resolver's authoritative override wins. Three branches:
        #       - indexical_override : Phase 3 already set request.query_mode.
        #       - caller             : caller supplied a non-empty query_mode.
        #       - inferred           : caller omitted it; run the heuristic
        #                              inference module and apply the result.
        if indexical.is_indexical:
            indexical_trace["mode_source"] = "indexical_override"
        elif request.query_mode:
            indexical_trace["mode_source"] = "caller"
        else:
            inferred_mode = infer_query_mode(query=request.query)
            request = dc_replace(request, query_mode=inferred_mode)
            indexical_trace["mode_source"] = "inferred"
            indexical_trace["inferred_mode"] = inferred_mode

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
                "requested_query_mode": raw_query_mode or None,
                "resolved_query_mode": resolved_mode,
                "sources": request.source_filters,
                "domains": request.domain_filters,
            }
        )
        if indexical_trace:
            payload.trace.update(indexical_trace)

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
        if not mode_explicit:
            inferred_mode = self._infer_mode_from_plans(decision.plans, resolved_mode)
            if inferred_mode != resolved_mode:
                payload.trace["mode_auto_inferred"] = True
            resolved_mode = inferred_mode
            mode_plan = MODE_REGISTRY.get(resolved_mode, mode_plan)
            payload.trace["query_mode"] = resolved_mode
            payload.trace["resolved_query_mode"] = resolved_mode
        payload.trace["intent_source"] = decision.source
        payload.trace["intent_reasoning"] = decision.reasoning
        payload.trace["planned_layers"] = [
            {"layer": plan.layer, "fallback": plan.is_fallback}
            for plan in decision.plans
        ]

        # 4. Build mode-adapted L1 handler with RRF weights from mode plan.
        #    Only apply RRF overrides when the mode is AUTHORITATIVE:
        #      - caller-supplied (tool call / API caller chose this mode), OR
        #      - indexical-override (Phase 3 resolver fired with confidence
        #        >= 0.9 on an indexical cue).
        #    Heuristic-inferred modes (Phase 4 infer_query_mode) MUST NOT
        #    drive RRF profile selection — keyword-heuristic errors would
        #    distort retrieval. They still route to the right layers but use
        #    default RRF weights.
        effective_l1 = self._l1
        authoritative_mode = caller_supplied_query_mode or indexical.is_indexical
        if (
            authoritative_mode
            and mode_explicit
            and mode_plan.rrf_profile
            and self._l1 is not None
        ):
            adapted_config = dc_replace(
                self._config,
                **{k: v for k, v in mode_plan.rrf_profile.items() if hasattr(self._config, k)},
            )
            if adapted_config is not self._config:
                effective_l1 = self._l1.with_config(adapted_config)
                payload.trace["mode_rrf_applied"] = True
        if effective_l1 is not None and mode_plan.l1_retrieval_scopes is not None:
            effective_l1 = effective_l1.with_l1_retrieval_scopes(mode_plan.l1_retrieval_scopes)
            payload.trace["l1_retrieval_scopes"] = list(mode_plan.l1_retrieval_scopes)
        # Indexical resolver's scope override is authoritative — applies after
        # the mode-plan scope so it wins for episode_recall (which has no
        # default L1 scope in the registry). Trace is set even when no L1
        # handler is wired up so the override intent is observable.
        if indexical.is_indexical and indexical.l1_retrieval_scope:
            indexical_scopes = [indexical.l1_retrieval_scope]
            if effective_l1 is not None:
                effective_l1 = effective_l1.with_l1_retrieval_scopes(indexical_scopes)
            payload.trace["l1_retrieval_scopes"] = list(indexical_scopes)
        payload.trace["mode_explicit"] = mode_explicit

        return await self._execute_query(
            request, decision, intent_input, payload,
            effective_l1=effective_l1,
            mode_plan=mode_plan,
        )

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

    @staticmethod
    def _infer_mode_from_plans(plans: List[Any], fallback: str) -> str:
        primary_layers = [plan.layer for plan in plans if not plan.is_fallback]
        fallback_layers = [plan.layer for plan in plans if plan.is_fallback and plan.layer not in primary_layers]
        for mode, plan in MODE_REGISTRY.items():
            if plan.primary_layers == primary_layers and plan.fallback_layers == fallback_layers:
                return mode
        return fallback

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
