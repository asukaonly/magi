"""Single entry point for executing tools and publishing SpanCompleted events.

All business code paths that previously called tool_registry.execute() directly
should now call ToolInvocationService.invoke() instead. tool_registry.execute()
remains the underlying mechanism but is treated as an internal API.

Phase 3 (B): publishes SpanCompleted(node_type='tool_invocation', ...) via
start_async_span.  TOOL_INVOCATION_COMPLETED is no longer produced here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional
from magi_plugin_sdk.runtime import InvocationIdentity

from magi.events.domain_payloads import TaskContext, ToolError
from magi.events.tracing import current_trace_context, start_async_span
from magi.runtime_trace import build_root_span_id, build_trace_id, normalize_turn_id

from .tool_effects import (
    ToolEffectIntent,
    ToolEffectLedger,
    ToolEffectReplayPolicy,
    ToolEffectState,
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
    authorize_call: Callable[[ToolCall], Awaitable[Any | None]] | None = None
    trigger: str = "model"


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


@dataclass(slots=True)
class _EffectAttempt:
    ledger: ToolEffectLedger
    attempt_id: str
    finished: bool = False


class ToolEffectLedgerError(RuntimeError):
    """Raised when effect completion cannot be made durable."""


class ToolInvocationService:
    def __init__(
        self,
        tool_registry,
        *,
        effect_ledger: ToolEffectLedger | None = None,
        require_effect_ledger: bool = False,
    ):
        self._tool_registry = tool_registry
        self._effect_ledger = effect_ledger
        self._require_effect_ledger = bool(require_effect_ledger)

    async def invoke(self, call: ToolCall, ctx: InvocationContext):
        resolver = getattr(self._tool_registry, "resolve_tool_name", None)
        canonical_name = resolver(call.name) if callable(resolver) else call.name
        if isinstance(canonical_name, str) and canonical_name != call.name:
            call = replace(call, name=canonical_name)
        # NOTE: per the Claude Code Skills spec, ``allowed-tools`` is a
        # *pre-approval* list, not a hard deny list. The pre-approval
        # short-circuit lives in
        # ``magi.agent.execution.function_calling.permission`` so tools
        # outside the list still flow through the normal permission
        # gateway (kill list, cached rules, user prompts, …) without
        # being summarily blocked here.
        getter = getattr(self._tool_registry, "get_tool", None)
        tool = getter(call.name) if callable(getter) else None
        from magi.plugins.operations import _BoundOperationTool

        operation_tool = tool if isinstance(tool, _BoundOperationTool) else None
        if operation_tool is not None:
            ctx = operation_tool.prepare_invocation(ctx)
        runtime = _build_invocation_runtime(ctx)
        hook_result = await _apply_pre_tool_hook(call, runtime)
        if hook_result.denied_result is not None:
            return hook_result.denied_result
        if hook_result.modified_call is not None:
            if (
                ctx.authorize_call is None
                and operation_tool is None
                and hook_result.modified_call.args != call.args
            ):
                return _effect_denied_result(
                    call,
                    error_code="HOOK_ARGUMENTS_NOT_AUTHORIZED",
                    message="Hook-modified arguments require a final authorization boundary.",
                )
            call = hook_result.modified_call

        if ctx.authorize_call is not None:
            denial = await ctx.authorize_call(call)
            if denial is not None:
                return denial

        if operation_tool is not None:
            denial = await operation_tool.admit_operation(dict(call.args), ctx)
            if denial is not None:
                return denial

        effect_attempt, effect_denial = await self._begin_effect_attempt(
            call=call,
            ctx=ctx,
            runtime=runtime,
        )
        if effect_denial is not None:
            return effect_denial

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
                await _finish_effect_from_result(effect_attempt, result)
                await _dispatch_post_tool_hook(call, runtime, snapshot)
                return result
            except BaseException as exc:
                await _finish_effect_after_exception(effect_attempt, exc)
                _apply_tool_exception_to_span(span, runtime, exc)
                # span.record_exception is called by start_async_span's except branch
                raise

    async def _begin_effect_attempt(
        self,
        *,
        call: ToolCall,
        ctx: InvocationContext,
        runtime: _InvocationRuntime,
    ) -> tuple[_EffectAttempt | None, Any | None]:
        policy, idempotency_parameter, canonical_tool_name = _resolve_effect_policy(
            self._tool_registry,
            call.name,
        )
        if not policy.requires_ledger:
            return None, None

        ledger, required = self._resolve_effect_ledger()
        if ledger is None:
            if required or isinstance(
                getattr(ctx.execution_context, "invocation", None), InvocationIdentity
            ):
                return None, _effect_denied_result(
                    call,
                    error_code="TOOL_EFFECT_LEDGER_UNAVAILABLE",
                    message="Effectful tool execution requires the durable effect ledger.",
                )
            return None, None

        scope_id = _resolve_effect_scope(ctx, runtime)
        if scope_id is None:
            return None, _effect_denied_result(
                call,
                error_code="TOOL_EFFECT_IDENTITY_REQUIRED",
                message="Effectful tool execution requires a stable task or turn identity.",
            )

        arguments_digest = _stable_digest(dict(call.args))
        idempotency_key_digest = _idempotency_key_digest(
            call.args,
            idempotency_parameter,
        )
        semantic_key = _stable_digest(
            {
                "scope_id": scope_id,
                "tool_name": canonical_tool_name,
                "arguments_digest": arguments_digest,
                "connection_id": getattr(
                    getattr(ctx.execution_context, "invocation", None),
                    "connection_id",
                    None,
                ),
                "principal_id": getattr(
                    getattr(ctx.execution_context, "invocation", None),
                    "principal_id",
                    None,
                ),
            }
        )
        intent = ToolEffectIntent(
            semantic_key=semantic_key,
            scope_id=scope_id,
            user_id=runtime.user_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            task_id=(
                str(ctx.task_context.task_id or "").strip()
                if ctx.task_context is not None
                else None
            )
            or None,
            tool_call_id=runtime.tool_call_id,
            tool_name=canonical_tool_name,
            replay_policy=policy,
            arguments_digest=arguments_digest,
            idempotency_key_digest=idempotency_key_digest,
        )
        try:
            admission = await ledger.begin_tool_effect(
                intent,
                permit_ambiguous_retry=policy.permits_ambiguous_retry(
                    has_idempotency_key=idempotency_key_digest is not None,
                ),
            )
        except Exception:
            logger.exception("Failed to persist tool effect intent", extra={"tool": call.name})
            return None, _effect_denied_result(
                call,
                error_code="TOOL_EFFECT_LEDGER_UNAVAILABLE",
                message="The tool effect intent could not be persisted safely.",
            )
        if not admission.admitted:
            blocked_state = admission.blocked_state
            error_code = (
                "TOOL_EFFECT_ALREADY_COMPLETED"
                if blocked_state is ToolEffectState.SUCCEEDED
                else "TOOL_EFFECT_UNCERTAIN"
            )
            return None, _effect_denied_result(
                call,
                error_code=error_code,
                message=(
                    "A prior matching tool attempt may already have produced its effect. "
                    "Do not retry automatically; reconcile the external state or ask the user."
                ),
                attempt_id=admission.blocked_by_attempt_id,
            )
        assert admission.attempt_id is not None
        return _EffectAttempt(ledger=ledger, attempt_id=admission.attempt_id), None

    def _resolve_effect_ledger(self) -> tuple[ToolEffectLedger | None, bool]:
        if self._effect_ledger is not None:
            return self._effect_ledger, self._require_effect_ledger
        resolver = getattr(self._tool_registry, "resolve_tool_effect_ledger", None)
        if callable(resolver):
            resolved = resolver()
            if isinstance(resolved, tuple) and len(resolved) == 2:
                return resolved[0], bool(resolved[1]) or self._require_effect_ledger
        return None, self._require_effect_ledger


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
        arguments=deepcopy(dict(call.args)),
    )
    if decision.outcome == HookOutcome.DENY:
        return _PreToolHookResult(
            denied_result=_hook_denied_result(call, decision),
            modified_call=None,
        )
    if decision.modified_arguments is not None:
        return _PreToolHookResult(
            denied_result=None,
            modified_call=ToolCall(
                name=call.name,
                args=deepcopy(dict(decision.modified_arguments)),
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
    exc: BaseException,
) -> None:
    span.set_attributes(
        {
            "success": False,
            "execution_time_ms": int((time.monotonic() - runtime.started_mono) * 1000),
            "finished_at": time.time(),
            "error_message": str(exc)[:1000],
        }
    )


def _resolve_effect_policy(
    tool_registry: Any,
    requested_name: str,
) -> tuple[ToolEffectReplayPolicy, str | None, str]:
    tool = None
    getter = getattr(tool_registry, "get_tool", None)
    if callable(getter):
        tool = getter(requested_name)
    schema = None
    get_schema = getattr(tool, "get_schema", None)
    if callable(get_schema):
        schema = get_schema()
    raw_policy = getattr(schema, "effect_replay_policy", None)
    try:
        policy = ToolEffectReplayPolicy(str(raw_policy))
    except ValueError:
        policy = ToolEffectReplayPolicy.UNKNOWN
    raw_parameter = getattr(schema, "effect_idempotency_key_parameter", None)
    idempotency_parameter = (
        str(raw_parameter).strip() if isinstance(raw_parameter, str) else None
    ) or None
    raw_name = getattr(schema, "name", None)
    canonical_name = (str(raw_name).strip() if isinstance(raw_name, str) else "") or str(
        requested_name
    )
    return policy, idempotency_parameter, canonical_name


def _resolve_effect_scope(
    ctx: InvocationContext,
    runtime: _InvocationRuntime,
) -> str | None:
    identity = getattr(ctx.execution_context, "invocation", None)
    if isinstance(identity, InvocationIdentity):
        return f"operation:{identity.connection_id}:{identity.task_id or ctx.task_context.turn_id or identity.invocation_id}"
    task_id = str(ctx.task_context.task_id or "").strip() if ctx.task_context is not None else ""
    if task_id:
        return f"task:{task_id}"
    if runtime.turn_id and str(runtime.turn_id).strip():
        return f"turn:{str(runtime.turn_id).strip()}"
    env_vars = getattr(ctx.execution_context, "env_vars", None)
    env_vars = env_vars if isinstance(env_vars, Mapping) else {}
    run_id = str(env_vars.get("run_id") or "").strip()
    if run_id:
        return f"run:{run_id}"
    execution_task_id = str(getattr(ctx.execution_context, "task_id", "") or "").strip()
    if execution_task_id:
        return f"task:{execution_task_id}"
    if runtime.session_id and str(runtime.session_id).strip():
        return f"session:{str(runtime.session_id).strip()}"
    return None


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _idempotency_key_digest(
    arguments: Mapping[str, Any],
    parameter: str | None,
) -> str | None:
    if parameter is None:
        return None
    value = arguments.get(parameter)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _stable_digest(value)


def _effect_denied_result(
    call: ToolCall,
    *,
    error_code: str,
    message: str,
    attempt_id: str | None = None,
) -> Any:
    from magi.tools.schema import ToolResult

    return ToolResult(
        success=False,
        error=message,
        error_code=error_code,
        metadata={
            "effect_attempt_id": attempt_id,
            "automatic_retry_allowed": False,
            "tool_name": call.name,
        },
    )


_NO_EFFECT_ERROR_CODES = {
    "AUTH_REQUIRED",
    "FEATURE_NOT_ENABLED",
    "INVALID_PARAMETERS",
    "PERMISSION_DENIED",
    "POLICY_BLOCKED",
    "ROLE_NOT_ALLOWED",
    "TOOL_NOT_FOUND",
}


async def _finish_effect_from_result(
    attempt: _EffectAttempt | None,
    result: Any,
) -> None:
    if attempt is None:
        return
    state = _effect_state_from_result(result)
    error_code = str(getattr(result, "error_code", "") or "") or None
    try:
        await attempt.ledger.finish_tool_effect(
            attempt_id=attempt.attempt_id,
            state=state,
            error_code=error_code,
        )
    except Exception as exc:
        raise ToolEffectLedgerError(
            "Tool returned but its effect outcome could not be persisted"
        ) from exc
    attempt.finished = True


def _effect_state_from_result(result: Any) -> ToolEffectState:
    if getattr(result, "operation_status", None) == "uncertain":
        return ToolEffectState.UNCERTAIN
    if bool(getattr(result, "success", False)):
        return ToolEffectState.SUCCEEDED
    metadata = getattr(result, "metadata", None)
    effect_state = (
        str(metadata.get("effect_state") or "").strip().lower()
        if isinstance(metadata, Mapping)
        else ""
    )
    if effect_state == "none":
        return ToolEffectState.FAILED_NO_EFFECT
    if effect_state == "committed":
        return ToolEffectState.SUCCEEDED
    error_code = str(getattr(result, "error_code", "") or "")
    if error_code in _NO_EFFECT_ERROR_CODES:
        return ToolEffectState.FAILED_NO_EFFECT
    return ToolEffectState.UNCERTAIN


async def _finish_effect_after_exception(
    attempt: _EffectAttempt | None,
    exc: BaseException,
) -> None:
    if attempt is None or attempt.finished:
        return

    async def persist_uncertain() -> None:
        await attempt.ledger.finish_tool_effect(
            attempt_id=attempt.attempt_id,
            state=ToolEffectState.UNCERTAIN,
            error_code=type(exc).__name__,
        )

    try:
        await asyncio.shield(persist_uncertain())
        attempt.finished = True
    except BaseException:
        logger.exception(
            "Failed to persist uncertain tool effect outcome",
            extra={"effect_attempt_id": attempt.attempt_id},
        )


def get_tool_invocation_service(tool_registry) -> ToolInvocationService:
    """Build a ToolInvocationService backed by the global tool registry."""
    return ToolInvocationService(tool_registry)
