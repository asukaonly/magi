"""Backstop and fallback execution helpers for hybrid retrieval service queries."""

from __future__ import annotations

from typing import Any, Optional, cast

from .handlers import L1Handler
from .models import (
    IntentDeciderInput,
    L1Conditions,
    LayerQueryPlan,
    RetrievalPayload,
    RetrievalQuery,
)
from .service_plan_augmentation import _apply_request_constraints
from .service_policy import comparison_backstop_queries, rule_backstop_reason


class HybridRetrievalBackstopMixin:
    """Run deterministic backstops and fallback plans when primary retrieval is weak."""

    async def _run_backstops(
        self,
        request: RetrievalQuery,
        decision: Any,
        intent_input: IntentDeciderInput,
        payload: RetrievalPayload,
        *,
        l1: Optional[L1Handler],
        primary_plans: list[LayerQueryPlan],
    ) -> None:
        """Run rule-based and comparison backstops when primary results are insufficient."""
        host = cast(Any, self)
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
            for plan in rule_primary_plans:
                plan.time_range = decision.time_range
            _apply_request_constraints(
                rule_primary_plans,
                request=request,
                time_range=decision.time_range,
            )
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
                        context_scope=dict(request.context_scope or {}),
                        limit=request.limit,
                    ),
                    time_range=decision.time_range,
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
        host = cast(Any, self)
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
            _apply_request_constraints(
                fallback_plans,
                request=request,
                time_range=decision.time_range,
            )
            await self._execute_and_merge_plans(
                fallback_plans, payload, l1=l1, request=request, label="Fallback plan",
            )
            if fallback_plans:
                payload.trace["fallback_triggered"] = True

    async def _maybe_supplement_cold_archives(
        self,
        decision: Any,
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
    ) -> None:
        """Supplement retrieval from cold archives when hot hits are sparse or historical."""
        host = cast(Any, self)
        memory = getattr(host, "_memory", None)
        archives = getattr(memory, "archives", None) if memory is not None else None
        if archives is None:
            return

        time_range = getattr(decision, "time_range", None)
        start_time = getattr(time_range, "start", None) if time_range is not None else None
        end_time = getattr(time_range, "end", None) if time_range is not None else None
        if start_time is None and request.time_range:
            start_time = request.time_range.get("start")
        if end_time is None and request.time_range:
            end_time = request.time_range.get("end")

        has_historical_range = start_time is not None
        hot_sparse = len(payload.l1_events) < max(1, int(host._config.fallback_trigger_threshold))
        if not has_historical_range and not hot_sparse:
            return

        limit = max(1, min(int(request.limit or 10), 20))
        source_filters = tuple(request.source_filters) if request.source_filters else None
        try:
            result = await archives.search(
                query=request.query or "",
                start_time=float(start_time) if start_time is not None else None,
                end_time=float(end_time) if end_time is not None else None,
                source_filters=source_filters,
                limit=limit,
            )
            # If a time-bounded query found no lexical matches in archive, retry time-only
            # so historical questions ("what did I do on Oct 3?") still recover archived details.
            if not result.items and start_time is not None and (request.query or "").strip():
                result = await archives.search(
                    query="",
                    start_time=float(start_time),
                    end_time=float(end_time) if end_time is not None else None,
                    source_filters=source_filters,
                    limit=limit,
                )
        except Exception:
            return

        if not result.items:
            return

        existing_l1_ids = {str(item.get("event_id") or "") for item in payload.l1_events}
        existing_l3_ids = {str(item.get("summary_id") or "") for item in payload.l3_reflections}
        added = 0
        for record in result.items:
            if record.layer == "l1":
                if record.record_id in existing_l1_ids:
                    continue
                payload.l1_events.append(
                    {
                        "event_id": record.record_id,
                        "timestamp": float(record.occurred_at),
                        "source": record.source,
                        "event_type": record.event_type,
                        "content": record.content,
                        "archived": True,
                        "retrieval_source": "cold_archive",
                        "retrieval_score": 0.45,
                    }
                )
                existing_l1_ids.add(record.record_id)
                added += 1
            elif record.layer == "l3":
                if record.record_id in existing_l3_ids:
                    continue
                payload.l3_reflections.append(
                    {
                        "summary_id": record.record_id,
                        "summary_type": record.event_type,
                        "period_start": float(record.occurred_at),
                        "period_end": float(record.period_end or record.occurred_at),
                        "content": record.content,
                        "source_event_ids": list(record.evidence_event_ids),
                        "archived": True,
                        "retrieval_source": "cold_archive",
                    }
                )
                existing_l3_ids.add(record.record_id)
                added += 1
        if added:
            payload.trace["cold_archive_hits"] = added

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


__all__ = ["HybridRetrievalBackstopMixin"]
