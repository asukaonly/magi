"""Trace persistence and worker publication helpers."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict

from ...agent.trace import TraceEventEmitter, build_trace_timing, now_wall_ms
from ...core.logger import get_logger
from ...events.domain_payloads import ToolError
from ...events.events import Event, EventLevel
from ...runtime_trace import RuntimeNotificationRecord
from ...runtime_trace.span_publisher import publish_trace_span, resolve_event_bus
from .worker_state import WorkerRunState

WORKER_CONTEXT_USAGE_CHANNEL = "worker_context_usage"
logger = get_logger(__name__)


class WorkerTraceMixin:
    """Persist child runtime spans and trace notifications."""

    _message_bus: Any
    _runtime_trace_store: Any
    _task_agent_manager: Any

    async def _handle_worker_loop_event(
        self, run_state: WorkerRunState, payload: Dict[str, Any]
    ) -> None:
        llm_trace = payload.get("llm_trace")
        if not isinstance(llm_trace, dict) or not llm_trace:
            return
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        # llm_call SpanCompleted is now published by provider_bridge
        # (see llm/provider_bridge/responses.py:_emit_usage_event); the
        # B-era after-the-fact projection has been removed (D phase 4).
        context_usage = payload.get("context_usage")
        if isinstance(context_usage, dict):
            await self._publish_context_usage_notification(run_state, context_usage)
        await self._publish_trace_update_notification(
            {
                "user_id": run_state.user_id,
                "session_id": run_state.session_id,
                "turn_id": run_state.turn_id,
            }
        )

    async def _publish_context_usage_notification(
        self,
        run_state: WorkerRunState,
        context_usage: Dict[str, Any],
    ) -> None:
        if self._runtime_trace_store is None:
            return
        turn_id = str(run_state.turn_id or "").strip()
        if not run_state.user_id or not run_state.session_id or not turn_id:
            return
        payload = {
            "user_id": run_state.user_id,
            "session_id": run_state.session_id,
            "turn_id": turn_id,
            "used_tokens": int(context_usage.get("used_tokens") or 0),
            "window_size": int(context_usage.get("window_size") or 0),
            "threshold": int(context_usage.get("threshold") or 0),
            "timestamp": time.time(),
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel=WORKER_CONTEXT_USAGE_CHANNEL,
                user_id=run_state.user_id,
                session_id=run_state.session_id,
                turn_id=turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )

    def _build_trace_emitter(self) -> TraceEventEmitter | None:
        if self._message_bus is None:
            return None
        return TraceEventEmitter(emit_runtime_event=self._emit_trace_runtime_event)

    async def _emit_trace_runtime_event(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
        success: bool = True,
    ) -> None:
        _ = success
        await self._publish_worker_bus_event(
            event_type=event_type,
            payload=payload,
            correlation_id=str(correlation_id or payload.get("span_id") or uuid.uuid4()),
        )

    async def _publish_worker_bus_event(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> None:
        try:
            if self._message_bus is not None:
                await self._message_bus.publish(
                    Event(
                        type=event_type,
                        data=payload,
                        source="agent_tool",
                        level=EventLevel.INFO,
                        correlation_id=correlation_id,
                    )
                )
        except Exception as exc:
            logger.debug(
                "Failed to publish child trace event | event_type=%s error=%s",
                event_type,
                exc,
            )
        await self._publish_trace_update_notification(payload)

    async def _publish_trace_update_notification(self, payload: Dict[str, Any]) -> None:
        if self._runtime_trace_store is None:
            return
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip() or None
        if not user_id or not session_id or not turn_id:
            return
        notification_payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "refresh_trace": True,
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="trace_update",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json=json.dumps(notification_payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )

    async def _emit_worker_dispatch_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        dispatch_span_id = self._build_worker_dispatch_span_id(
            trace_turn_id, self._worker_trace_key(run_state)
        )
        await publish_trace_span(
            event_bus=resolve_event_bus(fallback=self._message_bus),
            node_type="worker_dispatch",
            name="Worker dispatch",
            span_id=dispatch_span_id,
            trace_id=self._build_trace_id(trace_turn_id),
            parent_span_id=self._build_root_span_id(trace_turn_id),
            status="completed",
            started_at_ms=run_state.started_at_ms,
            ended_at_ms=run_state.started_at_ms,
            turn_id=trace_turn_id,
            result_preview=run_state.description[:240] or None,
            attributes={
                "attempt_index": run_state.retry_count + 1,
                "retry_count": run_state.retry_count,
                "execution_agent_id": run_state.worker_id,
            },
        )

    async def _emit_worker_attempt_started_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        await publish_trace_span(
            event_bus=resolve_event_bus(fallback=self._message_bus),
            node_type="worker_attempt",
            name=f"Attempt {attempt_index}",
            span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
            trace_id=self._build_trace_id(trace_turn_id),
            parent_span_id=self._build_worker_dispatch_span_id(trace_turn_id, trace_key),
            status="running",
            started_at_ms=run_state.started_at_ms,
            ended_at_ms=run_state.started_at_ms,
            turn_id=trace_turn_id,
            attributes={
                "attempt_index": attempt_index,
                "retry_count": run_state.retry_count,
                "execution_agent_id": run_state.worker_id,
            },
        )

    async def _emit_worker_started_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        await publish_trace_span(
            event_bus=resolve_event_bus(fallback=self._message_bus),
            node_type="worker",
            name=f"{run_state.preset.value} child",
            span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
            trace_id=self._build_trace_id(trace_turn_id),
            parent_span_id=self._build_worker_attempt_span_id(
                trace_turn_id, trace_key, attempt_index
            ),
            status="running",
            started_at_ms=run_state.started_at_ms,
            ended_at_ms=run_state.started_at_ms,
            turn_id=trace_turn_id,
            result_preview=run_state.description[:240] or None,
            attributes={
                "attempt_index": attempt_index,
                "retry_count": run_state.retry_count,
                "execution_agent_id": run_state.worker_id,
            },
        )

    async def _emit_worker_completed_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state=run_state, status="completed")
        await self._emit_worker_attempt_terminal_trace(run_state=run_state, status="completed")

    async def _emit_worker_failed_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state=run_state, status="failed")
        await self._emit_worker_attempt_terminal_trace(run_state=run_state, status="failed")

    async def _emit_worker_cancelled_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state=run_state, status="cancelled")
        await self._emit_worker_attempt_terminal_trace(run_state=run_state, status="cancelled")

    async def _emit_worker_attempt_terminal_trace(
        self, run_state: WorkerRunState, status: str
    ) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        timing = _worker_terminal_timing(run_state)
        output_payload = {
            "worker_id": run_state.worker_id,
            "result_preview": run_state.result_preview,
            "failure_reason": run_state.failure_reason,
        }
        await publish_trace_span(
            event_bus=resolve_event_bus(fallback=self._message_bus),
            node_type="worker_attempt",
            name=f"Attempt {attempt_index}",
            span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
            trace_id=self._build_trace_id(trace_turn_id),
            parent_span_id=self._build_worker_dispatch_span_id(trace_turn_id, trace_key),
            status=status,
            started_at_ms=timing.started_at_ms,
            ended_at_ms=timing.ended_at_ms or timing.started_at_ms,
            turn_id=trace_turn_id,
            result_preview=output_payload["result_preview"],
            error=_worker_error_payload(
                run_state,
                status=status,
                error_type="WorkerAttemptError",
                fallback_message="Worker attempt failed",
            ),
            attributes=_worker_span_attributes(run_state, attempt_index),
        )

    async def _emit_worker_terminal_trace(self, run_state: WorkerRunState, status: str) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        timing = _worker_terminal_timing(run_state)
        output_payload = {
            "result_preview": run_state.result_preview,
            "result": dict(run_state.result or {}),
            "failure_reason": run_state.failure_reason,
        }
        await publish_trace_span(
            event_bus=resolve_event_bus(fallback=self._message_bus),
            node_type="worker",
            name=f"{run_state.preset.value} child",
            span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
            trace_id=self._build_trace_id(trace_turn_id),
            parent_span_id=self._build_worker_attempt_span_id(
                trace_turn_id, trace_key, attempt_index
            ),
            status=status,
            started_at_ms=timing.started_at_ms,
            ended_at_ms=timing.ended_at_ms or timing.started_at_ms,
            turn_id=trace_turn_id,
            result_preview=output_payload["result_preview"],
            error=_worker_error_payload(
                run_state,
                status=status,
                error_type="WorkerExecutionError",
                fallback_message="Worker execution failed",
            ),
            attributes=_worker_span_attributes(run_state, attempt_index),
        )

    async def _emit_worker_tool_trace(
        self,
        *,
        run_state: WorkerRunState,
        payload: Dict[str, Any],
        result_preview: str,
    ) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        timing = _tool_trace_timing(payload)
        tool_name = _tool_name(payload)
        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        tool_span_id = self._build_worker_tool_span_id(
            turn_id=trace_turn_id,
            trace_key=trace_key,
            attempt_index=attempt_index,
            tool_call_id=str(payload.get("tool_call_id") or "") or None,
            tool_name=tool_name,
        )

        success = bool(payload.get("success"))
        await publish_trace_span(
            event_bus=resolve_event_bus(fallback=self._message_bus),
            node_type="tool_invocation",
            name=f"{tool_name} tool call",
            span_id=tool_span_id,
            trace_id=self._build_trace_id(trace_turn_id),
            parent_span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
            status="completed" if success else "failed",
            started_at_ms=timing["started_at_ms"],
            ended_at_ms=timing["ended_at_ms"],
            turn_id=trace_turn_id,
            result_preview=result_preview,
            error=_tool_error_payload(payload),
            attributes=_worker_tool_attributes(
                run_state,
                payload=payload,
                tool_name=tool_name,
                result_preview=result_preview,
                duration_ms=timing["duration_ms"],
                success=success,
            ),
        )

    def _resolve_trace_turn_id(self, run_state: WorkerRunState) -> str | None:
        normalized_turn_id = str(run_state.turn_id or "").strip()
        return normalized_turn_id or None

    @staticmethod
    def _build_trace_id(turn_id: str) -> str:
        return f"trace:{turn_id}"

    @staticmethod
    def _serialize_tool_result_json(data: Any) -> str | None:
        return _serialize_tool_result_value_json(data)

    @staticmethod
    def _build_root_span_id(turn_id: str) -> str:
        return f"{turn_id}:turn"

    @staticmethod
    def _build_worker_dispatch_span_id(turn_id: str, trace_key: str) -> str:
        return f"{turn_id}:worker_dispatch:{trace_key}"

    @staticmethod
    def _build_worker_attempt_span_id(turn_id: str, trace_key: str, attempt_index: int) -> str:
        return f"{turn_id}:worker_attempt:{trace_key}:{attempt_index}"

    @staticmethod
    def _build_worker_span_id(turn_id: str, trace_key: str, attempt_index: int) -> str:
        return f"{turn_id}:worker:{trace_key}:{attempt_index}"

    @staticmethod
    def _build_worker_llm_span_id(
        turn_id: str, trace_key: str, attempt_index: int, stage: str, iteration: int
    ) -> str:
        return f"{turn_id}:worker_llm:{trace_key}:{attempt_index}:{stage}:{iteration}"

    @staticmethod
    def _build_worker_tool_span_id(
        turn_id: str,
        trace_key: str,
        attempt_index: int,
        tool_call_id: str | None,
        tool_name: str,
    ) -> str:
        if tool_call_id:
            return f"{turn_id}:worker_tool:{trace_key}:{attempt_index}:{tool_call_id}"
        return f"{turn_id}:worker_tool:{trace_key}:{attempt_index}:{tool_name}"

    @staticmethod
    def _worker_trace_key(run_state: WorkerRunState) -> str:
        return run_state.child_run_id

    @staticmethod
    def _build_worker_trace_tags(run_state: WorkerRunState) -> Dict[str, Any]:
        return {
            "role": "worker",
            "worker_id": run_state.worker_id,
            "child_preset": run_state.preset.value,
            "child_run_id": run_state.child_run_id,
            "parent_run_id": run_state.parent_run_id,
            "parent_task_agent_type": run_state.parent_task_agent_type,
            "parent_task_agent_id": run_state.parent_task_agent_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
        }


def _worker_terminal_timing(run_state: WorkerRunState):
    ended_at_ms = int((run_state.completed_at or run_state.updated_at or time.time()) * 1000)
    return build_trace_timing(
        started_at_ms=run_state.started_at_ms,
        ended_at_ms=ended_at_ms,
        started_monotonic=run_state.started_monotonic or None,
        ended_monotonic=time.monotonic(),
    )


def _worker_error_payload(
    run_state: WorkerRunState,
    *,
    status: str,
    error_type: str,
    fallback_message: str,
) -> ToolError | None:
    if status == "completed":
        return None
    error_text = run_state.error or run_state.failure_reason or fallback_message
    return ToolError(type=error_type, message=error_text)


def _worker_span_attributes(
    run_state: WorkerRunState,
    attempt_index: int,
) -> Dict[str, Any]:
    return {
        "attempt_index": attempt_index,
        "retry_count": run_state.retry_count,
        "execution_agent_id": run_state.worker_id,
    }


def _tool_trace_timing(payload: Dict[str, Any]) -> dict[str, int]:
    execution_time_seconds = float(payload.get("execution_time") or 0.0)
    duration_ms = max(0, int(round(execution_time_seconds * 1000)))
    ended_at_ms = now_wall_ms()
    return {
        "duration_ms": duration_ms,
        "ended_at_ms": ended_at_ms,
        "started_at_ms": max(0, ended_at_ms - duration_ms),
    }


def _tool_name(payload: Dict[str, Any]) -> str:
    return str(payload.get("tool_name") or "unknown")


def _tool_error_payload(payload: Dict[str, Any]) -> ToolError | None:
    error_message = str(payload.get("error") or "") or None
    if not error_message:
        return None
    return ToolError(type="ToolExecutionError", message=error_message)


def _worker_tool_attributes(
    run_state: WorkerRunState,
    *,
    payload: Dict[str, Any],
    tool_name: str,
    result_preview: str,
    duration_ms: int,
    success: bool,
) -> Dict[str, Any]:
    error_message = str(payload.get("error") or "") or None
    return {
        "attempt_index": run_state.retry_count + 1,
        "retry_count": run_state.retry_count,
        "execution_agent_id": run_state.worker_id,
        "tool_name": tool_name,
        "tool_call_id": str(payload.get("tool_call_id") or "") or None,
        "arguments_json": json.dumps(payload.get("arguments") or {}),
        "success": success,
        "execution_time_ms": duration_ms,
        "error_code": str(payload.get("error_code") or "") or None,
        "error_message": error_message,
        "result_preview": result_preview,
        "result_json": _serialize_tool_result_value_json(payload.get("data")),
    }


def _serialize_tool_result_value_json(data: Any) -> str | None:
    if data is None:
        return None
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data)
    except (TypeError, ValueError):
        return str(data)
