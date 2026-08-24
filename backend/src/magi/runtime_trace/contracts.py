"""Typed contracts for runtime trace persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PluginIngressClearStateReader(Protocol):
    """Read the durable generation and cutoff for plugin ingress filtering."""

    async def __call__(self) -> tuple[int, float]: ...


@dataclass(slots=True)
class TraceTurnRecord:
    trace_id: str
    turn_id: str
    session_id: str
    user_id: str
    status: str
    mode: str
    started_at_ms: int = 0
    ended_at_ms: int | None = None
    duration_ms: int | None = None
    user_message_preview: str | None = None
    response_preview: str | None = None
    error_summary: str | None = None
    run_id: str | None = None
    run_revision: int = 0
    continued_from_turn_id: str | None = None
    continued_from_trace_id: str | None = None
    superseded_by_turn_id: str | None = None
    supersession_reason: str | None = None
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass(slots=True)
class TraceSpanRecord:
    span_id: str
    trace_id: str
    turn_id: str
    parent_span_id: str | None
    node_type: str
    name: str
    status: str
    attempt_index: int = 1
    retry_count: int = 0
    iteration: int | None = None
    execution_agent_id: str | None = None
    result_preview: str | None = None
    error_text: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    run_id: str | None = None
    run_revision: int = 0
    started_at_ms: int = 0
    ended_at_ms: int | None = None
    duration_ms: int | None = None
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass(slots=True)
class TraceIntentResolutionRecord:
    span_id: str
    trace_id: str
    turn_id: str
    intent: str
    execution_mode: str
    route_reason: str | None = None
    selected_tools_json: str = "[]"
    selected_worker_type: str | None = None


@dataclass(slots=True)
class TraceLlmCallRecord:
    span_id: str
    trace_id: str
    turn_id: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    thinking_enabled: bool = False
    thinking_depth: str = "none"
    request_preview: str | None = None
    response_preview: str | None = None
    thinking_content: str | None = None


@dataclass(slots=True)
class TraceToolRecord:
    span_id: str
    trace_id: str
    turn_id: str
    tool_name: str
    tool_call_id: str | None = None
    arguments_json: str = "{}"
    success: bool = False
    execution_time_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_preview: str | None = None
    result_json: str | None = None


@dataclass(slots=True)
class RuntimeNotificationRecord:
    notification_id: int
    channel: str
    user_id: str
    session_id: str
    turn_id: str | None = None
    run_id: str | None = None
    run_revision: int = 0
    payload_json: str = "{}"
    created_at_ms: int = 0


@dataclass(slots=True)
class PluginIngressEventRecord:
    event_id: int
    source_kind: str
    producer: str
    plugin_target: str
    event_type: str
    occurred_at_ms: int
    payload_json: str = "{}"
    cursor_key: str | None = None
    status: str = "pending"
    claimed_by: str | None = None
    claimed_at_ms: int | None = None
    processed_at_ms: int | None = None
    last_error: str | None = None
    created_at_ms: int = 0
