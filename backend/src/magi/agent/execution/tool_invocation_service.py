"""Single entry point for executing tools and publishing ToolInvocationCompleted.

All business code paths that previously called tool_registry.execute() directly
should now call ToolInvocationService.invoke() instead. tool_registry.execute()
remains the underlying mechanism but is treated as an internal API.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    TaskContext, ToolError, ToolInvocationCompleted,
)

logger = logging.getLogger(__name__)
_SUMMARY_LIMIT = 500


def _summarize(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) <= _SUMMARY_LIMIT:
        return text
    return text[: _SUMMARY_LIMIT - 3] + "..."


@dataclass
class ToolCall:
    name: str
    args: Mapping[str, Any]


@dataclass
class InvocationContext:
    tool_category: str
    task_context: TaskContext
    execution_context: Any


class ToolInvocationService:
    def __init__(self, tool_registry, event_bus):
        self._tool_registry = tool_registry
        self._event_bus = event_bus

    async def invoke(self, call: ToolCall, ctx: InvocationContext):
        started_at = time.time()
        started_mono = time.monotonic()
        success = False
        error_obj: Optional[ToolError] = None
        result = None
        try:
            result = await self._tool_registry.execute(call.name, call.args, ctx.execution_context)
            success = bool(getattr(result, "success", False))
            if not success:
                error_obj = ToolError(
                    type=str(getattr(result, "error_code", "ToolFailure") or "ToolFailure"),
                    message=str(getattr(result, "error", "") or "")[:1000],
                )
            return result
        except Exception as exc:
            error_obj = ToolError(
                type=type(exc).__name__,
                message=str(exc)[:1000],
            )
            raise
        finally:
            finished_at = time.time()
            duration_ms = (time.monotonic() - started_mono) * 1000
            try:
                payload = ToolInvocationCompleted(
                    tool_name=call.name,
                    tool_category=ctx.tool_category,
                    success=success,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    finished_at=finished_at,
                    args_summary=_summarize(call.args),
                    result_summary=_summarize(getattr(result, "data", None)) if result is not None else None,
                    error=error_obj,
                    context=ctx.task_context,
                )
                await self._event_bus.publish(Event(
                    type=EventTypes.TOOL_INVOCATION_COMPLETED,
                    data=payload,
                    source="tool_invocation_service",
                ))
            except Exception:
                logger.exception("publish ToolInvocationCompleted failed")
