"""Trace and callback helpers for function-calling execution."""

from __future__ import annotations

import inspect
import json
import logging
import time
from collections.abc import Callable
from typing import Any, Dict, Protocol, cast

from ....runtime_trace import (
    RuntimeTraceStore,
    RuntimeTraceWriter,
    TraceSpanRecord,
    TraceToolRecord,
)
from .types import ToolCall, ToolCallResult

logger = logging.getLogger(__name__)


class _TracingHostProtocol(Protocol):
    tool_result_callback: Callable[[dict[str, Any]], Any] | None
    loop_event_callback: Callable[[Dict[str, Any]], Any] | None
    runtime_trace_store: RuntimeTraceStore | None


class FunctionCallingTracingMixin:
    """Emit function-calling callbacks and persist runtime trace rows."""

    def _runtime_trace_writer(self) -> RuntimeTraceWriter | None:
        host = cast(_TracingHostProtocol, self)
        if host.runtime_trace_store is None:
            return None
        return RuntimeTraceWriter(host.runtime_trace_store)

    async def _emit_tool_result(
        self,
        user_id: str,
        session_id: str | None,
        turn_id: str | None,
        user_message: str,
        intent: str,
        iteration: int,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> None:
        """Emit tool execution result to external callback if provided."""
        host = cast(_TracingHostProtocol, self)
        if not host.tool_result_callback:
            return

        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_message": user_message,
            "intent": intent,
            "iteration": iteration,
            "tool_name": tool_call.name,
            "tool_call_id": tool_call.id,
            "arguments": tool_call.arguments,
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "execution_time": result.execution_time,
        }

        try:
            callback_result = host.tool_result_callback(payload)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as exc:
            logger.warning(f"[FunctionCalling] Tool result callback failed: {exc}")

    async def _emit_loop_event(self, payload: Dict[str, Any]) -> None:
        """Emit function-calling loop stage event to external callback if provided."""
        host = cast(_TracingHostProtocol, self)
        if not host.loop_event_callback:
            return
        try:
            callback_result = host.loop_event_callback(payload)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as exc:
            logger.warning(f"[FunctionCalling] Loop event callback failed: {exc}")

    async def _start_iteration_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        execution_agent_id: str,
    ) -> int | None:
        normalized_turn_id = str(turn_id or "").strip()
        writer = self._runtime_trace_writer()
        if writer is None or not normalized_turn_id:
            return None
        started_at_ms = int(time.time() * 1000)
        await writer.record_span(
            TraceSpanRecord(
                span_id=self._build_iteration_span_id(normalized_turn_id, iteration),
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="iteration",
                name=f"Iteration {iteration}",
                status="running",
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=started_at_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=started_at_ms,
            )
        )
        return started_at_ms

    async def _complete_iteration_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        execution_agent_id: str,
        started_at_ms: int | None,
        status: str,
        result_preview: str | None = None,
        error_text: str | None = None,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        writer = self._runtime_trace_writer()
        if writer is None or not normalized_turn_id or started_at_ms is None:
            return
        ended_at_ms = int(time.time() * 1000)
        await writer.record_span(
            TraceSpanRecord(
                span_id=self._build_iteration_span_id(normalized_turn_id, iteration),
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="iteration",
                name=f"Iteration {iteration}",
                status=status,
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                result_preview=result_preview,
                error_text=error_text,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )

    async def _persist_llm_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        stage: str,
        execution_agent_id: str,
        llm_trace: Any,
        response_preview: str | None = None,
        request_preview: str | None = None,
    ) -> None:
        # llm_call span + llm_usage row are now published by provider_bridge
        # (see llm/provider_bridge/responses.py:_emit_usage_event). The B-era
        # after-the-fact projection that wrote trace_spans + trace_llm_calls
        # here was a duplicate and has been removed (D phase 4).
        _ = (
            turn_id,
            iteration,
            stage,
            execution_agent_id,
            llm_trace,
            response_preview,
            request_preview,
        )

    async def _persist_tool_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        execution_agent_id: str,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        writer = self._runtime_trace_writer()
        if writer is None or not normalized_turn_id:
            return
        ended_at_ms = int(time.time() * 1000)
        duration_ms = max(0, int(round(float(result.execution_time or 0.0) * 1000)))
        started_at_ms = max(0, ended_at_ms - duration_ms)
        span_id = self._build_tool_span_id(normalized_turn_id, iteration, tool_call.id)
        result_preview = str(result.data or result.error or "")[:240] or None
        result_json_str: str | None = None
        if result.data is not None:
            try:
                result_json_str = (
                    json.dumps(result.data) if not isinstance(result.data, str) else result.data
                )
            except (TypeError, ValueError):
                result_json_str = str(result.data)
        await writer.record_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                parent_span_id=self._build_iteration_span_id(normalized_turn_id, iteration),
                node_type="tool_call",
                name=f"{tool_call.name} tool call",
                status="completed" if result.success else "failed",
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                result_preview=result_preview,
                error_text=result.error,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await writer.record_tool_call(
            TraceToolRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                tool_name=tool_call.name,
                tool_call_id=tool_call.id,
                arguments_json=json.dumps(tool_call.arguments),
                success=result.success,
                execution_time_ms=duration_ms,
                error_code=result.error_code,
                error_message=result.error,
                result_preview=result_preview,
                result_json=result_json_str,
            )
        )

    @staticmethod
    def _build_trace_id(turn_id: str) -> str:
        return f"trace:{turn_id}"

    @staticmethod
    def _build_root_span_id(turn_id: str) -> str:
        return f"{turn_id}:turn"

    @staticmethod
    def _build_iteration_span_id(turn_id: str, iteration: int) -> str:
        return f"{turn_id}:iteration:{iteration}"

    @staticmethod
    def _build_llm_span_id(turn_id: str, stage: str, iteration: int) -> str:
        return f"{turn_id}:llm_call:{stage}:{iteration}"

    @staticmethod
    def _build_tool_span_id(turn_id: str, iteration: int, tool_call_id: str) -> str:
        return f"{turn_id}:tool_call:{iteration}:{tool_call_id}"
