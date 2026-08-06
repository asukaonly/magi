"""Hybrid retrieval service for the rewritten memory system."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace as dc_replace
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ...config import AppConfig
from ..context_scope import (
    ContextScopeResolver,
    merge_context_scopes,
    normalize_context_scope,
)
from .correction_evidence_governance import decide_l1_correction_evidence
from .handlers import L1Handler, L2Handler, L3Handler, L4Handler
from .evidence.session_bundles import EvidenceBundleMixin
from .indexical_resolver import resolve as resolve_indexical
from .intent_decider import IntentDecider, LLMIntentDecider, RuleBasedIntentDecider
from .mode_inference import infer_query_mode
from .mode_registry import MODE_REGISTRY, VALID_MODES
from .recall_shape import RecallShape, classify_recall_shape
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


# Round 5 I2: trace keys emitted to ops logs so the routing decisions
# (mode_source, indexical_resolved, etc.) and quality counters
# (dropped_unresolved_entity_count) are visible without dumping
# the payload object. Keep this short — log line, not dump.
_TRACE_KEYS_LOGGED: tuple[str, ...] = (
    "query_mode",
    "mode_source",
    "inferred_mode",
    "indexical_resolved",
    "indexical_cue",
    "indexical_cue_orphaned",
    "mode_rrf_applied",
    "l1_retrieval_scopes",
    "recall_shape",
    "structured_recall",
    "dropped_unresolved_entity_count",
)


@dataclass(frozen=True)
class _QueryModeContext:
    request: RetrievalQuery
    indexical: Any
    indexical_trace: Dict[str, Any]
    resolved_mode: str
    raw_query_mode: str
    mode_explicit: bool
    mode_plan: Any
    caller_supplied_query_mode: bool
    intent_query_mode_hint: str | None


def _log_retrieval_trace(payload: "RetrievalPayload") -> None:
    """Emit selected trace keys to the module logger.

    Trace keys that are unset on a given request are omitted so the line
    stays short and easy to grep. ``dropped_unresolved_entity_count`` is
    only included when > 0 (the projection layer only writes it then).
    """
    trace = getattr(payload, "trace", None) or {}
    if not trace:
        return
    parts: list[str] = []
    for key in _TRACE_KEYS_LOGGED:
        if key not in trace:
            continue
        value = trace[key]
        # Drop falsy values (None, "", [], False, 0) — keeps the line short
        # and ensures dropped_unresolved_entity_count is only emitted when
        # there's actually something dropped.
        if not value:
            continue
        parts.append(f"{key}={value!r}")
    if not parts:
        return
    logger.info("retrieval trace: %s", " ".join(parts))


def build_retrieval_config_from_app_config(app_config: AppConfig) -> RetrievalConfig:
    """Build retrieval config from the runtime app config."""
    reranker = app_config.agent.memory.reranker
    qe = app_config.agent.memory.query_expansion
    gs = app_config.agent.memory.graph_spreading
    return RetrievalConfig(
        reranker_top_k=reranker.top_k,
        cross_encoder_enabled=reranker.cross_encoder.enabled,
        cross_encoder_model_id=reranker.cross_encoder.managed_model_id,
        cross_encoder_variant=reranker.cross_encoder.variant,
        query_expansion_enabled=qe.enabled,
        query_expansion_max_expansions=qe.max_expansions,
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
        memory_db_path = getattr(unified_memory, "memory_db_path", None)
        self._context_scope_resolver = (
            ContextScopeResolver(memory_db_path)
            if isinstance(memory_db_path, str) and memory_db_path.strip()
            else None
        )

        # Build handlers from available stores
        l2_store = unified_memory.l2 if unified_memory.l2 else None
        self._l1 = (
            L1Handler(unified_memory.l1, self._config, l2_store=l2_store)
            if unified_memory.l1
            else None
        )
        self._l2 = self._build_l2_handler(unified_memory) if unified_memory.l2 else None
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

        # Post-retrieval grounding filter. Sits between _execute_query
        # (raw RRF-fused candidate set) and the answer LLM, trims
        # noise so the chat LLM only sees evidence that the cheap
        # filter LLM agrees is relevant. Disabled if no bridge is
        # configured — degrades to "pass raw payload through".
        from .grounding_filter import GroundingFilter

        self._grounding_filter = GroundingFilter(
            llm_bridge=llm_provider_bridge,
            timeout_seconds=getattr(self._config, "grounding_filter_timeout_seconds", 3.0),
            enabled=getattr(self._config, "grounding_filter_enabled", True),
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
        request = await self._resolve_context_scope(request)

        mode_context = self._resolve_query_mode_context(request)
        request = mode_context.request
        payload = self._build_initial_payload(request, mode_context)

        recall_shape = classify_recall_shape(request.query)
        payload.trace["recall_shape"] = recall_shape.to_dict()

        await self._load_l0_workbench_if_available(request, payload)

        intent_input = self._build_intent_input(request, mode_context)
        decision = await self._intent_decider.decide(intent_input)
        _, mode_plan = self._apply_intent_decision(
            decision=decision,
            mode_context=mode_context,
            payload=payload,
        )
        effective_l1 = self._effective_l1_for_mode(
            mode_context=mode_context,
            mode_plan=mode_plan,
            payload=payload,
        )

        result = await self._execute_query(
            request,
            decision,
            intent_input,
            payload,
            effective_l1=effective_l1,
            mode_plan=mode_plan,
        )
        return await self._finalize_query_result(
            request=request,
            recall_shape=recall_shape,
            payload=result,
        )

    async def _resolve_context_scope(self, request: RetrievalQuery) -> RetrievalQuery:
        """Resolve every retrieval caller through the same local context path."""
        explicit_scope = normalize_context_scope(request.context_scope)
        resolved_scope: dict[str, Any] = {}
        if self._context_scope_resolver is not None and request.context_signals is not None:
            try:
                resolved_scope = await self._context_scope_resolver.resolve(request.context_signals)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "automatic context resolution failed; using explicit or global scope "
                    "(error_type=%s)",
                    type(exc).__name__,
                )
        explicit_dimensions = {str(item["dimension"]) for item in explicit_scope.get("all_of", [])}
        compatible_resolved_conditions = [
            item
            for item in resolved_scope.get("all_of", [])
            if str(item["dimension"]) not in explicit_dimensions
        ]
        compatible_resolved_scope = (
            {"all_of": compatible_resolved_conditions} if compatible_resolved_conditions else {}
        )
        return dc_replace(
            request,
            context_scope=merge_context_scopes(
                explicit_scope,
                compatible_resolved_scope,
            ),
        )

    def _resolve_query_mode_context(self, request: RetrievalQuery) -> _QueryModeContext:
        caller_supplied_query_mode = bool(request.query_mode)
        request, indexical, indexical_trace = self._apply_indexical_resolution(request)
        request, indexical_trace = self._apply_mode_source_resolution(
            request,
            indexical=indexical,
            indexical_trace=indexical_trace,
        )
        resolved_mode = normalize_query_mode(request.query_mode)
        mode_explicit = resolved_mode is not None and resolved_mode in VALID_MODES
        if not mode_explicit:
            resolved_mode = "exact_fact"
        raw_query_mode = str(request.query_mode or "").strip().lower()
        intent_query_mode_hint = (
            "graph" if raw_query_mode == "graph" else (resolved_mode if mode_explicit else None)
        )
        return _QueryModeContext(
            request=request,
            indexical=indexical,
            indexical_trace=indexical_trace,
            resolved_mode=resolved_mode,
            raw_query_mode=raw_query_mode,
            mode_explicit=mode_explicit,
            mode_plan=MODE_REGISTRY[resolved_mode],
            caller_supplied_query_mode=caller_supplied_query_mode,
            intent_query_mode_hint=intent_query_mode_hint,
        )

    @staticmethod
    def _apply_indexical_resolution(
        request: RetrievalQuery,
    ) -> tuple[RetrievalQuery, Any, Dict[str, Any]]:
        indexical = resolve_indexical(
            query=request.query,
            conversation_context=request.conversation_context,
        )
        indexical_trace: Dict[str, Any] = {}
        if indexical.is_indexical:
            request = dc_replace(request, query_mode=indexical.force_mode)
            indexical_trace["indexical_resolved"] = True
            indexical_trace["indexical_cue"] = indexical.cue_matched
        elif indexical.cue_matched:
            indexical_trace["indexical_cue_orphaned"] = indexical.cue_matched
        return request, indexical, indexical_trace

    @staticmethod
    def _apply_mode_source_resolution(
        request: RetrievalQuery,
        *,
        indexical: Any,
        indexical_trace: Dict[str, Any],
    ) -> tuple[RetrievalQuery, Dict[str, Any]]:
        if indexical.is_indexical:
            indexical_trace["mode_source"] = "indexical_override"
        elif request.query_mode:
            indexical_trace["mode_source"] = "caller"
        else:
            inferred_mode = infer_query_mode(query=request.query)
            request = dc_replace(request, query_mode=inferred_mode)
            indexical_trace["mode_source"] = "inferred"
            indexical_trace["inferred_mode"] = inferred_mode
        return request, indexical_trace

    @staticmethod
    def _build_initial_payload(
        request: RetrievalQuery,
        mode_context: _QueryModeContext,
    ) -> RetrievalPayload:
        payload = RetrievalPayload(
            trace={
                "query": request.query,
                "query_mode": mode_context.resolved_mode,
                "requested_query_mode": mode_context.raw_query_mode or None,
                "resolved_query_mode": mode_context.resolved_mode,
                "sources": request.source_filters,
                "domains": request.domain_filters,
                "context_scope": dict(request.context_scope or {}),
            }
        )
        if mode_context.indexical_trace:
            payload.trace.update(mode_context.indexical_trace)
        return payload

    async def _load_l0_workbench_if_available(
        self,
        request: RetrievalQuery,
        payload: RetrievalPayload,
    ) -> None:
        if request.session_id and self._memory.l0 is not None:
            payload.l0_workbench = await self._load_l0(
                request.session_id,
                query=request.query,
            )

    @staticmethod
    def _build_intent_input(
        request: RetrievalQuery,
        mode_context: _QueryModeContext,
    ) -> IntentDeciderInput:
        return IntentDeciderInput(
            query=request.query,
            user_id=request.user_id,
            session_id=request.session_id,
            raw_time_range=request.time_range if request.time_range else None,
            source_filters=request.source_filters,
            domain_filters=request.domain_filters,
            summary_categories=list(request.summary_categories or []),
            context_scope=dict(request.context_scope or {}),
            query_mode_hint=mode_context.intent_query_mode_hint,
            l1_limit=request.limit,
        )

    def _apply_intent_decision(
        self,
        *,
        decision: Any,
        mode_context: _QueryModeContext,
        payload: RetrievalPayload,
    ) -> tuple[str, Any]:
        resolved_mode = mode_context.resolved_mode
        mode_plan = mode_context.mode_plan
        if not mode_context.mode_explicit:
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
            {"layer": plan.layer, "fallback": plan.is_fallback} for plan in decision.plans
        ]
        return resolved_mode, mode_plan

    def _effective_l1_for_mode(
        self,
        *,
        mode_context: _QueryModeContext,
        mode_plan: Any,
        payload: RetrievalPayload,
    ) -> L1Handler | None:
        effective_l1 = self._l1
        authoritative_mode = (
            mode_context.caller_supplied_query_mode or mode_context.indexical.is_indexical
        )
        if (
            authoritative_mode
            and mode_context.mode_explicit
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
        if mode_context.indexical.is_indexical and mode_context.indexical.l1_retrieval_scope:
            indexical_scopes = [mode_context.indexical.l1_retrieval_scope]
            if effective_l1 is not None:
                effective_l1 = effective_l1.with_l1_retrieval_scopes(indexical_scopes)
            payload.trace["l1_retrieval_scopes"] = list(indexical_scopes)
        payload.trace["mode_explicit"] = mode_context.mode_explicit
        return effective_l1

    async def _finalize_query_result(
        self,
        *,
        request: RetrievalQuery,
        recall_shape: RecallShape,
        payload: RetrievalPayload,
    ) -> RetrievalPayload:
        payload = await self._grounding_filter.apply(payload, request)
        payload = await self._apply_structured_recall(
            request=request,
            recall_shape=recall_shape,
            payload=payload,
        )
        _log_retrieval_trace(payload)
        return payload

    async def _apply_structured_recall(
        self,
        *,
        request: RetrievalQuery,
        recall_shape: RecallShape,
        payload: RetrievalPayload,
    ) -> RetrievalPayload:
        if (
            recall_shape.domain_hint not in {"photo", "browser", "music"}
            or recall_shape.desired_coverage != "exhaustive"
        ):
            return payload
        l1_store = getattr(self._memory, "l1", None)
        if l1_store is None:
            payload.trace["structured_recall"] = "skipped:l1_missing"
            return payload
        try:
            event_id_blocklist = self._structured_recall_event_id_blocklist(
                payload,
                query_mode=request.query_mode,
            )
            if recall_shape.domain_hint == "photo":
                from ..structured_recall.photo import expand_photo_structured_recall

                result = await expand_photo_structured_recall(
                    l1_store=l1_store,
                    request=request,
                    recall_shape=recall_shape,
                    payload=payload,
                    event_id_blocklist=event_id_blocklist,
                )
            else:
                from ..structured_recall.generic import expand_generic_structured_recall

                result = await expand_generic_structured_recall(
                    l1_store=l1_store,
                    request=request,
                    recall_shape=recall_shape,
                    payload=payload,
                    event_id_blocklist=event_id_blocklist,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("structured recall failed: %s", exc, exc_info=True)
            payload.trace["structured_recall"] = "failed"
            return payload
        if result is None:
            payload.trace["structured_recall"] = "miss"
            return payload
        payload.structured_results.append(result)
        payload.trace["structured_recall"] = recall_shape.domain_hint
        return payload

    def _structured_recall_event_id_blocklist(
        self,
        payload: RetrievalPayload,
        *,
        query_mode: str | None,
    ) -> Callable[[list[str]], Awaitable[set[str]]] | None:
        mode = str(
            payload.trace.get("resolved_query_mode")
            or payload.trace.get("query_mode")
            or normalize_query_mode(query_mode)
            or ""
        )
        mode_plan = MODE_REGISTRY.get(mode)
        retrieval_scopes = set(getattr(mode_plan, "l1_retrieval_scopes", None) or [])
        if "fact_authoritative" not in retrieval_scopes:
            return None
        l2_store = getattr(self._memory, "l2", None)

        async def blocklist(event_ids: list[str]) -> set[str]:
            decision = await decide_l1_correction_evidence(
                l2_store,
                event_ids,
            )
            payload.trace["structured_recall_correction_governance"] = decision.status
            if decision.reason is not None:
                payload.trace["structured_recall_correction_governance_reason"] = decision.reason
            payload.trace["structured_recall_correction_governance_dropped_count"] = (
                len(event_ids)
                if decision.drop_all
                else sum(
                    1
                    for event_id in event_ids
                    if not str(event_id).strip()
                    or str(event_id).strip() in decision.blocked_event_ids
                )
            )
            if decision.drop_all:
                raise RuntimeError("Structured recall correction governance failed closed")
            return set(decision.blocked_event_ids)

        return blocklist

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
            l1_store=getattr(memory, "l1", None),
        )

    @staticmethod
    def _infer_mode_from_plans(plans: List[Any], fallback: str) -> str:
        primary_layers = [plan.layer for plan in plans if not plan.is_fallback]
        fallback_layers = [
            plan.layer for plan in plans if plan.is_fallback and plan.layer not in primary_layers
        ]
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
