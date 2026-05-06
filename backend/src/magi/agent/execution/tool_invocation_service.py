"""Single entry point for executing tools and publishing SpanCompleted events.

All business code paths that previously called tool_registry.execute() directly
should now call ToolInvocationService.invoke() instead. tool_registry.execute()
remains the underlying mechanism but is treated as an internal API.

Phase 3 (B): publishes SpanCompleted(node_type='tool_invocation', ...) via
start_async_span.  TOOL_INVOCATION_COMPLETED is no longer produced here.
"""
from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from magi.events.domain_payloads import TaskContext, ToolError
from magi.events.tracing import start_async_span

logger = logging.getLogger(__name__)
_SUMMARY_LIMIT = 500


def _summarize(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) <= _SUMMARY_LIMIT:
        return text
    return text[: _SUMMARY_LIMIT - 3] + "..."


def _safe_json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        text = json.dumps(value, default=str)
    except Exception:
        return _summarize(value)
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
    def __init__(self, tool_registry, event_bus=None):
        self._tool_registry = tool_registry
        # ``event_bus`` is accepted for backward-compatible construction but
        # SpanCompleted is published exclusively via ``container.message_bus``
        # inside ``start_async_span``.
        del event_bus

    async def invoke(self, call: ToolCall, ctx: InvocationContext):
        started_at = time.time()
        started_mono = time.monotonic()
        args_summary = _summarize(dict(call.args))
        arguments_json = _safe_json_dumps(dict(call.args))

        async with start_async_span(node_type="tool_invocation", name=call.name) as span:
            turn_id = ctx.task_context.turn_id if ctx.task_context else None
            span.set_turn_id(turn_id)
            session_id = ctx.task_context.session_id if ctx.task_context else None
            task_id = ctx.task_context.task_id if ctx.task_context else None
            user_id = ctx.task_context.user_id if ctx.task_context else None
            span.set_attributes({
                "tool_name": call.name,
                "tool_call_id": None,
                "tool_category": ctx.tool_category,
                "args_summary": args_summary,
                "arguments_json": arguments_json,
                "started_at": started_at,
                "session_id": session_id,
                "task_id": task_id,
                "user_id": user_id,
            })
            result = None
            try:
                result = await self._tool_registry.execute(
                    call.name, call.args, ctx.execution_context
                )
                success = bool(getattr(result, "success", False))
                duration_ms = int((time.monotonic() - started_mono) * 1000)
                finished_at = time.time()
                result_summary = _summarize(getattr(result, "data", None))
                span.set_attributes({
                    "success": success,
                    "execution_time_ms": duration_ms,
                    "finished_at": finished_at,
                    "result_summary": result_summary,
                    "result_json": None,
                })
                span.set_result_preview(result_summary)
                if not success:
                    span.set_status("error")
                    err_code = str(getattr(result, "error_code", "") or "") or None
                    err_msg = str(getattr(result, "error", "") or "")[:1000] or None
                    span.set_attributes({
                        "error_code": err_code,
                        "error_message": err_msg,
                    })
                    # Build a structured error so SpanCompleted.error is populated for
                    # subscribers that read sp.error (event_translation, runtime_trace_subscriber).
                    span._error = ToolError(
                        type=err_code or "ToolFailure",
                        message=err_msg or "",
                    )
                return result
            except Exception as exc:
                duration_ms = int((time.monotonic() - started_mono) * 1000)
                finished_at = time.time()
                span.set_attributes({
                    "success": False,
                    "execution_time_ms": duration_ms,
                    "finished_at": finished_at,
                    "error_message": str(exc)[:1000],
                })
                # span.record_exception is called by start_async_span's except branch
                raise


def get_tool_invocation_service(tool_registry) -> ToolInvocationService:
    """Build a ToolInvocationService using the global container's message bus.

    Falls back to a no-op bus if the container hasn't been wired yet (e.g. unit tests
    that only construct a host and don't expect events to flow). The no-op bus has
    an async publish() that returns False — span publishing also tolerates an
    unresolved bus.
    """
    from magi.core.container import get_container

    bus = None
    try:
        bus = get_container().message_bus()
    except Exception:
        bus = None

    if bus is None or type(bus).__name__ == "object":
        class _NoopBus:
            async def publish(self, event):
                return False

        bus = _NoopBus()

    return ToolInvocationService(tool_registry, bus)
