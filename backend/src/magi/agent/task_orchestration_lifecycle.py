"""Task lifecycle event publication for orchestration."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from ..core.logger import get_logger
from ..events.domain_payloads import SpanCompleted, ToolError
from ..events.events import Event, EventTypes

logger = get_logger(__name__)


class TaskOrchestrationLifecyclePublisher:
    """Publish task lifecycle spans without expanding TaskOrchestrator."""

    def __init__(self, host: Any) -> None:
        self._host = host

    async def publish(
        self,
        *,
        state: Any,
        status: str,
        summary: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        error: Optional[ToolError] = None,
    ) -> None:
        payload = _build_span_completed(
            state=state,
            status=status,
            summary=summary,
            error_type=error_type,
            error_message=error_message,
            error=error,
        )
        try:
            await self._host._event_bus.publish(
                Event(
                    type=EventTypes.SPAN_COMPLETED,
                    data=payload,
                    source="task_orchestrator",
                    correlation_id=state.turn_id,
                )
            )
        except Exception:
            logger.exception("publish task_lifecycle SpanCompleted failed")


def _build_span_completed(
    *,
    state: Any,
    status: str,
    summary: Optional[str],
    error_type: Optional[str],
    error_message: Optional[str],
    error: Optional[ToolError],
) -> SpanCompleted:
    err_obj = _resolve_error(
        error=error,
        error_type=error_type,
        error_message=error_message,
    )
    started_at_ms = int(state.created_at * 1000)
    ended_at_ms = int(state.updated_at * 1000)
    return SpanCompleted(
        span_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        parent_span_id=None,
        node_type="task_lifecycle",
        name=state.planner,
        status=status,
        started_at_ms=started_at_ms,
        ended_at_ms=ended_at_ms,
        duration_ms=ended_at_ms - started_at_ms,
        error=err_obj,
        result_preview=summary,
        turn_id=state.turn_id,
        attributes=_build_attributes(state, status=status, summary=summary),
    )


def _resolve_error(
    *,
    error: Optional[ToolError],
    error_type: Optional[str],
    error_message: Optional[str],
) -> ToolError | None:
    if error is not None:
        return error
    if error_type is None and error_message is None:
        return None
    return ToolError(
        type=error_type or "Error",
        message=(error_message or "")[:1000],
    )


def _build_attributes(
    state: Any,
    *,
    status: str,
    summary: Optional[str],
) -> dict[str, Any]:
    return {
        "task_id": state.orchestration_id,
        "task_type": state.planner,
        "status": status,
        "summary": summary,
        "user_id": state.user_id,
        "session_id": state.session_id,
        "started_at": state.created_at,
        "finished_at": state.updated_at,
    }


__all__ = ["TaskOrchestrationLifecyclePublisher"]
