"""Runtime trace and notification helpers for chat post-processing."""

from __future__ import annotations

from typing import Any

from .....agent.trace import now_wall_ms
from .....runtime_trace import TraceLlmCallRecord, TraceSpanRecord, TraceTurnRecord
from .components import ChatOutcomeWriter
from .utils import (
    build_root_span_id,
    build_span_id,
    build_trace_id,
    normalize_mode,
    resolve_started_at_ms,
    serialize_ux_plan,
)


class ChatPostprocessTraceMixin:
    """Persist chat runtime traces and emit runtime notifications."""

    _chat_store: Any
    _runtime_notifier: Any
    _runtime_trace_store: Any
    _started_turn_traces: set[str]
    _trace_read_service: Any

    async def _emit_response_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        response_text: str,
        started_at_ms: int,
        ended_at_ms: int,
        orchestration_id: str | None,
        mode: str,
        user_message: str,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id:
            return
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=normalized_turn_id,
            user_id=user_id,
            session_id=session_id,
            started_at_ms=started_at_ms,
            user_message=user_message,
            mode=mode,
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_span_id(normalized_turn_id, "response_emit"),
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="response_emit",
                name="Response emission",
                status="completed",
                result_preview=response_text[:240] or None,
                started_at_ms=ended_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=0,
                created_at_ms=ended_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_root_span_id(normalized_turn_id),
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=None,
                node_type="turn",
                name="Chat turn",
                status="completed",
                result_preview=response_text[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_turn(
            TraceTurnRecord(
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                session_id=session_id,
                user_id=user_id,
                status="completed",
                mode=mode,
                orchestration_id=orchestration_id,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                user_message_preview=user_message[:240] or None,
                response_preview=response_text[:240] or None,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )

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
    ) -> None:
        if self._runtime_trace_store is None or turn_id in self._started_turn_traces:
            return
        continued_from_turn_id, continued_from_trace_id = await self._resolve_trace_continuation(
            anchor_turn_id=turn_id
        )
        await self._runtime_trace_store.upsert_turn(
            TraceTurnRecord(
                trace_id=trace_id,
                turn_id=turn_id,
                session_id=session_id,
                user_id=user_id,
                status="running",
                mode=mode,
                started_at_ms=started_at_ms,
                user_message_preview=user_message[:240] or None,
                continued_from_turn_id=continued_from_turn_id,
                continued_from_trace_id=continued_from_trace_id,
                created_at_ms=started_at_ms,
                updated_at_ms=started_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_root_span_id(turn_id),
                trace_id=trace_id,
                turn_id=turn_id,
                parent_span_id=None,
                node_type="turn",
                name="Chat turn",
                status="running",
                started_at_ms=started_at_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=started_at_ms,
            )
        )
        self._started_turn_traces.add(turn_id)

    async def _resolve_trace_continuation(
        self,
        *,
        anchor_turn_id: str,
    ) -> tuple[str | None, str | None]:
        if self._chat_store is None:
            return (None, None)
        previous_turn = await self._chat_store.get_latest_superseded_turn(anchor_turn_id=anchor_turn_id)
        if previous_turn is None:
            return (None, None)
        trace_id = str(previous_turn.trace_id or self._build_trace_id(previous_turn.turn_id)).strip() or None
        return (previous_turn.turn_id, trace_id)

    async def _persist_trace_supersession(
        self,
        *,
        turn_id: str,
        anchor_turn_id: str,
        reason: str,
        updated_at_ms: int,
    ) -> None:
        if self._runtime_trace_store is None:
            return
        existing_turn = await self._runtime_trace_store.get_turn(turn_id)
        if existing_turn is None:
            return
        status = "merged" if reason == "augment" else "interrupted"
        started_at_ms = int(existing_turn.started_at_ms or updated_at_ms)
        ended_at_ms = max(updated_at_ms, started_at_ms)
        await self._runtime_trace_store.upsert_turn(
            TraceTurnRecord(
                trace_id=existing_turn.trace_id,
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                status=status,
                mode=existing_turn.mode,
                orchestration_id=existing_turn.orchestration_id,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                user_message_preview=existing_turn.user_message_preview,
                response_preview=existing_turn.response_preview,
                error_summary=existing_turn.error_summary,
                run_id=existing_turn.run_id,
                run_revision=existing_turn.run_revision,
                continued_from_turn_id=existing_turn.continued_from_turn_id,
                continued_from_trace_id=existing_turn.continued_from_trace_id,
                superseded_by_turn_id=anchor_turn_id,
                supersession_reason=status,
                created_at_ms=int(existing_turn.created_at_ms or started_at_ms),
                updated_at_ms=ended_at_ms,
            )
        )
        root_span = await self._runtime_trace_store.get_span(self._build_root_span_id(turn_id))
        if root_span is None:
            return
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=root_span.span_id,
                trace_id=root_span.trace_id,
                turn_id=root_span.turn_id,
                parent_span_id=root_span.parent_span_id,
                node_type=root_span.node_type,
                name=root_span.name,
                status=status,
                attempt_index=root_span.attempt_index,
                retry_count=root_span.retry_count,
                iteration=root_span.iteration,
                execution_agent_id=root_span.execution_agent_id,
                result_preview=root_span.result_preview,
                error_text=root_span.error_text,
                run_id=root_span.run_id,
                run_revision=root_span.run_revision,
                started_at_ms=int(root_span.started_at_ms or started_at_ms),
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - int(root_span.started_at_ms or started_at_ms)),
                created_at_ms=int(root_span.created_at_ms or started_at_ms),
                updated_at_ms=ended_at_ms,
            )
        )

    async def _emit_agent_response_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        response_text: str,
        attachments: list[dict[str, Any]] | None,
        orchestration_id: str | None,
        trace_summary: dict[str, Any] | None,
        trace_available: bool,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
    ) -> None:
        await self._runtime_notifier.emit_agent_response(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            response_text=response_text,
            attachments=attachments,
            orchestration_id=orchestration_id,
            trace_summary=trace_summary,
            trace_available=trace_available,
            ux_plan=ux_plan,
            message_id=message_id,
            message_kind=message_kind,
        )

    async def _emit_turn_ux_plan_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
        timestamp_ms: int | None,
    ) -> None:
        await self._runtime_notifier.emit_turn_ux_plan(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            ux_plan=ux_plan,
            message_id=message_id,
            message_kind=message_kind,
            timestamp_ms=timestamp_ms,
        )

    async def _emit_trace_update_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> None:
        trace_summary: dict[str, Any] | None = None
        if self._trace_read_service and turn_id:
            try:
                trace_summary = await self._trace_read_service.aget_trace_summary(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            except Exception:
                pass
        await self._runtime_notifier.emit_trace_update(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            trace_summary=trace_summary,
        )

    async def _emit_context_usage_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        context_usage: dict[str, Any],
    ) -> None:
        await self._runtime_notifier.emit_context_usage(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            context_usage=context_usage,
        )

    async def emit_execution_control_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        orchestration_id: str | None,
        state: str,
        can_cancel: bool,
        label: str | None = None,
    ) -> None:
        await self._runtime_notifier.emit_execution_control(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            orchestration_id=orchestration_id,
            state=state,
            can_cancel=can_cancel,
            label=label,
        )

    _build_trace_id = staticmethod(build_trace_id)
    _build_root_span_id = staticmethod(build_root_span_id)
    _build_span_id = staticmethod(build_span_id)
    _serialize_ux_plan = staticmethod(serialize_ux_plan)
    _resolve_started_at_ms = staticmethod(resolve_started_at_ms)

    @staticmethod
    def _resolve_reaction_notification_text(
        ux_plan: dict[str, Any] | None,
        *,
        fallback: str,
    ) -> str:
        reaction_text = ChatOutcomeWriter.resolve_reaction_text(ux_plan)
        return reaction_text or fallback

    async def _emit_loop_llm_trace(
        self,
        *,
        event_emitter: Any,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        stage: str,
        iteration: Any,
        execution_agent_id: Any,
        llm_trace: Any,
        response_preview: Any,
        tool_count: Any,
        tool_names: Any,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id or not isinstance(llm_trace, dict):
            return
        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = now_wall_ms()
        started_at_ms = max(0, ended_at_ms - duration_ms)
        _ = (event_emitter, user_id, session_id, tool_count, tool_names, response_preview, execution_agent_id)
        if self._runtime_trace_store is None:
            return
        span_id = self._build_span_id(
            normalized_turn_id,
            f"llm_call:{stage}:{int(iteration or 0)}",
        )
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_span_id(normalized_turn_id, f"iteration:{int(iteration or 0)}"),
                node_type="llm_call",
                name="Function-calling LLM call",
                status="completed",
                iteration=int(iteration or 0),
                execution_agent_id=str(execution_agent_id or "") or None,
                result_preview=str(response_preview or "")[:240] or None,
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
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                request_preview=str(llm_trace.get("request_preview") or "")[:240] or None,
                response_preview=str(response_preview or "")[:240] or None,
            )
        )

    async def _emit_result_llm_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        llm_trace: Any,
        started_at_ms: int,
        user_message: str,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id or not isinstance(llm_trace, dict) or not llm_trace:
            return
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=normalized_turn_id,
            user_id=user_id,
            session_id=session_id,
            started_at_ms=started_at_ms,
            user_message=user_message,
            mode="direct_llm",
        )
        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = max(started_at_ms, started_at_ms + duration_ms)
        span_id = self._build_span_id(normalized_turn_id, "llm_call:direct")
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="llm_call",
                name="Main LLM call",
                status="completed",
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
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                request_preview=(user_message or "")[:240] or None,
            )
        )

    _normalize_mode = staticmethod(normalize_mode)
