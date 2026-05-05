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
    TaskCompleted,
    TaskContext,
    TaskFailed,
    TaskStarted,
    ToolInvocationCompleted,
    UserMessageReceived,
)

from .event_contracts import MemoryEvent, normalize_runtime_event

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
    legacy_data = {**_ctx_dict(p.context), "content": p.content, **dict(p.metadata or {})}
    return normalize_runtime_event(Event(
        type=EventTypes.USER_MESSAGE,
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "chat_projector"),
        level=event.level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    ))


def _from_assistant_response(event: Event) -> MemoryEvent:
    p: AssistantResponseProduced = event.data
    if p.context.session_id is None:
        logger.warning("translate: chat-derived event missing session_id")
    legacy_data = {**_ctx_dict(p.context), "content": p.content, **dict(p.metadata or {})}
    return normalize_runtime_event(Event(
        type=EventTypes.AI_RESPONSE,
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "chat_projector"),
        level=event.level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    ))


def _from_sensor(event: Event) -> MemoryEvent:
    p: SensorEventEmitted = event.data
    legacy_data = {
        **_ctx_dict(p.context),
        "sensor_name": p.sensor_name,
        **dict(p.payload or {}),
    }
    return normalize_runtime_event(Event(
        type="SENSOR_EVENT",
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "awareness"),
        level=event.level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    ))


def _from_task_started(event: Event) -> MemoryEvent:
    p: TaskStarted = event.data
    legacy_data = {
        **_ctx_dict(p.context),
        "task_id": p.task_id,
        "task_type": p.task_type,
        "started_at": p.started_at,
    }
    return normalize_runtime_event(Event(
        type=EventTypes.TASK_STARTED,
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "task_orchestrator"),
        level=event.level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    ))


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
    return normalize_runtime_event(Event(
        type=EventTypes.TASK_COMPLETED,
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "task_orchestrator"),
        level=event.level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    ))


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
    return normalize_runtime_event(Event(
        type=EventTypes.TASK_FAILED,
        data=legacy_data,
        timestamp=event.timestamp,
        source=str(event.source or "task_orchestrator"),
        level=raised_level,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata or {}),
    ))


_DISPATCH: dict[str, EventTranslator] = {
    EventTypes.TOOL_INVOCATION_COMPLETED: _from_tool_invocation,
    EventTypes.USER_MESSAGE_RECEIVED: _from_user_message,
    EventTypes.ASSISTANT_RESPONSE_PRODUCED: _from_assistant_response,
    EventTypes.SENSOR_EVENT_EMITTED: _from_sensor,
    EventTypes.TASK_STARTED: _from_task_started,
    EventTypes.TASK_COMPLETED: _from_task_completed,
    EventTypes.TASK_FAILED: _from_task_failed,
}


__all__ = ["translate", "EventTranslator"]
