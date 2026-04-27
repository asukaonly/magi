"""Trace persistence and worker publication helpers."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

from ...agent.trace import TraceEventEmitter, build_trace_timing, now_wall_ms
from ...events.events import Event, EventLevel
from ...runtime_trace import (
    RuntimeNotificationRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
)
from .worker_state import WorkerRunState
from ...core.logger import get_logger

logger = get_logger(__name__)


class WorkerTraceMixin:
    """Persist worker runtime traces and publish worker progress facts."""

    _message_bus: Any
    _runtime_trace_store: Any
    _task_agent_manager: Any

    async def _handle_worker_loop_event(self, run_state: WorkerRunState, payload: Dict[str, Any]) -> None:
        llm_trace = payload.get("llm_trace")
        if not isinstance(llm_trace, dict) or not llm_trace:
            return
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = now_wall_ms()
        started_at_ms = max(0, ended_at_ms - duration_ms)
        stage = str(payload.get("stage") or "unknown")
        iteration = max(0, int(payload.get("iteration") or 0))
        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        span_id = self._build_worker_llm_span_id(
            turn_id=trace_turn_id,
            trace_key=trace_key,
            attempt_index=attempt_index,
            stage=stage,
            iteration=iteration,
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="llm_call",
                name=f"{run_state.subagent_type} worker LLM call",
                status="completed",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                iteration=iteration,
                execution_agent_id=run_state.worker_id,
                result_preview=str(payload.get("response_preview") or "")[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_llm_call(
            TraceLlmCallRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                response_preview=str(payload.get("response_preview") or "")[:240] or None,
            )
        )
        context_usage = payload.get("context_usage")
        if isinstance(context_usage, dict):
            await self._publish_context_usage_notification(run_state, context_usage)
        await self._publish_trace_update_notification({
            "user_id": run_state.user_id,
            "session_id": run_state.session_id,
            "turn_id": run_state.turn_id,
        })

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
                channel="context_usage",
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

    async def _emit_worker_dispatch_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        dispatch_span_id = self._build_worker_dispatch_span_id(trace_turn_id, self._worker_trace_key(run_state))
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=dispatch_span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_root_span_id(trace_turn_id),
                node_type="worker_dispatch",
                name="Worker dispatch",
                status="completed",
                attempt_index=run_state.retry_count + 1,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=run_state.description[:240] or None,
                started_at_ms=run_state.started_at_ms,
                ended_at_ms=run_state.started_at_ms,
                duration_ms=0,
                created_at_ms=run_state.started_at_ms,
                updated_at_ms=run_state.started_at_ms,
            )
        )

    async def _emit_worker_attempt_started_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_dispatch_span_id(trace_turn_id, trace_key),
                node_type="worker_attempt",
                name=f"Attempt {attempt_index}",
                status="running",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                started_at_ms=run_state.started_at_ms,
                created_at_ms=run_state.started_at_ms,
                updated_at_ms=run_state.started_at_ms,
            )
        )

    async def _emit_worker_started_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="worker",
                name=f"{run_state.subagent_type} worker",
                status="running",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=run_state.description[:240] or None,
                started_at_ms=run_state.started_at_ms,
                created_at_ms=run_state.started_at_ms,
                updated_at_ms=run_state.started_at_ms,
            )
        )

    async def _emit_worker_completed_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state=run_state, status="completed")
        await self._emit_worker_attempt_terminal_trace(run_state=run_state, status="completed")

    async def _emit_worker_failed_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state=run_state, status="failed")
        await self._emit_worker_attempt_terminal_trace(run_state=run_state, status="failed")

    async def _emit_worker_attempt_terminal_trace(self, run_state: WorkerRunState, status: str) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        ended_at_ms = int((run_state.completed_at or run_state.updated_at or time.time()) * 1000)
        timing = build_trace_timing(
            started_at_ms=run_state.started_at_ms,
            ended_at_ms=ended_at_ms,
            started_monotonic=run_state.started_monotonic or None,
            ended_monotonic=time.monotonic(),
        )
        output_payload = {
            "worker_id": run_state.worker_id,
            "result_preview": run_state.result_preview,
            "failure_reason": run_state.failure_reason,
        }
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_dispatch_span_id(trace_turn_id, trace_key),
                node_type="worker_attempt",
                name=f"Attempt {attempt_index}",
                status=status,
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=output_payload["result_preview"],
                error_text=(
                    run_state.error or run_state.failure_reason or "Worker attempt failed"
                    if status != "completed"
                    else None
                ),
                started_at_ms=timing.started_at_ms,
                ended_at_ms=timing.ended_at_ms or timing.started_at_ms,
                duration_ms=timing.duration_ms or 0,
                created_at_ms=timing.started_at_ms,
                updated_at_ms=timing.ended_at_ms or timing.started_at_ms,
            )
        )

    async def _emit_worker_terminal_trace(self, run_state: WorkerRunState, status: str) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        ended_at_ms = int((run_state.completed_at or run_state.updated_at or time.time()) * 1000)
        timing = build_trace_timing(
            started_at_ms=run_state.started_at_ms,
            ended_at_ms=ended_at_ms,
            started_monotonic=run_state.started_monotonic or None,
            ended_monotonic=time.monotonic(),
        )
        output_payload = {
            "result_preview": run_state.result_preview,
            "result": dict(run_state.result or {}),
            "failure_reason": run_state.failure_reason,
        }
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="worker",
                name=f"{run_state.subagent_type} worker",
                status=status,
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=output_payload["result_preview"],
                error_text=(
                    run_state.error or run_state.failure_reason or "Worker execution failed"
                    if status != "completed"
                    else None
                ),
                started_at_ms=timing.started_at_ms,
                ended_at_ms=timing.ended_at_ms or timing.started_at_ms,
                duration_ms=timing.duration_ms or 0,
                created_at_ms=timing.started_at_ms,
                updated_at_ms=timing.ended_at_ms or timing.started_at_ms,
            )
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

        execution_time_seconds = float(payload.get("execution_time") or 0.0)
        duration_ms = max(0, int(round(execution_time_seconds * 1000)))
        ended_at_ms = now_wall_ms()
        started_at_ms = max(0, ended_at_ms - duration_ms)
        tool_name = str(payload.get("tool_name") or "unknown")
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
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=tool_span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="tool_call",
                name=f"{tool_name} tool call",
                status="completed" if success else "failed",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=result_preview,
                error_text=str(payload.get("error") or "") or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_tool_call(
            TraceToolRecord(
                span_id=tool_span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                tool_name=tool_name,
                tool_call_id=str(payload.get("tool_call_id") or "") or None,
                arguments_json=json.dumps(payload.get("arguments") or {}),
                success=success,
                execution_time_ms=duration_ms,
                error_code=str(payload.get("error_code") or "") or None,
                error_message=str(payload.get("error") or "") or None,
                result_preview=result_preview,
                result_json=self._serialize_tool_result_json(payload.get("data")),
            )
        )

    def _resolve_trace_turn_id(self, run_state: WorkerRunState) -> str | None:
        normalized_turn_id = str(run_state.turn_id or "").strip()
        return normalized_turn_id or None

    @staticmethod
    def _build_trace_id(turn_id: str) -> str:
        return f"trace:{turn_id}"

    @staticmethod
    def _serialize_tool_result_json(data: Any) -> str | None:
        if data is None:
            return None
        if isinstance(data, str):
            return data
        try:
            return json.dumps(data)
        except (TypeError, ValueError):
            return str(data)

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
    def _build_worker_llm_span_id(turn_id: str, trace_key: str, attempt_index: int, stage: str, iteration: int) -> str:
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
        return str(run_state.subtask_id or run_state.worker_id)

    @staticmethod
    def _build_worker_trace_tags(run_state: WorkerRunState) -> Dict[str, Any]:
        return {
            "role": "worker",
            "worker_id": run_state.worker_id,
            "worker_type": run_state.subagent_type,
            "orchestration_id": run_state.orchestration_id,
            "subtask_id": run_state.subtask_id,
            "parent_task_agent_type": run_state.parent_task_agent_type,
            "parent_task_agent_id": run_state.parent_task_agent_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
        }

    async def _publish_worker_fact(
        self,
        run_state: WorkerRunState,
        event_type: str,
        internal_payload: Dict[str, Any],
        public_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            from ...agent.runtime.contracts import FactRecord

            manager = self._task_agent_manager
            if manager is None:
                raise RuntimeError("task agent manager unavailable")
        except Exception as exc:
            logger.debug(
                "Worker fact publish skipped (runtime unavailable) | worker_id=%s error=%s",
                run_state.worker_id,
                exc,
            )
            return

        now = time.time()
        internal_data = {
            "worker_id": run_state.worker_id,
            "worker_status": run_state.status,
            "worker_subagent_type": run_state.subagent_type,
            "worker_description": run_state.description,
            "failure_reason": run_state.failure_reason,
            "orchestration_id": run_state.orchestration_id,
            "subtask_id": run_state.subtask_id,
            "parent_task_agent_type": run_state.parent_task_agent_type,
            "parent_task_agent_id": run_state.parent_task_agent_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
            "user_id": run_state.user_id,
            "session_id": run_state.session_id,
            "turn_id": run_state.turn_id,
            "run_id": run_state.run_id,
            "run_revision": run_state.run_revision,
            "timestamp": now,
            **internal_payload,
        }
        fact = FactRecord(
            agent_id=f"{run_state.target_task_agent_type}:{run_state.target_task_agent_id}",
            event_type=event_type,
            payload=internal_data,
            agent_type=run_state.target_task_agent_type,
            agent_instance_id=run_state.target_task_agent_id,
            timestamp=now,
            correlation_id=run_state.worker_id,
        )
        await manager.add_fact_to_agent(run_state.target_task_agent_type, run_state.target_task_agent_id, fact)
        external_data = {
            "worker_id": run_state.worker_id,
            "worker_status": run_state.status,
            "worker_subagent_type": run_state.subagent_type,
            "worker_description": run_state.description,
            "failure_reason": run_state.failure_reason,
            "orchestration_id": run_state.orchestration_id,
            "subtask_id": run_state.subtask_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
            "user_id": run_state.user_id,
            "session_id": run_state.session_id,
            "turn_id": run_state.turn_id,
            "run_id": run_state.run_id,
            "run_revision": run_state.run_revision,
            "timestamp": now,
            **(public_payload or internal_payload),
        }
        await self._publish_worker_bus_event(event_type=event_type, payload=external_data, correlation_id=run_state.worker_id)

    async def _publish_worker_bus_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> None:
        try:
            message_bus = self._message_bus
            if message_bus is None:
                return
            await message_bus.publish(
                Event(
                    type=event_type,
                    data=payload,
                    source="agent_tool",
                    level=EventLevel.INFO,
                    correlation_id=correlation_id,
                )
            )
        except Exception as exc:
            logger.debug(f"Failed to publish worker bus event | event_type={event_type} error={exc}")
        await self._publish_trace_update_notification(payload)

    async def _publish_trace_update_notification(self, payload: Dict[str, Any]) -> None:
        if self._runtime_trace_store is None:
            return
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip() or None
        if not user_id or not session_id or not turn_id:
            return
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="trace_update",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json="{}",
                created_at_ms=now_wall_ms(),
            )
        )
