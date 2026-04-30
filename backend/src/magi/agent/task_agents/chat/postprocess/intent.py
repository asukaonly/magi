"""Intent-routing trace helpers for chat post-processing."""

from __future__ import annotations

from typing import Any, Protocol, cast

from .....agent.runtime.contracts import FactRecord
from .....agent.trace import now_wall_ms
from .....runtime_trace import (
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
)
from ..contracts import ChatRuntimeContext


class _IntentPostprocessHostProtocol(Protocol):
    _runtime_trace_store: Any

    def _resolve_turn_id(self, context: ChatRuntimeContext, payload: dict[str, Any]) -> str | None: ...

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


class ChatPostprocessIntentMixin:
    """Persist intent-routing and selected-tool trace details."""

    async def record_intent_resolution(self, context: ChatRuntimeContext, decision: Any) -> None:
        host = cast(_IntentPostprocessHostProtocol, self)
        latest_fact = context.latest_fact
        if host._runtime_trace_store is None or not isinstance(latest_fact, FactRecord):
            return
        turn_id = host._resolve_turn_id(
            context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {}
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
        )
        ended_at_ms = now_wall_ms()
        span_id = host._build_span_id(turn_id, "intent_resolution")
        await host._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=turn_id,
                parent_span_id=host._build_root_span_id(turn_id),
                node_type="intent_resolution",
                name="Intent resolution",
                status="completed",
                result_preview=str(getattr(decision, "intent", "") or "")[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await host._runtime_trace_store.upsert_intent_resolution(
            TraceIntentResolutionRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=turn_id,
                intent=str(getattr(decision, "intent", "") or ""),
                execution_mode=host._normalize_mode(getattr(decision, "execution_mode", None)),
                route_reason=str(getattr(decision, "reasoning", "") or "") or None,
                selected_tools_json=host._serialize_selected_tools_payload(
                    router_tools=list(getattr(decision, "tools", []) or []),
                    selected_tools=list(getattr(decision, "tools", []) or []),
                    task_hint=getattr(decision, "task_hint", None),
                    recommended_tools=list(getattr(decision, "recommended_tools", []) or []),
                ),
                selected_worker_type=(
                    str(
                        getattr(
                            getattr(decision, "orchestration_plan", None), "default_leaf_type", ""
                        )
                        or ""
                    )
                    or None
                ),
            )
        )
        llm_trace = getattr(decision, "llm_trace", None)
        if isinstance(llm_trace, dict) and llm_trace:
            await host._runtime_trace_store.upsert_llm_call(
                TraceLlmCallRecord(
                    span_id=span_id,
                    trace_id=trace_id,
                    turn_id=turn_id,
                    provider=str(llm_trace.get("provider") or "unknown"),
                    model=str(llm_trace.get("model") or "unknown"),
                    input_tokens=int(llm_trace.get("input_tokens") or 0),
                    output_tokens=int(llm_trace.get("output_tokens") or 0),
                    reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                    cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                    cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                    thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                    request_preview=(context.latest_user_message or "")[:240] or None,
                    response_preview=str(getattr(decision, "intent", "") or "")[:240] or None,
                )
            )
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
            message_id=turn_ux_message.message_id if turn_ux_message is not None else None,
            message_kind=turn_ux_message.message_kind if turn_ux_message is not None else None,
            timestamp_ms=turn_ux_message.created_at_ms if turn_ux_message is not None else None,
        )

    async def record_tool_selection(
        self, context: ChatRuntimeContext, decision: Any, tool_selection: Any
    ) -> None:
        host = cast(_IntentPostprocessHostProtocol, self)
        latest_fact = context.latest_fact
        if host._runtime_trace_store is None or not isinstance(latest_fact, FactRecord):
            return
        turn_id = host._resolve_turn_id(
            context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {}
        )
        if not turn_id:
            return
        span_id = host._build_span_id(turn_id, "intent_resolution")
        trace_id = host._build_trace_id(turn_id)
        await host._runtime_trace_store.upsert_intent_resolution(
            TraceIntentResolutionRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=turn_id,
                intent=str(getattr(decision, "intent", "") or ""),
                execution_mode=host._normalize_mode(getattr(decision, "execution_mode", None)),
                route_reason=str(getattr(decision, "reasoning", "") or "") or None,
                selected_tools_json=host._serialize_selected_tools_payload(
                    router_tools=list(getattr(decision, "tools", []) or []),
                    selected_tools=list(getattr(tool_selection, "tools", []) or []),
                    task_hint=getattr(tool_selection, "task_hint", None)
                    or getattr(decision, "task_hint", None),
                    recommended_tools=list(getattr(tool_selection, "recommended_tools", []) or []),
                ),
                selected_worker_type=(
                    str(
                        getattr(
                            getattr(decision, "orchestration_plan", None), "default_leaf_type", ""
                        )
                        or ""
                    )
                    or None
                ),
            )
        )


__all__ = ["ChatPostprocessIntentMixin"]
