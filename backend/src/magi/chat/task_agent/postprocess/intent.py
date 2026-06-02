"""Intent-routing trace helpers for chat post-processing.

Phase 5 migration: SpanCompleted events instead of direct upserts.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from magi.agent.runtime.contracts import FactRecord
from magi.agent.trace import now_wall_ms
from magi.runtime_trace.span_publisher import publish_trace_span, resolve_event_bus
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext


def _preview_text(value: Any, *, limit: int = 240) -> str | None:
    text = " ".join(str(value or "").strip().split())
    return text[:limit] or None


class _IntentPostprocessHostProtocol(Protocol):
    _runtime_trace_store: Any

    def _resolve_turn_id(
        self, context: ChatRuntimeContext, payload: dict[str, Any]
    ) -> str | None: ...

    def _build_trace_id(self, turn_id: str) -> str: ...

    def _build_span_id(self, turn_id: str, kind: str) -> str: ...

    def _build_root_span_id(self, turn_id: str) -> str: ...

    def _resolve_started_at_ms(self, result: Any, latest_fact: FactRecord) -> int: ...

    def _normalize_mode(self, value: Any) -> str: ...

    def _serialize_ux_plan(self, decision: Any) -> dict[str, Any]: ...

    def _serialize_selected_tools_payload(
        self,
        *,
        router_tools: list[str],
        selected_tools: list[str],
        task_hint: Any,
        recommended_tools: list[dict[str, Any]],
        llm_trace: dict[str, Any] | None = None,
    ) -> str: ...

    async def _ensure_turn_trace_started(
        self,
        *,
        trace_id: str,
        turn_id: str,
        user_id: str,
        session_id: str,
        started_at_ms: int,
        user_message: str,
        mode: str,
        run_id: str | None = None,
        run_revision: int | None = None,
    ) -> None: ...

    async def _persist_turn_ux_plan(
        self,
        *,
        turn_id: str | None,
        execution_mode: str,
        ux_plan: dict[str, Any] | None,
        updated_at_ms: int,
        run_id: str | None,
        run_revision: int,
        run_disposition: str | None,
    ) -> None: ...

    async def _get_turn_ux_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> Any: ...

    async def _emit_turn_ux_plan_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
        timestamp_ms: int | None,
    ) -> None: ...


def _intent_resolution_attributes(
    *,
    decision: Any,
    host: _IntentPostprocessHostProtocol,
    selected_tools: list[str] | None = None,
    task_hint: Any = None,
    recommended_tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    router_tools = list(getattr(decision, "tools", []) or [])
    selected = list(selected_tools if selected_tools is not None else router_tools)
    selected_worker_type = (
        str(getattr(getattr(decision, "orchestration_plan", None), "default_leaf_type", "") or "")
        or None
    )
    return {
        "intent": str(getattr(decision, "intent", "") or ""),
        "execution_mode": host._normalize_mode(getattr(decision, "execution_mode", None)),
        "route_reason": str(getattr(decision, "reasoning", "") or "") or None,
        "selected_tools_json": host._serialize_selected_tools_payload(
            router_tools=router_tools,
            selected_tools=selected,
            task_hint=(
                task_hint if task_hint is not None else getattr(decision, "task_hint", None)
            ),
            recommended_tools=list(
                recommended_tools
                if recommended_tools is not None
                else (getattr(decision, "recommended_tools", []) or [])
            ),
            llm_trace=getattr(decision, "llm_trace", None),
        ),
        "selected_worker_type": selected_worker_type,
    }


class ChatPostprocessIntentMixin:
    """Persist intent-routing and selected-tool trace details."""

    async def record_intent_resolution(self, context: ChatRuntimeContext, decision: Any) -> None:
        host = cast(_IntentPostprocessHostProtocol, self)
        latest_fact = context.latest_fact
        if host._runtime_trace_store is None or not isinstance(latest_fact, FactRecord):
            return
        turn_id = host._resolve_turn_id(
            context,
            latest_fact.payload if isinstance(latest_fact.payload, dict) else {},
        )
        if not turn_id:
            return
        trace_id = host._build_trace_id(turn_id)
        started_at_ms = host._resolve_started_at_ms(None, latest_fact)
        await host._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=turn_id,
            user_id=context.user_id,
            session_id=context.session_id,
            started_at_ms=started_at_ms,
            user_message=context.latest_user_message,
            mode=host._normalize_mode(getattr(decision, "execution_mode", None)),
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
        )
        bus = getattr(host, "_event_bus", None) or resolve_event_bus()
        ended_at_ms = now_wall_ms()
        span_id = host._build_span_id(turn_id, "intent_resolution")
        intent_preview = str(getattr(decision, "intent", "") or "")[:240] or None
        # intent_resolution sub-table row (subscriber writes trace_spans + trace_intent_resolutions)
        attributes = _intent_resolution_attributes(decision=decision, host=host)
        attributes["input_preview"] = _preview_text(context.latest_user_message)
        attributes["output_preview"] = _preview_text(
            f"{getattr(decision, 'intent', '')} / {host._normalize_mode(getattr(decision, 'execution_mode', None))}"
        )
        await publish_trace_span(
            event_bus=bus,
            node_type="intent_resolution",
            name="Intent resolution",
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=host._build_root_span_id(turn_id),
            status="completed",
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            result_preview=intent_preview,
            turn_id=turn_id,
            attributes=attributes,
        )
        # Note: llm_call SpanCompleted is now published by provider_bridge
        # (see llm/provider_bridge/responses.py:_emit_usage_event). The intent
        # resolution parent span above is the only chat-side publish needed.
        ux_plan = host._serialize_ux_plan(decision)
        await host._persist_turn_ux_plan(
            turn_id=turn_id,
            execution_mode=host._normalize_mode(getattr(decision, "execution_mode", None)),
            ux_plan=ux_plan,
            updated_at_ms=ended_at_ms,
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            run_disposition=context.session_run_disposition,
        )
        turn_ux_message = await host._get_turn_ux_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )
        await host._emit_turn_ux_plan_notification(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            ux_plan=ux_plan,
            message_id=(turn_ux_message.message_id if turn_ux_message is not None else None),
            message_kind=(turn_ux_message.message_kind if turn_ux_message is not None else None),
            timestamp_ms=(turn_ux_message.created_at_ms if turn_ux_message is not None else None),
        )

    async def record_tool_selection(
        self, context: ChatRuntimeContext, decision: Any, tool_selection: Any
    ) -> None:
        host = cast(_IntentPostprocessHostProtocol, self)
        latest_fact = context.latest_fact
        if host._runtime_trace_store is None or not isinstance(latest_fact, FactRecord):
            return
        turn_id = host._resolve_turn_id(
            context,
            latest_fact.payload if isinstance(latest_fact.payload, dict) else {},
        )
        if not turn_id:
            return
        bus = getattr(host, "_event_bus", None) or resolve_event_bus()
        span_id = host._build_span_id(turn_id, "intent_resolution")
        trace_id = host._build_trace_id(turn_id)
        now_ms = now_wall_ms()
        attributes = _intent_resolution_attributes(
            decision=decision,
            host=host,
            selected_tools=list(getattr(tool_selection, "tools", []) or []),
            task_hint=getattr(tool_selection, "task_hint", None)
            or getattr(decision, "task_hint", None),
            recommended_tools=list(getattr(tool_selection, "recommended_tools", []) or []),
        )
        attributes["input_preview"] = _preview_text(context.latest_user_message)
        attributes["output_preview"] = _preview_text(
            f"{getattr(decision, 'intent', '')} / {host._normalize_mode(getattr(decision, 'execution_mode', None))}"
        )
        await publish_trace_span(
            event_bus=bus,
            node_type="intent_resolution",
            name="Intent resolution",
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=host._build_root_span_id(turn_id),
            status="completed",
            started_at_ms=now_ms,
            ended_at_ms=now_ms,
            turn_id=turn_id,
            attributes=attributes,
        )


__all__ = ["ChatPostprocessIntentMixin"]
