"""Runtime trace persistence helpers for chat post-processing.

Phase 5 migration: this module no longer writes to ``runtime_trace_store``
directly. It publishes ``SpanCompleted`` events via ``publish_trace_span`` and
``RuntimeTraceSubscriber`` projects them into the trace tables.

The store reference is kept for read-side access (``get_turn`` / ``get_span``)
where supersession needs to inspect existing rows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .....runtime_trace.span_publisher import publish_trace_span, resolve_event_bus


def _root_turn_attributes(
    *,
    turn_id: str,
    session_id: str,
    user_id: str,
    status: str,
    mode: str,
    started_at_ms: int,
    ended_at_ms: int | None = None,
    duration_ms: int | None = None,
    orchestration_id: str | None = None,
    user_message_preview: str | None = None,
    response_preview: str | None = None,
    error_summary: str | None = None,
    run_id: str | None = None,
    run_revision: int | None = None,
    continued_from_turn_id: str | None = None,
    continued_from_trace_id: str | None = None,
    superseded_by_turn_id: str | None = None,
    supersession_reason: str | None = None,
    created_at_ms: int | None = None,
    updated_at_ms: int | None = None,
) -> dict[str, Any]:
    """Build the attribute bag for a trace_turns row, matching field names used
    by ``RuntimeTraceSubscriber._record_turn``."""
    attrs: dict[str, Any] = {
        "turn_id": turn_id,
        "session_id": session_id,
        "user_id": user_id,
        "status": status,
        "mode": mode,
        "started_at_ms": int(started_at_ms),
    }
    if ended_at_ms is not None:
        attrs["ended_at_ms"] = int(ended_at_ms)
    if duration_ms is not None:
        attrs["duration_ms"] = int(duration_ms)
    if orchestration_id is not None:
        attrs["orchestration_id"] = orchestration_id
    if user_message_preview is not None:
        attrs["user_message_preview"] = user_message_preview
    if response_preview is not None:
        attrs["response_preview"] = response_preview
    if error_summary is not None:
        attrs["error_summary"] = error_summary
    if run_id is not None:
        attrs["run_id"] = run_id
    if run_revision is not None:
        attrs["run_revision"] = int(run_revision)
    if continued_from_turn_id is not None:
        attrs["continued_from_turn_id"] = continued_from_turn_id
    if continued_from_trace_id is not None:
        attrs["continued_from_trace_id"] = continued_from_trace_id
    if superseded_by_turn_id is not None:
        attrs["superseded_by_turn_id"] = superseded_by_turn_id
    if supersession_reason is not None:
        attrs["supersession_reason"] = supersession_reason
    attrs["created_at_ms"] = int(created_at_ms if created_at_ms is not None else started_at_ms)
    attrs["updated_at_ms"] = int(
        updated_at_ms
        if updated_at_ms is not None
        else (ended_at_ms if ended_at_ms is not None else started_at_ms)
    )
    return attrs


class ChatPostprocessRuntimeTraceMixin:
    """Persist turn/span runtime trace records for chat responses."""

    _chat_store: Any
    _runtime_trace_store: Any
    _event_bus: Any
    _started_turn_traces: set[str]
    _build_trace_id: Callable[[str], str]
    _build_root_span_id: Callable[[str], str]
    _build_span_id: Callable[[str, str], str]

    def _resolve_trace_event_bus(self) -> Any | None:
        bus = getattr(self, "_event_bus", None)
        if bus is not None:
            return bus
        return resolve_event_bus()

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
        bus = self._resolve_trace_event_bus()
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
        # response_emit child span
        await publish_trace_span(
            event_bus=bus,
            node_type="response_emit",
            name="Response emission",
            span_id=self._build_span_id(normalized_turn_id, "response_emit"),
            trace_id=trace_id,
            parent_span_id=self._build_root_span_id(normalized_turn_id),
            status="completed",
            started_at_ms=ended_at_ms,
            ended_at_ms=ended_at_ms,
            result_preview=response_text[:240] or None,
            turn_id=normalized_turn_id,
        )
        # root span (semantic node_type "turn" — does NOT trigger turn-record dispatch)
        await publish_trace_span(
            event_bus=bus,
            node_type="turn",
            name="Chat turn",
            span_id=self._build_root_span_id(normalized_turn_id),
            trace_id=trace_id,
            parent_span_id=None,
            status="completed",
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            result_preview=response_text[:240] or None,
            turn_id=normalized_turn_id,
        )
        # trace_turns row update (writes BOTH base span + turn sub-table)
        await publish_trace_span(
            event_bus=bus,
            node_type="turn_record",
            name=f"turn:{normalized_turn_id}",
            trace_id=trace_id,
            parent_span_id=None,
            status="ok",
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            turn_id=normalized_turn_id,
            attributes=_root_turn_attributes(
                turn_id=normalized_turn_id,
                session_id=session_id,
                user_id=user_id,
                status="completed",
                mode=mode,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                orchestration_id=orchestration_id,
                user_message_preview=user_message[:240] or None,
                response_preview=response_text[:240] or None,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            ),
        )

    async def _emit_response_rhythm_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        response_text: str,
        response_plan: Any,
        started_at_ms: int,
        ended_at_ms: int,
        mode: str,
        user_message: str,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        segments = list(getattr(response_plan, "segments", []) or [])
        if self._runtime_trace_store is None or not normalized_turn_id or not segments:
            return
        bus = self._resolve_trace_event_bus()
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
        segment_previews = [
            " ".join(str(getattr(segment, "content", "") or "").split())[:72]
            for segment in segments
        ]
        segment_previews = [preview for preview in segment_previews if preview]
        output_preview = f"{len(segments)} message segments"
        if segment_previews:
            output_preview = f"{output_preview}: {' | '.join(segment_previews)[:180]}"
        await publish_trace_span(
            event_bus=bus,
            node_type="rhythm_processing",
            name="Response rhythm processing",
            span_id=self._build_span_id(normalized_turn_id, "rhythm_processing"),
            trace_id=trace_id,
            parent_span_id=self._build_root_span_id(normalized_turn_id),
            status="completed",
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            result_preview=output_preview,
            turn_id=normalized_turn_id,
            attributes={
                "input_preview": " ".join(str(response_text or "").split())[:240] or None,
                "output_preview": output_preview,
            },
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
        run_id: str | None = None,
        run_revision: int | None = None,
    ) -> None:
        if self._runtime_trace_store is None or turn_id in self._started_turn_traces:
            return
        bus = self._resolve_trace_event_bus()
        continued_from_turn_id, continued_from_trace_id = await self._resolve_trace_continuation(
            anchor_turn_id=turn_id
        )
        await publish_trace_span(
            event_bus=bus,
            node_type="turn_record",
            name=f"turn:{turn_id}",
            trace_id=trace_id,
            parent_span_id=None,
            status="ok",
            started_at_ms=started_at_ms,
            ended_at_ms=started_at_ms,
            turn_id=turn_id,
            attributes=_root_turn_attributes(
                turn_id=turn_id,
                session_id=session_id,
                user_id=user_id,
                status="running",
                mode=mode,
                started_at_ms=started_at_ms,
                user_message_preview=user_message[:240] or None,
                run_id=run_id,
                run_revision=run_revision,
                continued_from_turn_id=continued_from_turn_id,
                continued_from_trace_id=continued_from_trace_id,
                created_at_ms=started_at_ms,
                updated_at_ms=started_at_ms,
            ),
        )
        await publish_trace_span(
            event_bus=bus,
            node_type="turn",
            name="Chat turn",
            span_id=self._build_root_span_id(turn_id),
            trace_id=trace_id,
            parent_span_id=None,
            status="running",
            started_at_ms=started_at_ms,
            ended_at_ms=started_at_ms,
            turn_id=turn_id,
        )
        self._started_turn_traces.add(turn_id)

    async def emit_cancelled_turn_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        started_at_ms: int,
        cancelled_at_ms: int,
        user_message: str,
        mode: str,
        run_id: str | None = None,
        run_revision: int | None = None,
        error_summary: str | None = None,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id:
            return
        bus = self._resolve_trace_event_bus()
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=normalized_turn_id,
            user_id=user_id,
            session_id=session_id,
            started_at_ms=started_at_ms,
            user_message=user_message,
            mode=mode,
            run_id=run_id,
            run_revision=run_revision,
        )
        await publish_trace_span(
            event_bus=bus,
            node_type="turn",
            name="Chat turn",
            span_id=self._build_root_span_id(normalized_turn_id),
            trace_id=trace_id,
            parent_span_id=None,
            status="cancelled",
            started_at_ms=started_at_ms,
            ended_at_ms=cancelled_at_ms,
            turn_id=normalized_turn_id,
            result_preview=error_summary,
        )
        await publish_trace_span(
            event_bus=bus,
            node_type="turn_record",
            name=f"turn:{normalized_turn_id}",
            trace_id=trace_id,
            parent_span_id=None,
            status="ok",
            started_at_ms=started_at_ms,
            ended_at_ms=cancelled_at_ms,
            turn_id=normalized_turn_id,
            attributes=_root_turn_attributes(
                turn_id=normalized_turn_id,
                session_id=session_id,
                user_id=user_id,
                status="cancelled",
                mode=mode,
                started_at_ms=started_at_ms,
                ended_at_ms=cancelled_at_ms,
                duration_ms=max(0, cancelled_at_ms - started_at_ms),
                user_message_preview=user_message[:240] or None,
                error_summary=error_summary,
                run_id=run_id,
                run_revision=run_revision,
                created_at_ms=started_at_ms,
                updated_at_ms=cancelled_at_ms,
            ),
        )

    async def _resolve_trace_continuation(
        self,
        *,
        anchor_turn_id: str,
    ) -> tuple[str | None, str | None]:
        if self._chat_store is None:
            return (None, None)
        previous_turn = await self._chat_store.get_latest_superseded_turn(
            anchor_turn_id=anchor_turn_id
        )
        if previous_turn is None:
            return (None, None)
        trace_id = (
            str(previous_turn.trace_id or self._build_trace_id(previous_turn.turn_id)).strip()
            or None
        )
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
        bus = self._resolve_trace_event_bus()
        status = "merged" if reason == "augment" else "interrupted"
        started_at_ms = int(existing_turn.started_at_ms or updated_at_ms)
        ended_at_ms = max(updated_at_ms, started_at_ms)
        await publish_trace_span(
            event_bus=bus,
            node_type="turn_record",
            name=f"turn:{existing_turn.turn_id}",
            trace_id=existing_turn.trace_id,
            parent_span_id=None,
            status="ok",
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            turn_id=existing_turn.turn_id,
            attributes=_root_turn_attributes(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                status=status,
                mode=existing_turn.mode,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                orchestration_id=existing_turn.orchestration_id,
                user_message_preview=existing_turn.user_message_preview,
                response_preview=existing_turn.response_preview,
                error_summary=existing_turn.error_summary,
                run_id=existing_turn.run_id,
                run_revision=int(existing_turn.run_revision or 0),
                continued_from_turn_id=existing_turn.continued_from_turn_id,
                continued_from_trace_id=existing_turn.continued_from_trace_id,
                superseded_by_turn_id=anchor_turn_id,
                supersession_reason=status,
                created_at_ms=int(existing_turn.created_at_ms or started_at_ms),
                updated_at_ms=ended_at_ms,
            ),
        )
        root_span = await self._runtime_trace_store.get_span(self._build_root_span_id(turn_id))
        if root_span is None:
            return
        span_started = int(root_span.started_at_ms or started_at_ms)
        await publish_trace_span(
            event_bus=bus,
            node_type=root_span.node_type,
            name=root_span.name,
            span_id=root_span.span_id,
            trace_id=root_span.trace_id,
            parent_span_id=root_span.parent_span_id,
            status=status,
            started_at_ms=span_started,
            ended_at_ms=ended_at_ms,
            result_preview=root_span.result_preview,
            turn_id=root_span.turn_id,
            attributes={
                "attempt_index": root_span.attempt_index,
                "retry_count": root_span.retry_count,
                "iteration": root_span.iteration,
                "execution_agent_id": root_span.execution_agent_id,
                "run_id": root_span.run_id,
                "run_revision": root_span.run_revision,
            },
        )


__all__ = ["ChatPostprocessRuntimeTraceMixin"]
