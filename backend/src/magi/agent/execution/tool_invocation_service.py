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
from magi.events.tracing import current_trace_context, start_async_span
from magi.runtime_trace import build_root_span_id, build_trace_id, normalize_turn_id

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


@dataclass(slots=True)
class _InvocationRuntime:
    started_at: float
    started_mono: float
    session_id: str | None
    turn_id: str | None
    user_id: str | None
    workspace: str | None
    trace_id: str | None
    parent_span_id: str | None
    tool_call_id: str | None


@dataclass(slots=True)
class _ToolExecutionSnapshot:
    success: bool
    duration_ms: int
    finished_at: float
    result_summary: str | None
    error_code: str | None
    error_message: str | None


@dataclass(slots=True)
class _PreToolHookResult:
    denied_result: Any | None
    modified_call: ToolCall | None


class ToolInvocationService:
    def __init__(self, tool_registry):
        self._tool_registry = tool_registry

    async def invoke(self, call: ToolCall, ctx: InvocationContext):
        # NOTE: per the Claude Code Skills spec, ``allowed-tools`` is a
        # *pre-approval* list, not a hard deny list. The pre-approval
        # short-circuit lives in
        # ``magi.agent.execution.function_calling.permission`` so tools
        # outside the list still flow through the normal permission
        # gateway (kill list, cached rules, user prompts, …) without
        # being summarily blocked here.
        runtime = _build_invocation_runtime(ctx)
        hook_result = await _apply_pre_tool_hook(call, runtime)
        if hook_result.denied_result is not None:
            return hook_result.denied_result
        if hook_result.modified_call is not None:
            call = hook_result.modified_call

        async with start_async_span(
            node_type="tool_invocation",
            name=call.name,
            trace_id=runtime.trace_id,
            parent_span_id=runtime.parent_span_id,
        ) as span:
            span.set_turn_id(runtime.turn_id)
            span.set_attributes(_initial_span_attributes(call, ctx, runtime))
            try:
                result = await self._tool_registry.execute(
                    call.name, call.args, ctx.execution_context
                )
                snapshot = _build_tool_execution_snapshot(result, runtime)
                _apply_tool_result_to_span(span, snapshot)
                await _dispatch_post_tool_hook(call, runtime, snapshot)
                return result
            except Exception as exc:
                _apply_tool_exception_to_span(span, runtime, exc)
                # span.record_exception is called by start_async_span's except branch
                raise


def _build_invocation_runtime(ctx: InvocationContext) -> _InvocationRuntime:
    turn_id = ctx.task_context.turn_id if ctx.task_context else None
    env_vars = getattr(ctx.execution_context, "env_vars", None)
    env_vars = env_vars if isinstance(env_vars, Mapping) else {}
    normalized_turn_id = normalize_turn_id(turn_id)
    context_trace_id = str(env_vars.get("trace_id") or "").strip() or None
    context_parent_span_id = str(env_vars.get("trace_parent_span_id") or "").strip() or None
    trace_id = _resolve_trace_id(normalized_turn_id, context_trace_id)
    return _InvocationRuntime(
        started_at=time.time(),
        started_mono=time.monotonic(),
        session_id=ctx.task_context.session_id if ctx.task_context else None,
        turn_id=turn_id,
        user_id=ctx.task_context.user_id if ctx.task_context else None,
        workspace=getattr(ctx.execution_context, "workspace", None),
        trace_id=trace_id,
        parent_span_id=_resolve_parent_span_id(
            trace_id,
            normalized_turn_id,
            context_parent_span_id,
        ),
        tool_call_id=str(env_vars.get("trace_tool_call_id") or "").strip() or None,
    )


def _resolve_trace_id(
    normalized_turn_id: str | None,
    context_trace_id: str | None,
) -> str | None:
    if not normalized_turn_id or current_trace_context() is not None:
        return None
    return context_trace_id or build_trace_id(normalized_turn_id)


def _resolve_parent_span_id(
    trace_id: str | None,
    normalized_turn_id: str | None,
    context_parent_span_id: str | None,
) -> str | None:
    if trace_id is None or normalized_turn_id is None:
        return None
    return context_parent_span_id or build_root_span_id(normalized_turn_id)


