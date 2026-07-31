"""Execution path for skill-backed function-calling tools."""

from __future__ import annotations

import getpass
import logging
import os
import time
from typing import Any, cast

from magi.utils.diagnostic_logging import full_content_logging_enabled

from ._tool_execution_contracts import (
    _FunctionCallingToolExecutionHostProtocol,
    _SkillExecutionRequest,
    _SkillResultSnapshot,
    _SkillTraceContext,
)
from .types import ToolCallResult

logger = logging.getLogger(__name__)


class _SkillInvocationEventPublisher:
    """Publish skill invocation facts for downstream memory ingestion."""

    async def publish(
        self,
        *,
        skill_name: str,
        success: bool,
        duration_ms: float,
        started_at: float,
        finished_at: float,
        fork_mode: bool,
        args_summary: str | None,
        result_summary: str | None,
        allowed_tools: tuple[str, ...] | None,
        error_message: str | None,
        session_id: str | None,
        turn_id: str | None,
        user_id: str | None,
    ) -> None:
        try:
            from ....core.container import get_container
            from ....events.events import Event, EventTypes

            bus = get_container().message_bus()
            if bus is None or not hasattr(bus, "publish"):
                return
            payload = self._build_payload(
                skill_name=skill_name,
                success=success,
                duration_ms=duration_ms,
                started_at=started_at,
                finished_at=finished_at,
                fork_mode=fork_mode,
                args_summary=args_summary,
                result_summary=result_summary,
                allowed_tools=allowed_tools,
                error_message=error_message,
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
            )
            await bus.publish(
                Event(
                    type=EventTypes.SKILL_INVOCATION_COMPLETED,
                    data=payload,
                    source="skill_runner",
                )
            )
        except Exception as exc:
            if full_content_logging_enabled():
                logger.exception(
                    "publish SkillInvocationCompleted failed (skill=%s)",
                    skill_name,
                )
            else:
                logger.warning(
                    "publish SkillInvocationCompleted failed "
                    "(skill=%s error_type=%s)",
                    skill_name,
                    type(exc).__name__,
                )

    @staticmethod
    def _build_payload(
        *,
        skill_name: str,
        success: bool,
        duration_ms: float,
        started_at: float,
        finished_at: float,
        fork_mode: bool,
        args_summary: str | None,
        result_summary: str | None,
        allowed_tools: tuple[str, ...] | None,
        error_message: str | None,
        session_id: str | None,
        turn_id: str | None,
        user_id: str | None,
    ) -> Any:
        from ....events.domain_payloads import (
            SkillInvocationCompleted,
            TaskContext,
            ToolError,
        )

        return SkillInvocationCompleted(
            skill_name=skill_name,
            success=success,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            fork_mode=fork_mode,
            args_summary=args_summary,
            result_summary=result_summary,
            allowed_tools=allowed_tools,
            error=(
                ToolError(type="SkillFailure", message=error_message[:1000])
                if error_message
                else None
            ),
            context=TaskContext(
                session_id=session_id,
                turn_id=turn_id,
                task_id=None,
                user_id=user_id,
            ),
        )


