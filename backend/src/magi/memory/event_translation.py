"""Translate domain-event Events (with strongly-typed payloads) into MemoryEvent.

Strategy: build a synthetic legacy-type Event whose .data is a dict, then delegate
to magi.memory.event_contracts.normalize_runtime_event to reuse the routing
classification (ingest_target / cognition_eligible / retention_class).
The MemoryEvent's metadata_json is then patched in for the tool-invocation case.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from magi.events.events import Event, EventLevel, EventTypes
from magi.events.domain_payloads import (
    AssistantResponseProduced,
    SensorEventEmitted,
    SkillInvocationCompleted,
    SpanCompleted,
    TaskCompleted,
    TaskContext,
    TaskFailed,
    TaskStarted,
    ToolError,
    ToolInvocationCompleted,
    UserMessageReceived,
)
from magi.events.payload_helpers import PayloadTypeError, expect_payload

from .event_contracts import MemoryEvent, normalize_runtime_event
from .sensor_event_projection import build_sensor_memory_event

logger = logging.getLogger(__name__)

EventTranslator = Callable[[Event], Optional[MemoryEvent]]


def translate(event: Event) -> Optional[MemoryEvent]:
    handler = _DISPATCH.get(event.type)
    if handler is not None:
        return handler(event)
    if isinstance(event.data, dict):
        return normalize_runtime_event(event)
    return None


def _ctx_dict(ctx: TaskContext) -> dict[str, Any]:
    return {
        "session_id": ctx.session_id,
        "turn_id": ctx.turn_id,
        "task_id": ctx.task_id,
        "user_id": ctx.user_id,
    }


def _from_tool_invocation(event: Event) -> MemoryEvent:
    p: ToolInvocationCompleted = event.data
    if p.context.session_id is None:
        logger.debug("translate: tool invocation without session_id (tool=%s)", p.tool_name)
    legacy_data = {
        **_ctx_dict(p.context),
        "action_type": p.tool_name,
        "content": p.tool_name,
    }
    legacy_level = EventLevel.ERROR if not p.success else event.level
    legacy = Event(
        type=EventTypes.ACTION_EXECUTED,
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "tool_invocation_service"),
        level=legacy_level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    )
    me = normalize_runtime_event(legacy)
    me.metadata_json = {
        "duration_ms": p.duration_ms,
        "input": p.args_summary,
        "output": p.result_summary,
        "error": p.error.message if p.error else None,
        "tool_category": p.tool_category,
        "started_at": p.started_at,
        "finished_at": p.finished_at,
    }
    return me


def _from_user_message(event: Event) -> MemoryEvent:
    p: UserMessageReceived = event.data
    if p.context.session_id is None:
        logger.warning("translate: chat-derived event missing session_id")
    legacy_data = {
        **_ctx_dict(p.context),
        "content": p.content,
        "interaction_kind": p.interaction_kind,
        **dict(p.metadata or {}),
    }
    memory_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data=legacy_data,
            timestamp=event.timestamp,
            source=str(event.source or "chat_projector"),
            level=event.level,
            correlation_id=event.correlation_id,
            metadata=dict(event.metadata or {}),
            event_id=event.event_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
        )
    )
    if p.interaction_kind:
        memory_event.metadata_json = {"interaction_kind": p.interaction_kind}
    return memory_event


def _from_assistant_response(event: Event) -> MemoryEvent:
    p: AssistantResponseProduced = event.data
    if p.context.session_id is None:
        logger.warning("translate: chat-derived event missing session_id")
    legacy_data = {**_ctx_dict(p.context), "content": p.content, **dict(p.metadata or {})}
    return normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data=legacy_data,
            timestamp=event.timestamp,
            source=str(event.source or "chat_projector"),
            level=event.level,
            correlation_id=event.correlation_id,
            metadata=dict(event.metadata or {}),
            event_id=event.event_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
        )
    )


def _from_sensor(event: Event) -> MemoryEvent:
    p: SensorEventEmitted = event.data
    return build_sensor_memory_event(
        p,
        event_id=event.event_id,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        trace_context=event.trace_context,
    )


def _from_task_started(event: Event) -> MemoryEvent:
    p: TaskStarted = event.data
    legacy_data = {
        **_ctx_dict(p.context),
        "task_id": p.task_id,
        "task_type": p.task_type,
        "started_at": p.started_at,
    }
    return normalize_runtime_event(
        Event(
            type=EventTypes.TASK_STARTED,
            data=legacy_data,
            timestamp=event.timestamp,
            source=str(event.source or "task_orchestrator"),
            level=event.level,
            correlation_id=event.correlation_id,
            metadata=dict(event.metadata or {}),
            event_id=event.event_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
        )
    )


def _from_task_completed(event: Event) -> MemoryEvent:
    p: TaskCompleted = event.data
    legacy_data = {
        **_ctx_dict(p.context),
        "task_id": p.task_id,
        "task_type": p.task_type,
        "summary": p.summary,
        "finished_at": p.finished_at,
        "content": p.summary or "",
    }
    return normalize_runtime_event(
        Event(
            type=EventTypes.TASK_COMPLETED,
            data=legacy_data,
            timestamp=event.timestamp,
            source=str(event.source or "task_orchestrator"),
            level=event.level,
            correlation_id=event.correlation_id,
            metadata=dict(event.metadata or {}),
            event_id=event.event_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
        )
    )


def _from_task_failed(event: Event) -> MemoryEvent:
    p: TaskFailed = event.data
    legacy_data = {
        **_ctx_dict(p.context),
        "task_id": p.task_id,
        "task_type": p.task_type,
        "error": p.error.message,
        "finished_at": p.finished_at,
        "content": p.error.message,
    }
    raised_level = event.level if int(event.level) >= int(EventLevel.ERROR) else EventLevel.ERROR
    return normalize_runtime_event(
        Event(
            type=EventTypes.TASK_FAILED,
            data=legacy_data,
            timestamp=event.timestamp,
            source=str(event.source or "task_orchestrator"),
            level=raised_level,
            correlation_id=event.correlation_id,
            metadata=dict(event.metadata or {}),
            event_id=event.event_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
        )
    )


def _task_context_from_span(sp: SpanCompleted) -> TaskContext:
    attrs = sp.attributes or {}
    return TaskContext(
        session_id=attrs.get("session_id"),
        turn_id=sp.turn_id,
        task_id=attrs.get("task_id"),
        user_id=attrs.get("user_id"),
    )


def _from_span_completed(event: Event) -> Optional[MemoryEvent]:
    """Translate SpanCompleted -> MemoryEvent based on node_type.

    Phase 3 routes node_type='tool_invocation' to the existing tool path.
    Phase 4 adds 'task_lifecycle'. Other node_types are not memory-relevant.
    """
    try:
        sp = expect_payload(event, SpanCompleted)
    except PayloadTypeError:
        return None
    if sp.node_type == "tool_invocation":
        return _span_to_tool_invocation_memory(event, sp)
    if sp.node_type == "task_lifecycle":
        return _span_to_task_lifecycle_memory(event, sp)
    return None


def _span_to_tool_invocation_memory(event: Event, sp: SpanCompleted) -> Optional[MemoryEvent]:
    attrs = dict(sp.attributes or {})
    started_at = attrs.get("started_at")
    if started_at is None:
        started_at = sp.started_at_ms / 1000.0
    finished_at = attrs.get("finished_at")
    if finished_at is None:
        finished_at = sp.ended_at_ms / 1000.0
    duration_ms = attrs.get("execution_time_ms")
    if duration_ms is None:
        duration_ms = sp.duration_ms
    payload = ToolInvocationCompleted(
        tool_name=str(attrs.get("tool_name") or sp.name),
        tool_category=str(attrs.get("tool_category") or "external_tool"),
        success=bool(attrs.get("success", sp.status == "ok")),
        duration_ms=float(duration_ms),
        started_at=float(started_at),
        finished_at=float(finished_at),
        args_summary=attrs.get("args_summary"),
        result_summary=attrs.get("result_summary") or sp.result_preview,
        error=sp.error,
        context=_task_context_from_span(sp),
    )
    synthetic = Event(
        type=EventTypes.TOOL_INVOCATION_COMPLETED,
        data=payload,
        timestamp=event.timestamp,
        source=str(event.source or "tool_invocation_service"),
        level=event.level,
        correlation_id=event.correlation_id,
        event_id=event.event_id,
        causation_id=event.causation_id,
        trace_context=event.trace_context,
        metadata=dict(event.metadata or {}),
    )
    return _from_tool_invocation(synthetic)


def _span_to_task_lifecycle_memory(event: Event, sp: SpanCompleted) -> Optional[MemoryEvent]:
    """Translate task_lifecycle SpanCompleted into TaskCompleted/TaskFailed memory.

    status=='ok'   -> TaskCompleted MemoryEvent path
    status=='error' or 'cancelled' -> TaskFailed MemoryEvent path
    """
    attrs = dict(sp.attributes or {})
    ctx = _task_context_from_span(sp)
    started_at = float(attrs.get("started_at", sp.started_at_ms / 1000.0))
    finished_at = float(attrs.get("finished_at", sp.ended_at_ms / 1000.0))
    task_id = str(attrs.get("task_id") or "")
    task_type = str(attrs.get("task_type") or sp.name)
    if sp.status == "ok":
        payload = TaskCompleted(
            task_id=task_id,
            task_type=task_type,
            started_at=started_at,
            finished_at=finished_at,
            summary=attrs.get("summary"),
            context=ctx,
        )
        synthetic = Event(
            type=EventTypes.TASK_COMPLETED,
            data=payload,
            timestamp=event.timestamp,
            source=str(event.source or "task_orchestrator"),
            level=event.level,
            correlation_id=event.correlation_id,
            event_id=event.event_id,
            causation_id=event.causation_id,
            trace_context=event.trace_context,
            metadata=dict(event.metadata or {}),
        )
        return _from_task_completed(synthetic)
    err = sp.error or ToolError(type="Error", message="task failed")
    payload = TaskFailed(
        task_id=task_id,
        task_type=task_type,
        started_at=started_at,
        finished_at=finished_at,
        error=err,
        context=ctx,
    )
    synthetic = Event(
        type=EventTypes.TASK_FAILED,
        data=payload,
        timestamp=event.timestamp,
        source=str(event.source or "task_orchestrator"),
        level=event.level,
        correlation_id=event.correlation_id,
        event_id=event.event_id,
        causation_id=event.causation_id,
        trace_context=event.trace_context,
        metadata=dict(event.metadata or {}),
    )
    return _from_task_failed(synthetic)


def _from_skill_invocation(event: Event) -> MemoryEvent:
    """Translate a SkillInvocationCompleted into an ACTION_EXECUTED-shaped memory event.

    Skills behave as tool-like actions from the agent's perspective; reusing the
    tool-invocation memory shape keeps a single timeline of executed actions.
    """
    p: SkillInvocationCompleted = event.data
    if p.context.session_id is None:
        logger.debug("translate: skill invocation without session_id (skill=%s)", p.skill_name)
    action_type = f"skill:{p.skill_name}"
    legacy_data = {
        **_ctx_dict(p.context),
        "action_type": action_type,
        "content": action_type,
    }
    legacy_level = EventLevel.ERROR if not p.success else event.level
    legacy = Event(
        type=EventTypes.ACTION_EXECUTED,
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "skill_runner"),
        level=legacy_level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    )
    me = normalize_runtime_event(legacy)
    me.metadata_json = {
        "duration_ms": p.duration_ms,
        "input": p.args_summary,
        "output": p.result_summary,
        "error": p.error.message if p.error else None,
        "tool_category": "skill",
        "skill_name": p.skill_name,
        "fork_mode": p.fork_mode,
        "allowed_tools": list(p.allowed_tools) if p.allowed_tools else None,
        "started_at": p.started_at,
        "finished_at": p.finished_at,
    }
    return me


_DISPATCH: dict[str, EventTranslator] = {
    EventTypes.TOOL_INVOCATION_COMPLETED: _from_tool_invocation,
    EventTypes.SPAN_COMPLETED: _from_span_completed,
    EventTypes.USER_MESSAGE_RECEIVED: _from_user_message,
    EventTypes.ASSISTANT_RESPONSE_PRODUCED: _from_assistant_response,
    EventTypes.SENSOR_EVENT_EMITTED: _from_sensor,
    EventTypes.TASK_STARTED: _from_task_started,
    EventTypes.TASK_COMPLETED: _from_task_completed,
    EventTypes.TASK_FAILED: _from_task_failed,
    EventTypes.SKILL_INVOCATION_COMPLETED: _from_skill_invocation,
}


__all__ = ["translate", "EventTranslator"]
