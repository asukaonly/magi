"""Post-processing helpers for the hybrid retrieval service."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Protocol, cast

from ...utils.diagnostic_logging import full_content_logging_enabled
from .correction_evidence_governance import decide_l1_correction_evidence
from .debug_detail import DETAIL_LIMIT, event_records, log_detail
from .models import RetrievalPayload, RetrievalQuery
from .service_policy import count_payload_results
from .timeline_condense import build_timeline_summary

logger = logging.getLogger(__name__)

_HISTORICAL_L1_EVENT_MODES = frozenset(
    {"event_stream", "episode_recall", "experience_recall"}
)


@dataclass(frozen=True)
class FusionAudit:
    pre_counts: Dict[str, int]
    post_counts: Dict[str, int]
    pre_l1_events: List[Dict[str, Any]]
    pre_l1_unique: List[Dict[str, Any]]
    dropped_l1_events: List[Dict[str, Any]]


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


def _dedupe_l1_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique_events: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in events:
        event_id = str(item.get("event_id") or "")
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        unique_events.append(item)
    return unique_events


def _dropped_l1_events(
    pre_fusion_events: List[Dict[str, Any]],
    post_fusion_events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    post_fusion_ids = {str(item.get("event_id") or "") for item in post_fusion_events}
    return [
        item
        for item in _dedupe_l1_events(pre_fusion_events)
        if str(item.get("event_id") or "") not in post_fusion_ids
    ]


def _fusion_detail(
    request: RetrievalQuery,
    payload: RetrievalPayload,
    *,
    host: _HybridRetrievalPostProcessingHostProtocol,
    audit: FusionAudit,
) -> Dict[str, Any]:
    return {
        "query": request.query,
        "max_tokens": host._config.default_max_tokens,
        "pre_counts": audit.pre_counts,
        "post_counts": audit.post_counts,
        "pre_l1_count": len(audit.pre_l1_events),
        "pre_l1_unique_count": len(audit.pre_l1_unique),
        "post_l1_count": len(payload.l1_events),
        "dropped_l1_count": len(audit.dropped_l1_events),
        "pre_l1_events": event_records(audit.pre_l1_unique, limit=DETAIL_LIMIT),
        "post_l1_events": event_records(payload.l1_events, limit=DETAIL_LIMIT),
        "dropped_l1_events": event_records(audit.dropped_l1_events, limit=DETAIL_LIMIT),
    }


def _session_ids(events: List[Dict[str, Any]]) -> set[str]:
    return {str(hit.get("session_id") or "").strip() for hit in events if hit.get("session_id")}


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
        await self._apply_l1_event_semantics(
            payload,
            mode_plan=mode_plan,
            host=host,
        )
        await self._apply_l1_correction_governance(
            payload,
            mode_plan=mode_plan,
            host=host,
        )
        payload, fusion_audit = self._apply_result_fusion(
            payload,
            request=request,
            host=host,
        )
        payload = await self._select_manifest_if_enabled(
            payload,
            request=request,
            host=host,
        )
        await self._attach_l1_evidence(
            payload,
            request=request,
            host=host,
            pre_fusion_l1_events=fusion_audit.pre_l1_events,
        )
        self._update_post_processing_trace(payload)
        self._apply_mode_reducer(payload, request=request, mode_plan=mode_plan)
        self._log_post_processing_completed(payload, request=request)
        return payload

    async def _apply_l1_event_semantics(
        self,
        payload: RetrievalPayload,
        *,
        mode_plan: Any,
        host: _HybridRetrievalPostProcessingHostProtocol,
    ) -> None:
        """Mark narrative L1 evidence as a historical record, not a current fact."""
        mode = str(getattr(mode_plan, "mode", "") or "")
        if mode not in _HISTORICAL_L1_EVENT_MODES or not payload.l1_events:
            return
        corrected_event_ids: frozenset[str] = frozenset()
        l2_store = getattr(host._memory, "l2", None)
        db_path = getattr(l2_store, "db_path", None)
        lookup = getattr(l2_store, "active_correction_evidence_event_ids", None)
        if (
            l2_store is not None
            and isinstance(db_path, str)
            and db_path.strip()
            and callable(lookup)
        ):
            decision = await decide_l1_correction_evidence(
                l2_store,
                [str(event.get("event_id") or "") for event in payload.l1_events],
            )
            if not decision.drop_all:
                corrected_event_ids = decision.blocked_event_ids
                payload.trace["l1_historical_correction_annotation"] = "applied"
            else:
                payload.trace["l1_historical_correction_annotation"] = "unavailable"
        else:
            payload.trace["l1_historical_correction_annotation"] = "unavailable"
        payload.l1_events = [
            {
                **event,
                "evidence_semantics": "historical_record",
                **(
                    {"correction_status": "later_corrected"}
                    if str(event.get("event_id") or "").strip()
                    in corrected_event_ids
                    else {}
                ),
            }
            for event in payload.l1_events
        ]
        payload.trace["l1_event_semantics"] = "historical_record"
        payload.trace["l1_historical_corrected_event_count"] = sum(
            1
            for event in payload.l1_events
            if event.get("correction_status") == "later_corrected"
        )

    async def _apply_l1_correction_governance(
        self,
        payload: RetrievalPayload,
        *,
        mode_plan: Any,
        host: _HybridRetrievalPostProcessingHostProtocol,
    ) -> None:
        """Defer corrected fact evidence to the governed L2 interpretation."""
        retrieval_scopes = set(getattr(mode_plan, "l1_retrieval_scopes", None) or [])
        if "fact_authoritative" not in retrieval_scopes or not payload.l1_events:
            return
        original_count = len(payload.l1_events)
        decision = await decide_l1_correction_evidence(
            getattr(host._memory, "l2", None),
            [str(event.get("event_id") or "") for event in payload.l1_events],
        )
        payload.trace["l1_correction_governance"] = decision.status
        if decision.reason is not None:
            payload.trace["l1_correction_governance_reason"] = decision.reason
        if not decision.blocked_event_ids and not decision.missing_event_id_count:
            return
        payload.trace["l1_correction_governance_granularity"] = "event"
        if decision.drop_all:
            payload.l1_events = []
        else:
            payload.l1_events = [
                event
                for event in payload.l1_events
                if str(event.get("event_id") or "").strip()
                and str(event.get("event_id") or "").strip()
                not in decision.blocked_event_ids
            ]
        payload.trace["l1_correction_governance_dropped_count"] = (
            original_count - len(payload.l1_events)
        )

    def _apply_result_fusion(
        self,
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        host: _HybridRetrievalPostProcessingHostProtocol,
    ) -> tuple[RetrievalPayload, FusionAudit]:
        pre_counts = self._layer_result_counts(payload)
        pre_l1_events = list(payload.l1_events)
        payload = host._result_fusion.apply(payload, max_tokens=host._config.default_max_tokens)
        fusion_audit = FusionAudit(
            pre_counts=pre_counts,
            post_counts=self._layer_result_counts(payload),
            pre_l1_events=pre_l1_events,
            pre_l1_unique=_dedupe_l1_events(pre_l1_events),
            dropped_l1_events=_dropped_l1_events(pre_l1_events, payload.l1_events),
        )
        self._log_result_fusion(payload, request=request, host=host, audit=fusion_audit)
        return payload, fusion_audit

    def _log_result_fusion(
        self,
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        host: _HybridRetrievalPostProcessingHostProtocol,
        audit: FusionAudit,
    ) -> None:
        query_log = (
            request.query
            if full_content_logging_enabled()
            else f"[content omitted; {len(request.query)} chars]"
        )
        logger.debug(
            "Retrieval result fusion applied | query=%r pre_counts=%s post_counts=%s "
            "l1_event_ids_sample=%s",
            query_log,
            audit.pre_counts,
            self._layer_result_counts(payload),
            [str(item.get("event_id") or "") for item in payload.l1_events[:10]],
        )
        log_detail(
            logger,
            "RETRIEVAL FUSION DETAIL",
            _fusion_detail(request, payload, host=host, audit=audit),
        )

    async def _select_manifest_if_enabled(
        self,
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        host: _HybridRetrievalPostProcessingHostProtocol,
    ) -> RetrievalPayload:
        if not host._config.manifest_selector_enabled:
            return payload
        return await host._manifest_selector.select(
            payload,
            query=request.query,
            llm_bridge=host._llm_provider_bridge,
        )

    async def _attach_l1_evidence(
        self,
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        host: _HybridRetrievalPostProcessingHostProtocol,
        pre_fusion_l1_events: List[Dict[str, Any]],
    ) -> None:
        payload.l1_evidence_bundles = await host._build_l1_evidence_bundles(
            pre_fusion_l1_events,
            query=request.query,
            user_id=request.user_id,
        )
        payload.trace["l1_evidence_bundle_count"] = len(payload.l1_evidence_bundles)
        payload.trace["l1_evidence_bundle_sessions_total"] = len(_session_ids(pre_fusion_l1_events))
        payload.l1_timeline_summary = build_timeline_summary(
            question=request.query,
            evidence_bundles=payload.l1_evidence_bundles,
        )

    def _update_post_processing_trace(self, payload: RetrievalPayload) -> None:
        payload.trace["l1_timeline_summary_count"] = len(payload.l1_timeline_summary)
        payload.trace["l2_entity_card_count"] = len(payload.l2_entity_cards)
        payload.trace["l2_relationship_count"] = len(payload.l2_relationships)
        payload.trace["l2_assertion_count"] = len(payload.l2_assertions)
        payload.trace["l2_experience_count"] = len(payload.l2_experiences)
        payload.trace["layer_result_counts"] = self._layer_result_counts(payload)
        payload.trace["final_result_count"] = self._count_results(payload)

    @staticmethod
    def _apply_mode_reducer(
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
        mode_plan: Any = None,
    ) -> None:
        if mode_plan is None:
            return
        from .evidence import ASSEMBLER_REGISTRY
        from .reducers import REDUCER_REGISTRY

        assembler = ASSEMBLER_REGISTRY.get(mode_plan.evidence_shape)
        reducer = REDUCER_REGISTRY.get(mode_plan.reducer_type)
        if assembler is None or reducer is None:
            return
        evidence = assembler.assemble(payload, request)
        reduced = reducer.reduce(evidence)
        payload.trace["evidence_shape"] = mode_plan.evidence_shape
        payload.trace["reducer_type"] = mode_plan.reducer_type
        payload.trace["evidence_reduced"] = reduced

    @staticmethod
    def _log_post_processing_completed(
        payload: RetrievalPayload,
        *,
        request: RetrievalQuery,
    ) -> None:
        query_log = (
            request.query
            if full_content_logging_enabled()
            else f"[content omitted; {len(request.query)} chars]"
        )
        logger.debug(
            "Retrieval post-processing completed | query=%r layer_counts=%s "
            "final_result_count=%d l1_evidence_bundle_count=%d "
            "l1_timeline_summary_count=%d evidence_shape=%s reducer_type=%s",
            query_log,
            payload.trace["layer_result_counts"],
            payload.trace["final_result_count"],
            payload.trace["l1_evidence_bundle_count"],
            payload.trace["l1_timeline_summary_count"],
            payload.trace.get("evidence_shape"),
            payload.trace.get("reducer_type"),
        )

    async def _load_l0(
        self,
        session_id: str,
        *,
        query: str,
    ) -> List[Dict[str, Any]]:
        """Load L0 workbench data."""
        host = cast(_HybridRetrievalPostProcessingHostProtocol, self)
        try:
            projection = await host._memory.l0.get_prompt_workbench_projection(
                session_id,
                query=query,
            )
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
                payload.l2_experiences.extend(result.get("experiences", []))
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
            layer_plan_counts[layer] = int(layer_plan_counts.get(layer, 0) or 0) + int(
                record.get("count") or 0
            )

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
                    "experiences",
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
                + len(payload.l2_experiences)
                + len(payload.l2_state_facts)
                + len(payload.l2_state_history)
            ),
            "L3": len(payload.l3_reflections),
            "L4": len(payload.l4_procedures),
        }


__all__ = ["HybridRetrievalPostProcessingMixin"]