class _SkillToolExecutor:
    """Execute skill-backed tool calls and publish skill invocation facts."""

    def __init__(
        self,
        host: _FunctionCallingToolExecutionHostProtocol,
        event_publisher: _SkillInvocationEventPublisher | None = None,
    ) -> None:
        self._host = host
        self._event_publisher = event_publisher or _SkillInvocationEventPublisher()

    async def execute(self, request: _SkillExecutionRequest) -> ToolCallResult:
        if not self._host.skill_runner:
            return ToolCallResult(
                tool_call_id="",
                tool_name=request.skill_name,
                success=False,
                error="Skill runner not available",
            )

        workspace_root = self._host._resolve_execution_workspace(request.execution_workspace)
        arguments_or_result = await self._apply_pre_hook(request, workspace_root)
        if isinstance(arguments_or_result, ToolCallResult):
            return arguments_or_result

        trace = self._build_trace_context(request, arguments_or_result)
        skill_context = self._build_skill_context(request, workspace_root)
        return await self._run_with_span(
            request=request,
            workspace_root=workspace_root,
            arguments=arguments_or_result,
            skill_context=skill_context,
            trace=trace,
        )

    async def _apply_pre_hook(
        self,
        request: _SkillExecutionRequest,
        workspace_root: str,
    ) -> dict[str, Any] | ToolCallResult:
        from ....hooks.contracts import HookEventType, HookOutcome
        from ....hooks.dispatch import dispatch_hook

        decision = await dispatch_hook(
            HookEventType.PRE_SKILL_USE,
            session_id=request.session_id,
            turn_id=request.turn_id,
            user_id=request.user_id,
            workspace=workspace_root,
            skill_name=request.skill_name,
            arguments=request.arguments,
        )
        if decision.outcome == HookOutcome.DENY:
            return ToolCallResult(
                tool_call_id=request.tool_call_id or "",
                tool_name=request.skill_name,
                success=False,
                error=decision.reason or "Skill call denied by hook",
                error_code="HOOK_DENIED",
            )
        if decision.outcome == HookOutcome.MODIFY and decision.modified_arguments is not None:
            return dict(decision.modified_arguments)
        return request.arguments

    def _build_skill_context(
        self,
        request: _SkillExecutionRequest,
        workspace_root: str,
    ) -> dict[str, Any]:
        return {
            "user_id": request.user_id,
            "session_id": f"session_{request.user_id}",
            "workspace": workspace_root,
            "env_vars": {
                "user": getpass.getuser(),
                "HOME": os.path.expanduser("~"),
                "PWD": workspace_root,
            },
        }

    def _build_trace_context(
        self,
        request: _SkillExecutionRequest,
        arguments: dict[str, Any],
    ) -> _SkillTraceContext:
        from ....events.tracing import current_trace_context
        from ....runtime_trace import build_trace_id, normalize_turn_id

        normalized_turn_id = normalize_turn_id(request.turn_id)
        trace_id = (
            build_trace_id(normalized_turn_id)
            if normalized_turn_id and current_trace_context() is None
            else None
        )
        parent_span_id = self._resolve_parent_span_id(request, normalized_turn_id, trace_id)
        return _SkillTraceContext(
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            args_list=self._build_args_list(arguments),
            args_summary=str(arguments)[:500] if arguments else None,
            started_at=time.time(),
            started_mono=time.monotonic(),
        )

    def _resolve_parent_span_id(
        self,
        request: _SkillExecutionRequest,
        normalized_turn_id: str | None,
        trace_id: str | None,
    ) -> str | None:
        if not trace_id or not normalized_turn_id:
            return None
        from ....runtime_trace import build_root_span_id

        if request.iteration is not None and request.iteration > 0 and request.tool_call_id:
            return self._host._build_tool_span_id(
                normalized_turn_id,
                request.iteration,
                request.tool_call_id,
            )
        return cast(str, build_root_span_id(normalized_turn_id))

    @staticmethod
    def _build_args_list(arguments: dict[str, Any]) -> list[str]:
        args_list: list[str] = []
        for value in arguments.values():
            if isinstance(value, str):
                args_list.append(value)
            elif value is not None:
                args_list.append(str(value))
        return args_list

    async def _run_with_span(
        self,
        *,
        request: _SkillExecutionRequest,
        workspace_root: str,
        arguments: dict[str, Any],
        skill_context: dict[str, Any],
        trace: _SkillTraceContext,
    ) -> ToolCallResult:
        from ....events.tracing import start_async_span

        async with start_async_span(
            node_type="skill_call",
            name=request.skill_name,
            trace_id=trace.trace_id,
            parent_span_id=trace.parent_span_id,
        ) as span:
            span.set_turn_id(request.turn_id)
            self._set_initial_span_attributes(span, request, trace)
            try:
                result = await self._host.skill_runner.execute(
                    skill_name=request.skill_name,
                    arguments=trace.args_list,
                    context=skill_context,
                )
                snapshot = self._snapshot_result(result, trace)
                self._record_result_span(span, snapshot)
                await self._publish_skill_event(request, trace, snapshot)
                await self._dispatch_post_hook(request, workspace_root, arguments, snapshot)
                return self._to_tool_call_result(request, snapshot)
            except Exception as exc:
                return await self._handle_exception(span, request, trace, exc)

    @staticmethod
    def _set_initial_span_attributes(
        span: Any,
        request: _SkillExecutionRequest,
        trace: _SkillTraceContext,
    ) -> None:
        span.set_attributes(
            {
                "skill_name": request.skill_name,
                "tool_call_id": request.tool_call_id,
                "args_summary": trace.args_summary,
                "started_at": trace.started_at,
                "session_id": request.session_id,
                "user_id": request.user_id,
            }
        )

    @staticmethod
    def _snapshot_result(result: Any, trace: _SkillTraceContext) -> _SkillResultSnapshot:
        duration_ms = (time.monotonic() - trace.started_mono) * 1000
        content = getattr(result, "content", None)
        metadata = getattr(result, "metadata", {}) or {}
        allowed_tools = metadata.get("allowed_tools")
        allowed_tools_tuple = (
            tuple(str(tool) for tool in allowed_tools)
            if isinstance(allowed_tools, (list, tuple))
            else None
        )
        return _SkillResultSnapshot(
            duration_ms=duration_ms,
            finished_at=time.time(),
            success=bool(getattr(result, "success", False)),
            content=content,
            error=getattr(result, "error", None),
            result_summary=str(content)[:500] if content is not None else None,
            fork_mode=bool(metadata.get("fork_mode") or metadata.get("context") == "fork"),
            allowed_tools=allowed_tools_tuple,
        )

    @staticmethod
    def _record_result_span(span: Any, snapshot: _SkillResultSnapshot) -> None:
        span.set_attributes(
            {
                "success": snapshot.success,
                "execution_time_ms": int(snapshot.duration_ms),
                "finished_at": snapshot.finished_at,
                "result_summary": snapshot.result_summary,
                "fork_mode": snapshot.fork_mode,
                "allowed_tools": (list(snapshot.allowed_tools) if snapshot.allowed_tools else None),
            }
        )
        span.set_result_preview(snapshot.result_summary)
        if snapshot.success:
            return
        span.set_status("error")
        from ....events.domain_payloads import ToolError as _ToolError

        span._error = _ToolError(
            type="SkillFailure",
            message=str(snapshot.error or "")[:1000],
        )

    async def _publish_skill_event(
        self,
        request: _SkillExecutionRequest,
        trace: _SkillTraceContext,
        snapshot: _SkillResultSnapshot,
    ) -> None:
        await self._event_publisher.publish(
            skill_name=request.skill_name,
            success=snapshot.success,
            duration_ms=snapshot.duration_ms,
            started_at=trace.started_at,
            finished_at=snapshot.finished_at,
            fork_mode=snapshot.fork_mode,
            args_summary=trace.args_summary,
            result_summary=snapshot.result_summary,
            allowed_tools=snapshot.allowed_tools,
            error_message=(
                str(snapshot.error) if (not snapshot.success and snapshot.error) else None
            ),
            session_id=request.session_id,
            turn_id=request.turn_id,
            user_id=request.user_id,
        )

    async def _dispatch_post_hook(
        self,
        request: _SkillExecutionRequest,
        workspace_root: str,
        arguments: dict[str, Any],
        snapshot: _SkillResultSnapshot,
    ) -> None:
        from ....hooks.contracts import HookEventType
        from ....hooks.dispatch import dispatch_hook

        await dispatch_hook(
            HookEventType.POST_SKILL_USE,
            session_id=request.session_id,
            turn_id=request.turn_id,
            user_id=request.user_id,
            workspace=workspace_root,
            skill_name=request.skill_name,
            arguments=arguments,
            extra={
                "success": snapshot.success,
                "duration_ms": snapshot.duration_ms,
                "result_summary": snapshot.result_summary,
                "fork_mode": snapshot.fork_mode,
                "error_message": (
                    str(snapshot.error) if (not snapshot.success and snapshot.error) else None
                ),
            },
        )

    @staticmethod
    def _to_tool_call_result(
        request: _SkillExecutionRequest,
        snapshot: _SkillResultSnapshot,
    ) -> ToolCallResult:
        return ToolCallResult(
            tool_call_id=request.tool_call_id or "",
            tool_name=request.skill_name,
            success=snapshot.success,
            data=snapshot.content,
            error=snapshot.error,
        )

    async def _handle_exception(
        self,
        span: Any,
        request: _SkillExecutionRequest,
        trace: _SkillTraceContext,
        exc: Exception,
    ) -> ToolCallResult:
        duration_ms = (time.monotonic() - trace.started_mono) * 1000
        finished_at = time.time()
        if full_content_logging_enabled():
            logger.error("[FunctionCalling] Skill execution error: %s", exc)
        else:
            logger.error(
                "[FunctionCalling] Skill execution error | error_type=%s",
                type(exc).__name__,
            )
        span.set_attributes(
            {
                "success": False,
                "execution_time_ms": int(duration_ms),
                "finished_at": finished_at,
                "error_message": str(exc)[:1000],
            }
        )
        await self._event_publisher.publish(
            skill_name=request.skill_name,
            success=False,
            duration_ms=duration_ms,
            started_at=trace.started_at,
            finished_at=finished_at,
            fork_mode=False,
            args_summary=trace.args_summary,
            result_summary=None,
            allowed_tools=None,
            error_message=str(exc),
            session_id=request.session_id,
            turn_id=request.turn_id,
            user_id=request.user_id,
        )
        return ToolCallResult(
            tool_call_id=request.tool_call_id or "",
            tool_name=request.skill_name,
            success=False,
            error=str(exc),
        )
