"""Public recorder surface for runtime_trace writes.

This module is the only place RuntimeTraceSubscriber may import from.
The internal writer logic lives in this package (schema, sqlite helpers, etc.).
"""
from __future__ import annotations

import logging

from magi.events.domain_payloads import (
    TaskCompleted,
    TaskFailed,
    TaskStarted,
    ToolInvocationCompleted,
)

logger = logging.getLogger(__name__)


async def record_tool_invocation(
    payload: ToolInvocationCompleted, *, correlation_id: str | None
) -> None:
    logger.debug(
        "runtime_trace.record_tool_invocation",
        extra={
            "tool_name": payload.tool_name,
            "success": payload.success,
            "correlation_id": correlation_id,
        },
    )


async def record_task_started(
    payload: TaskStarted, *, correlation_id: str | None
) -> None:
    logger.debug(
        "runtime_trace.record_task_started",
        extra={
            "task_id": payload.task_id,
            "task_type": payload.task_type,
            "correlation_id": correlation_id,
        },
    )


async def record_task_completed(
    payload: TaskCompleted, *, correlation_id: str | None
) -> None:
    logger.debug(
        "runtime_trace.record_task_completed",
        extra={
            "task_id": payload.task_id,
            "task_type": payload.task_type,
            "correlation_id": correlation_id,
        },
    )


async def record_task_failed(
    payload: TaskFailed, *, correlation_id: str | None
) -> None:
    logger.debug(
        "runtime_trace.record_task_failed",
        extra={
            "task_id": payload.task_id,
            "task_type": payload.task_type,
            "correlation_id": correlation_id,
        },
    )
