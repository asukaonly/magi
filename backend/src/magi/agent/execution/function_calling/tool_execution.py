"""Tool and skill execution helpers for function-calling orchestration."""

from __future__ import annotations

import getpass
import logging
import os
import time
from typing import Any, Protocol, cast

from ...cancel import CancelToken, null_cancel_token
from .types import ToolCall, ToolCallResult

logger = logging.getLogger(__name__)


class _ToolRegistryProtocol(Protocol):
    def get_tool_info(self, tool_name: str) -> dict[str, Any] | None: ...

    async def execute(self, tool_name: str, arguments: dict[str, Any], context: Any) -> Any: ...


class _FunctionCallingToolExecutionHostProtocol(Protocol):
    skill_runner: Any
    tool_registry: _ToolRegistryProtocol
    _FILE_SCAN_TOOLS: set[str]
    _SLOW_SCAN_WARNING_SECONDS: float

    def _resolve_execution_workspace(self, execution_workspace: str | None) -> str: ...

    def _apply_worker_explore_guardrails(
        self,
        *,
        intent: str,
        tool_name: str,
        arguments: dict[str, Any],
        execution_workspace: str | None,
        user_message: str | None,
    ) -> tuple[dict[str, Any], str | None]: ...

    def _classify_guardrail_error_code(self, *, tool_name: str, error_text: str) -> str: ...

    def _normalize_agent_launch_arguments(
        self,
        arguments: dict[str, Any],
        orchestration_strategy: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    def _resolve_permission_gateway(self) -> Any: ...

    async def _gate_tool_call(
        self,
        *,
        tool_call: ToolCall,
        tool_name: str,
        arguments: dict[str, Any],
        agent_id: str,
        session_id: str | None,
        turn_id: str | None,
        workspace: str | None,
        intent: str,
        start_time: float,
        gateway: Any = None,
    ) -> ToolCallResult | None: ...

    def _resolve_scan_root_path(self, path_value: Any, execution_workspace: str | None) -> str: ...


class FunctionCallingToolExecutionMixin:
    """Execute concrete tool calls and skill-backed tools."""

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        user_id: str,
        session_id: str | None,
        turn_id: str | None,
        intent: str,
        execution_agent_id: str,
        execution_workspace: str | None,
        orchestration_strategy: dict[str, Any] | None,
        session_run_id: str | None = None,
        session_run_revision: int = 0,
        user_message: str | None = None,
        iteration: int | None = None,
        cancel_token: CancelToken | None = None,
    ) -> ToolCallResult:
        """Execute a single tool call."""
        host = cast(_FunctionCallingToolExecutionHostProtocol, self)
        start_time = time.time()
        token = cancel_token if cancel_token is not None else null_cancel_token()

        tool_name = tool_call.name
        arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        workspace_root = host._resolve_execution_workspace(execution_workspace)

        if await token.is_cancelled():
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error="Run cancelled before tool execution",
                error_code="CANCELLED",
                execution_time=time.time() - start_time,
            )

        try:
            from ....tools.schema import ToolExecutionContext

            if tool_name.startswith("skill_"):
                skill_name = tool_name.replace("skill_", "")
                return await self._execute_skill(
                    skill_name=skill_name,
                    arguments=arguments,
                    user_id=user_id,
                    execution_workspace=execution_workspace,
                )

            if tool_name == "todo_write" and (
                str(intent or "").startswith("worker_")
                or str(execution_agent_id or "").startswith("worker_")
            ):
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    success=False,
                    error=(
                        "todo_write is owned by the parent task agent; "
                        "worker agents must report progress through worker results."
                    ),
                    error_code="ROLE_NOT_ALLOWED",
                    execution_time=time.time() - start_time,
                )

            arguments, guardrail_error = host._apply_worker_explore_guardrails(
                intent=intent,
                tool_name=tool_name,
                arguments=arguments,
                execution_workspace=execution_workspace,
                user_message=user_message,
            )
            if guardrail_error:
                guardrail_error_code = host._classify_guardrail_error_code(
                    tool_name=tool_name,
                    error_text=guardrail_error,
                )
                logger.warning(
                    "[FunctionCalling] Blocked by guardrail: %s | intent=%s | workspace=%s | args=%s | reason=%s",
                    tool_name,
                    intent,
                    workspace_root,
                    arguments,
                    guardrail_error,
                )
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    success=False,
                    error=guardrail_error,
                    error_code=guardrail_error_code,
                    execution_time=time.time() - start_time,
                )

            permissions = ["authenticated"]
            tool_info = host.tool_registry.get_tool_info(tool_name)
            if tool_info and tool_info.get("dangerous", False):
                permissions.append("dangerous_tools")
            normalized_session_id = str(session_id or "").strip()
            normalized_turn_id = str(turn_id or "").strip()
            target_task_agent_id = normalized_session_id or user_id
            trace_parent_span_id = (
                self._build_tool_span_id(normalized_turn_id, iteration, tool_call.id)
                if normalized_turn_id and iteration is not None and iteration > 0
                else ""
            )

            context = ToolExecutionContext(
                agent_id=execution_agent_id,
                workspace=workspace_root,
                env_vars={
                    "user_id": user_id,
                    "session_id": session_id or "",
                    "turn_id": turn_id or "",
                    "intent": intent,
                    "run_id": session_run_id or "",
                    "run_revision": str(session_run_revision),
                    "target_task_agent_type": "chat",
                    "target_task_agent_id": target_task_agent_id,
                    "trace_id": f"trace:{normalized_turn_id}" if normalized_turn_id else "",
                    "trace_parent_span_id": trace_parent_span_id,
                    "trace_tool_call_id": tool_call.id,
                },
                permissions=permissions,
                cancellation=token,
            )

            if tool_name == "agent":
                arguments = host._normalize_agent_launch_arguments(
                    arguments=arguments,
                    orchestration_strategy=orchestration_strategy,
                )

            gateway = host._resolve_permission_gateway()
            if gateway is not None:
                denied_result = await host._gate_tool_call(
                    tool_call=tool_call,
                    tool_name=tool_name,
                    arguments=arguments,
                    agent_id=execution_agent_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    workspace=context.workspace,
                    intent=intent,
                    start_time=start_time,
                    gateway=gateway,
                )
                if denied_result is not None:
                    return denied_result

            if tool_name in host._FILE_SCAN_TOOLS:
                logger.info(
                    "[FunctionCalling] Executing scan tool: %s | workspace=%s | path=%s | args=%s",
                    tool_name,
                    workspace_root,
                    host._resolve_scan_root_path(arguments.get("path"), execution_workspace),
                    arguments,
                )
            else:
                logger.info(
                    "[FunctionCalling] Executing: %s with args: %s",
                    tool_name,
                    arguments,
                )
            from ...execution.tool_invocation_service import (
                InvocationContext,
                ToolCall as _ServiceToolCall,
                get_tool_invocation_service,
            )
            from ....events.domain_payloads import TaskContext

            if not hasattr(host, "_tool_invocation_service"):
                host._tool_invocation_service = get_tool_invocation_service(host.tool_registry)

            result = await host._tool_invocation_service.invoke(
                _ServiceToolCall(name=tool_name, args=arguments),
                InvocationContext(
                    tool_category="external_tool",
                    task_context=TaskContext(
                        session_id=session_id,
                        turn_id=turn_id,
                        task_id=getattr(context, "task_id", None),
                        user_id=user_id,
                    ),
                    execution_context=context,
                ),
            )
            execution_time = time.time() - start_time
            if not result.success:
                logger.warning(
                    "[FunctionCalling] Tool failed: %s | error=%s | code=%s",
                    tool_name,
                    result.error,
                    result.error_code,
                )
            if (
                tool_name in host._FILE_SCAN_TOOLS
                and execution_time >= host._SLOW_SCAN_WARNING_SECONDS
            ):
                logger.warning(
                    "[FunctionCalling] Slow scan tool: %s | workspace=%s | path=%s | elapsed_ms=%.1f | args=%s",
                    tool_name,
                    workspace_root,
                    host._resolve_scan_root_path(arguments.get("path"), execution_workspace),
                    execution_time * 1000,
                    arguments,
                )

            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=result.success,
                data=result.data,
                error=result.error,
                error_code=getattr(result, "error_code", None),
                execution_time=execution_time,
            )

        except Exception as exc:
            logger.error("[FunctionCalling] Tool execution error: %s", exc)
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=str(exc),
                execution_time=time.time() - start_time,
            )

    async def _execute_skill(
        self,
        skill_name: str,
        arguments: dict[str, Any],
        user_id: str,
        execution_workspace: str | None = None,
    ) -> ToolCallResult:
        """Execute a skill-backed tool call."""
        host = cast(_FunctionCallingToolExecutionHostProtocol, self)
        if not host.skill_runner:
            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=False,
                error="Skill runner not available",
            )

        workspace_root = host._resolve_execution_workspace(execution_workspace)
        skill_context = {
            "user_id": user_id,
            "session_id": f"session_{user_id}",
            "workspace": workspace_root,
            "env_vars": {
                "user": getpass.getuser(),
                "HOME": os.path.expanduser("~"),
                "PWD": workspace_root,
            },
        }

        try:
            args_list: list[str] = []
            if arguments:
                for value in arguments.values():
                    if isinstance(value, str):
                        args_list.append(value)
                    elif value is not None:
                        args_list.append(str(value))

            result = await host.skill_runner.execute(
                skill_name=skill_name,
                arguments=args_list,
                context=skill_context,
            )

            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=result.success,
                data=result.content,
                error=result.error,
            )

        except Exception as exc:
            logger.error("[FunctionCalling] Skill execution error: %s", exc)
            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=False,
                error=str(exc),
            )


__all__ = ["FunctionCallingToolExecutionMixin"]
