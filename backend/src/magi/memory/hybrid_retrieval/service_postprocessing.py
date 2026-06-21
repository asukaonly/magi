"""Post-processing helpers for the hybrid retrieval service."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Protocol, cast

from .models import RetrievalPayload, RetrievalQuery
from .service_policy import count_payload_results
from .timeline_condense import build_timeline_summary

logger = logging.getLogger(__name__)


class _HybridRetrievalPostProcessingHostProtocol(Protocol):
    _config: Any
    _llm_provider_bridge: Any
    _manifest_selector: Any
    _memory: Any
    _result_fusion: Any

    async def _build_l1_evidence_bundles(
        self,
        events: List[Dict[str, Any]],
        *,
        query: str,
        user_id: str | None = None,
    ) -> List[Dict[str, Any]]: ...


class HybridRetrievalPostProcessingMixin:
    """Fusion, manifest selection, evidence bundle, and payload merge helpers."""

    async def _supplement_activity_summary(
        self,
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
        time_range: Any,
    ) -> None:
        """Backfill L3 reflections by summary_category for activity_summary queries."""
        host = cast(_HybridRetrievalPostProcessingHostProtocol, self)
        l3_handler = getattr(host, "_l3", None)
        l3_store = getattr(l3_handler, "_store", None)
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
            summary_id = str(summary.get("summary_id") or "")
            if summary_id and summary_id in existing_ids:
                continue
            payload.l3_reflections.append(summary)

    async def _apply_post_processing(
        self,
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        mode_plan: Any = None,
    ) -> RetrievalPayload:
        """Apply fusion, manifest selection, evidence bundling, and timeline summary."""
        host = cast(_HybridRetrievalPostProcessingHostProtocol, self)
        pre_fusion_l1_events = list(payload.l1_events)

        payload = host._result_fusion.apply(payload, max_tokens=host._config.default_max_tokens)

        if host._config.manifest_selector_enabled:
            payload = await host._manifest_selector.select(
                payload, query=request.query, llm_bridge=host._llm_provider_bridge,
            )

        payload.l1_evidence_bundles = await host._build_l1_evidence_bundles(
            pre_fusion_l1_events,
            query=request.query,
            user_id=request.user_id,
        )
        payload.trace["l1_evidence_bundle_count"] = len(payload.l1_evidence_bundles)
        payload.trace["l1_evidence_bundle_sessions_total"] = len(
            {str(hit.get("session_id") or "").strip() for hit in pre_fusion_l1_events if hit.get("session_id")}
        )
        payload.l1_timeline_summary = build_timeline_summary(
            question=request.query,
            evidence_bundles=payload.l1_evidence_bundles,
        )
        payload.trace["l1_timeline_summary_count"] = len(payload.l1_timeline_summary)
        payload.trace["l2_entity_card_count"] = len(payload.l2_entity_cards)
        payload.trace["l2_relationship_count"] = len(payload.l2_relationships)
        payload.trace["l2_assertion_count"] = len(payload.l2_assertions)
        payload.trace["layer_result_counts"] = self._layer_result_counts(payload)
        payload.trace["final_result_count"] = self._count_results(payload)

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

    async def _load_l0(self, session_id: str) -> List[Dict[str, Any]]:
        """Load L0 workbench data."""
        host = cast(_HybridRetrievalPostProcessingHostProtocol, self)
        try:
            projection = await host._memory.l0.get_prompt_workbench_projection(session_id)
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
        """Count total non-L0 retrieval results."""
        return count_payload_results(payload)

    @staticmethod
    def _append_plan_trace(payload: RetrievalPayload, record: dict[str, Any]) -> None:
        plan_trace = payload.trace.setdefault("plan_executions", [])
        if isinstance(plan_trace, list):
            plan_trace.append(record)

        layer = str(record.get("layer") or "")
        if not layer:
            return
        executed_layers = payload.trace.setdefault("executed_layers", [])
        if isinstance(executed_layers, list) and layer not in executed_layers:
            executed_layers.append(layer)
        layer_plan_counts = payload.trace.setdefault("layer_plan_result_counts", {})
        if isinstance(layer_plan_counts, dict):
            layer_plan_counts[layer] = int(layer_plan_counts.get(layer, 0) or 0) + int(record.get("count") or 0)

    @staticmethod
    def _count_plan_result(layer: str, result: Any) -> int:
        if layer in {"L1", "L3", "L4"}:
            return len(result) if isinstance(result, list) else 0
        if layer == "L2" and isinstance(result, dict):
            return sum(
                len(result.get(key, []))
                for key in (
                    "entity_cards",
                    "relationships",
                    "assertions",
                    "episodes",
                    "state_facts",
                    "state_history",
                )
            )
        return 0

    @staticmethod
    def _layer_result_counts(payload: RetrievalPayload) -> dict[str, int]:
        return {
            "L1": len(payload.l1_events),
            "L2": (
                len(payload.l2_entity_cards)
                + len(payload.l2_relationships)
                + len(payload.l2_assertions)
                + len(payload.l2_episodes)
                + len(payload.l2_state_facts)
                + len(payload.l2_state_history)
            ),
            "L3": len(payload.l3_reflections),
            "L4": len(payload.l4_procedures),
        }


__all__ = ["HybridRetrievalPostProcessingMixin"]
