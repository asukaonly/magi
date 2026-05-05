"""Strongly-typed payloads for domain events flowing through the EventBus.

These dataclasses are carried inside Event.data (the existing envelope).
Each subclass corresponds to a single EventTypes constant.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ToolError:
    type: str
    message: str
    truncated: bool = False


@dataclass(frozen=True)
class TaskContext:
    session_id: Optional[str]
    turn_id: Optional[str]
    task_id: Optional[str]
    user_id: Optional[str]


@dataclass(frozen=True)
class ToolInvocationCompleted:
    tool_name: str
    tool_category: str
    success: bool
    duration_ms: float
    started_at: float
    finished_at: float
    args_summary: Optional[str]
    result_summary: Optional[str]
    error: Optional[ToolError]
    context: TaskContext


@dataclass(frozen=True)
class TaskStarted:
    task_id: str
    task_type: str
    started_at: float
    context: TaskContext


@dataclass(frozen=True)
class TaskCompleted:
    task_id: str
    task_type: str
    started_at: float
    finished_at: float
    summary: Optional[str]
    context: TaskContext


@dataclass(frozen=True)
class TaskFailed:
    task_id: str
    task_type: str
    started_at: float
    finished_at: float
    error: ToolError
    context: TaskContext


@dataclass(frozen=True)
class UserMessageReceived:
    content: str
    context: TaskContext
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssistantResponseProduced:
    content: str
    context: TaskContext
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SensorEventEmitted:
    sensor_name: str
    payload: Mapping[str, Any]
    context: TaskContext

    # New (C): extended fields for cross-subscriber projection.
    sensor_id: str = ""
    output_dict: Mapping[str, Any] = field(default_factory=dict)
    metadata_dict: Optional[Mapping[str, Any]] = None
    policy_dict: Mapping[str, Any] = field(default_factory=dict)
    projection_dict: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: float = 0.0
    owner_user_id: Optional[str] = None
    relation_candidates: tuple[Mapping[str, Any], ...] = ()
    allowed_edge_whitelist: tuple[str, ...] = ()
    sensor_fingerprint: Optional[str] = None
    idempotency_key: Optional[str] = None
    memory_event_type: str = "SENSOR_EVENT"
    l2_batch_policy_dict: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class SpanCompleted:
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    node_type: str
    name: str
    status: str
    started_at_ms: int
    ended_at_ms: int
    duration_ms: int
    error: Optional[ToolError]
    result_preview: Optional[str]
    turn_id: Optional[str]
    attributes: Mapping[str, Any] = field(default_factory=dict)
