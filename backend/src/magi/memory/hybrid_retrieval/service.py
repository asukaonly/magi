"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ...config import AppConfig
from .handlers import L1Handler, L2Handler, L3Handler, L4Handler, execute_plan
from .evidence.session_bundles import EvidenceBundleMixin
from .intent_decider import IntentDecider, LLMIntentDecider, RuleBasedIntentDecider
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
