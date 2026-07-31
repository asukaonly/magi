"""Plan execution helpers for hybrid retrieval service queries."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Optional, cast

from ...utils.diagnostic_logging import full_content_logging_enabled
from .handlers import L1Handler, execute_plan
from .debug_detail import log_detail
from .models import LayerQueryPlan, RetrievalPayload, RetrievalQuery

logger = logging.getLogger(__name__)


async def execute_layer_plan(plan: LayerQueryPlan, **kwargs: Any) -> Any:
    return await execute_plan(plan, **kwargs)


class HybridRetrievalPlanExecutionMixin:
    """Execute layer query plans in parallel and merge their results."""

    async def _execute_and_merge_plans(
        self,
        plans: list[LayerQueryPlan],
        payload: RetrievalPayload,
        *,
        l1: Optional[L1Handler],
        request: RetrievalQuery,
        label: str = "Plan",
    ) -> None:
        """Execute layer query plans in parallel and merge results into *payload*."""
        if not plans:
            return
        host = cast(Any, self)
        self._log_plan_batch(plans=plans, request=request, label=label)
        results = await self._execute_plan_batch(plans=plans, l1=l1, request=request)
        for plan, result in zip(plans, results):
            self._record_plan_result(
                host=host,
                payload=payload,
                plan=plan,
                result=result,
                label=label,
            )

    def _log_plan_batch(
        self,
        *,
        plans: list[LayerQueryPlan],
        request: RetrievalQuery,
        label: str,
    ) -> None:
        for plan in plans:
            conditions = _conditions_dict(getattr(plan, "conditions", None))
            conditions_log = (
                _compact_value(conditions)
                if full_content_logging_enabled()
                else {"fields": sorted(conditions)}
            )
            logger.info(
                "%s executing | layer=%s fallback=%s conditions=%s time_range=%s "
                "session_id=%s user_id=%s",
                label,
                plan.layer,
                plan.is_fallback,
                conditions_log,
                _time_range_dict(getattr(plan, "time_range", None)),
                request.session_id,
                request.user_id,
            )

    async def _execute_plan_batch(
        self,
        *,
        plans: list[LayerQueryPlan],
        l1: Optional[L1Handler],
        request: RetrievalQuery,
    ) -> list[Any]:
        host = cast(Any, self)
        return await asyncio.gather(
            *(
                self._execute_single_layer_plan(
                    plan=plan,
                    l1=l1,
                    request=request,
                    host=host,
                )
                for plan in plans
            ),
            return_exceptions=True,
        )

    async def _execute_single_layer_plan(
        self,
        *,
        plan: LayerQueryPlan,
        l1: Optional[L1Handler],
        request: RetrievalQuery,
        host: Any,
    ) -> Any:
        return await execute_layer_plan(
            plan,
            l1=l1,
            l2=host._l2,
            l3=host._l3,
            l4=host._l4,
            session_id=request.session_id,
            user_id=request.user_id,
        )

    def _record_plan_result(
        self,
        *,
        host: Any,
        payload: RetrievalPayload,
        plan: LayerQueryPlan,
        result: Any,
        label: str,
    ) -> None:
        trace_record = {
            "label": label,
            "layer": plan.layer,
            "fallback": plan.is_fallback,
        }
        if isinstance(result, Exception):
            if full_content_logging_enabled():
                logger.warning("%s %s failed: %s", label, plan.layer, result)
            else:
                logger.warning(
                    "%s %s failed: error_type=%s",
                    label,
                    plan.layer,
                    type(result).__name__,
                )
            trace_record["status"] = "error"
            trace_record["error"] = str(result)
            host._append_plan_trace(payload, trace_record)
            return

        trace_record["status"] = "ok"
        trace_record["count"] = host._count_plan_result(plan.layer, result)
        host._append_plan_trace(payload, trace_record)
        self._log_plan_result(plan=plan, result=result, trace_record=trace_record, label=label)
        host._merge_result(payload, plan.layer, result)

    def _log_plan_result(
        self,
        *,
        plan: LayerQueryPlan,
        result: Any,
        trace_record: dict[str, Any],
        label: str,
    ) -> None:
        result_summary = _result_summary(plan.layer, result)
        logger.debug(
            "%s result | layer=%s fallback=%s count=%d summary=%s",
            label,
            plan.layer,
            plan.is_fallback,
            trace_record["count"],
            result_summary,
        )
        log_detail(
            logger,
            "RETRIEVAL PLAN RESULT DETAIL",
            {
                "label": label,
                "layer": plan.layer,
                "fallback": plan.is_fallback,
                "count": trace_record["count"],
                "conditions": _compact_value(_conditions_dict(getattr(plan, "conditions", None))),
                "time_range": _time_range_dict(getattr(plan, "time_range", None)),
                "summary": result_summary,
            },
        )


def _conditions_dict(conditions: Any) -> dict[str, Any]:
    if conditions is None:
        return {}
    if is_dataclass(conditions):
        return asdict(conditions)
    if isinstance(conditions, dict):
        return dict(conditions)
    return (
        {key: value for key, value in vars(conditions).items() if not key.startswith("_")}
        if hasattr(conditions, "__dict__")
        else {"repr": repr(conditions)}
    )


def _time_range_dict(time_range: Any) -> dict[str, Any] | None:
    if time_range is None:
        return None
    return {
        "start": getattr(time_range, "start", None),
        "end": getattr(time_range, "end", None),
    }


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return repr(value)[:160]
    if isinstance(value, str):
        return value if len(value) <= 240 else value[:237] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, depth=depth + 1)
            for key, item in value.items()
            if item not in (None, "", [], {}, set())
        }
    if isinstance(value, (list, tuple)):
        sample = [_compact_value(item, depth=depth + 1) for item in list(value)[:12]]
        if len(value) > 12:
            sample.append(f"...(+{len(value) - 12})")
        return sample
    if isinstance(value, set):
        sample = sorted(str(item) for item in value)[:12]
        if len(value) > 12:
            sample.append(f"...(+{len(value) - 12})")
        return sample
    return repr(value)[:160]


def _result_summary(layer: str, result: Any) -> dict[str, Any]:
    if layer in {"L1", "L3", "L4"} and isinstance(result, list):
        key = "event_id" if layer == "L1" else "summary_id" if layer == "L3" else "id"
        return {
            "ids_sample": [
                str(item.get(key) or item.get("id") or "")
                for item in result[:10]
                if isinstance(item, dict)
            ],
        }
    if layer == "L2" and isinstance(result, dict):
        summary: dict[str, Any] = {}
        for key in (
            "entity_cards",
            "relationships",
            "assertions",
            "episodes",
            "experiences",
            "state_facts",
            "state_history",
        ):
            items = result.get(key, [])
            if isinstance(items, list):
                summary[key] = {
                    "count": len(items),
                    "ids_sample": _l2_ids_sample(key, items),
                }
        return summary
    return {"type": type(result).__name__}


def _l2_ids_sample(kind: str, items: list[Any]) -> list[str]:
    id_key = {
        "entity_cards": "entity_id",
        "relationships": "triple_id",
        "assertions": "assertion_id",
        "episodes": "episode_id",
        "experiences": "experience_id",
    }.get(kind, "id")
    return [
        str(item.get(id_key) or item.get("id") or "")
        for item in items[:10]
        if isinstance(item, dict)
    ]


__all__ = ["HybridRetrievalPlanExecutionMixin", "execute_layer_plan"]