async def _apply_pre_tool_hook(
    call: ToolCall,
    runtime: _InvocationRuntime,
) -> _PreToolHookResult:
    from magi.hooks.contracts import HookEventType, HookOutcome
    from magi.hooks.dispatch import dispatch_hook

    decision = await dispatch_hook(
        HookEventType.PRE_TOOL_USE,
        session_id=runtime.session_id,
        turn_id=runtime.turn_id,
        user_id=runtime.user_id,
        workspace=runtime.workspace,
        tool_name=call.name,
        arguments=dict(call.args),
    )
    if decision.outcome == HookOutcome.DENY:
        return _PreToolHookResult(
            denied_result=_hook_denied_result(call, decision),
            modified_call=None,
        )
    if decision.outcome == HookOutcome.MODIFY and decision.modified_arguments is not None:
        return _PreToolHookResult(
            denied_result=None,
            modified_call=ToolCall(
                name=call.name,
                args=dict(decision.modified_arguments),
            ),
        )
    return _PreToolHookResult(denied_result=None, modified_call=None)


def _hook_denied_result(call: ToolCall, decision: Any) -> Any:
    from magi.agent.execution.function_calling.types import ToolCallResult

    return ToolCallResult(
        tool_call_id="",
        tool_name=call.name,
        success=False,
        error=decision.reason or "Tool call denied by hook",
        error_code="HOOK_DENIED",
        execution_time=0.0,
    )


def _initial_span_attributes(
    call: ToolCall,
    ctx: InvocationContext,
    runtime: _InvocationRuntime,
) -> dict[str, Any]:
    return {
        "tool_name": call.name,
        "tool_call_id": runtime.tool_call_id,
        "tool_category": ctx.tool_category,
        "args_summary": _summarize(dict(call.args)),
        "arguments_json": _safe_json_dumps(dict(call.args)),
        "started_at": runtime.started_at,
        "session_id": runtime.session_id,
        "task_id": ctx.task_context.task_id if ctx.task_context else None,
        "user_id": runtime.user_id,
    }


def _build_tool_execution_snapshot(
    result: Any,
    runtime: _InvocationRuntime,
) -> _ToolExecutionSnapshot:
    return _ToolExecutionSnapshot(
        success=bool(getattr(result, "success", False)),
        duration_ms=int((time.monotonic() - runtime.started_mono) * 1000),
        finished_at=time.time(),
        result_summary=_summarize(getattr(result, "data", None)),
        error_code=str(getattr(result, "error_code", "") or "") or None,
        error_message=str(getattr(result, "error", "") or "")[:1000] or None,
    )


def _apply_tool_result_to_span(span: Any, snapshot: _ToolExecutionSnapshot) -> None:
    span.set_attributes(
        {
            "success": snapshot.success,
            "execution_time_ms": snapshot.duration_ms,
            "finished_at": snapshot.finished_at,
            "result_summary": snapshot.result_summary,
            "result_json": None,
        }
    )
    span.set_result_preview(snapshot.result_summary)
    if snapshot.success:
        return

    span.set_status("error")
    span.set_attributes(
        {
            "error_code": snapshot.error_code,
            "error_message": snapshot.error_message,
        }
    )
    # Keep SpanCompleted.error populated for subscribers that read sp.error.
    span._error = ToolError(
        type=snapshot.error_code or "ToolFailure",
        message=snapshot.error_message or "",
    )


async def _dispatch_post_tool_hook(
    call: ToolCall,
    runtime: _InvocationRuntime,
    snapshot: _ToolExecutionSnapshot,
) -> None:
    from magi.hooks.contracts import HookEventType
    from magi.hooks.dispatch import dispatch_hook

    await dispatch_hook(
        HookEventType.POST_TOOL_USE,
        session_id=runtime.session_id,
        turn_id=runtime.turn_id,
        user_id=runtime.user_id,
        workspace=runtime.workspace,
        tool_name=call.name,
        arguments=dict(call.args),
        extra={
            "success": snapshot.success,
            "duration_ms": snapshot.duration_ms,
            "result_summary": snapshot.result_summary,
            "error_code": snapshot.error_code,
            "error_message": snapshot.error_message,
        },
    )


def _apply_tool_exception_to_span(
    span: Any,
    runtime: _InvocationRuntime,
    exc: Exception,
) -> None:
    span.set_attributes(
        {
            "success": False,
            "execution_time_ms": int((time.monotonic() - runtime.started_mono) * 1000),
            "finished_at": time.time(),
            "error_message": str(exc)[:1000],
        }
    )


def get_tool_invocation_service(tool_registry) -> ToolInvocationService:
    """Build a ToolInvocationService backed by the global tool registry."""
    return ToolInvocationService(tool_registry)
