"""Trace projection for deterministic chat admission and capability exposure."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, cast

from magi.agent.runtime.contracts import FactRecord
from magi.agent.trace import now_wall_ms
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
from magi.runtime_trace.span_publisher import publish_trace_span, resolve_event_bus


@dataclass(slots=True, frozen=True)
class _CapabilityTraceScope:
    turn_id: str
    trace_id: str


class _CapabilityProjectionHost(Protocol):
    _runtime_trace_store: Any

    def _resolve_turn_id(
        self,
        context: ChatRuntimeContext,
        payload: dict[str, Any],
    ) -> str | None: ...

    def _build_trace_id(self, turn_id: str) -> str: ...

    def _build_span_id(self, turn_id: str, kind: str) -> str: ...

    def _build_root_span_id(self, turn_id: str) -> str: ...

    async def _ensure_turn_trace_started(self, **kwargs: Any) -> None: ...


class ChatPostprocessCapabilityMixin:
    """Project admitted capabilities without recreating semantic route traces."""

    async def record_tool_selection(
        self,
        context: ChatRuntimeContext,
        decision: Any,
        tool_selection: Any,
    ) -> None:
        host = cast(_CapabilityProjectionHost, self)
        scope = _resolve_scope(host, context)
        if scope is None:
            return
        now_ms = now_wall_ms()
        await host._ensure_turn_trace_started(
            trace_id=scope.trace_id,
            turn_id=scope.turn_id,
            user_id=context.user_id,
            session_id=context.session_id,
            started_at_ms=now_ms,
            user_message=context.latest_user_message,
            mode="agent_run",
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
        )
        resolution = getattr(decision, "capability_resolution", None)
        payload = (
            resolution.to_event_payload()
            if resolution is not None
            else {"initial_exposed_tools": list(getattr(tool_selection, "tools", []) or [])}
        )
        payload["advisories"] = list(getattr(decision, "recommended_tools", []) or [])
        bus = getattr(host, "_event_bus", None) or resolve_event_bus()
        await publish_trace_span(
            event_bus=bus,
            node_type="capability_resolution",
            name="Capability resolution",
            span_id=host._build_span_id(scope.turn_id, "capability_resolution"),
            trace_id=scope.trace_id,
            parent_span_id=host._build_root_span_id(scope.turn_id),
            status="completed",
            started_at_ms=now_ms,
            ended_at_ms=now_ms,
            result_preview=", ".join(payload.get("initial_exposed_tools", []))[:240] or None,
            turn_id=scope.turn_id,
            attributes={
                "admission": "agent_run",
                "input_preview": " ".join(context.latest_user_message.split())[:240] or None,
                "capability_resolution_json": json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            },
        )


def _resolve_scope(
    host: _CapabilityProjectionHost,
    context: ChatRuntimeContext,
) -> _CapabilityTraceScope | None:
    latest_fact = context.latest_fact
    if host._runtime_trace_store is None or not isinstance(latest_fact, FactRecord):
        return None
    turn_id = host._resolve_turn_id(
        context,
        latest_fact.payload if isinstance(latest_fact.payload, dict) else {},
    )
    if not turn_id:
        return None
    return _CapabilityTraceScope(
        turn_id=turn_id,
        trace_id=host._build_trace_id(turn_id),
    )


__all__ = ["ChatPostprocessCapabilityMixin"]
