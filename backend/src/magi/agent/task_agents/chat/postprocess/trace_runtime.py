"""Runtime trace persistence helpers for chat post-processing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .....runtime_trace import TraceSpanRecord, TraceTurnRecord


class ChatPostprocessRuntimeTraceMixin:
    """Persist turn/span runtime trace records for chat responses."""

    _chat_store: Any
    _runtime_trace_store: Any
    _started_turn_traces: set[str]
    _build_trace_id: Callable[[str], str]
    _build_root_span_id: Callable[[str], str]
    _build_span_id: Callable[[str, str], str]

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


__all__ = ["ChatPostprocessRuntimeTraceMixin"]
