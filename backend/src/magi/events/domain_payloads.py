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
