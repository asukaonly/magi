"""Execution path for registry-backed function-calling tools."""

from __future__ import annotations

import logging
import json
import time
from typing import Any

from magi.tools.capabilities import build_tool_capabilities
from magi.utils.diagnostic_logging import full_content_logging_enabled

from ._tool_execution_contracts import (
    _FunctionCallingToolExecutionHostProtocol,
    _RegisteredToolExecutionRequest,
)
from .types import ToolCallResult

logger = logging.getLogger(__name__)


def _execution_task_id(request: _RegisteredToolExecutionRequest) -> str | None:
    agent_id = str(request.execution_agent_id or "").strip()
    prefix = "background:"
    if agent_id.startswith(prefix):
        return agent_id[len(prefix) :].strip() or None
    return None


class _RegisteredToolExecutor:
    """Execute non-skill tools through the shared invocation service."""

    def __init__(self, host: _FunctionCallingToolExecutionHostProtocol) -> None:
        self._host = host

    async def execute(self, request: _RegisteredToolExecutionRequest) -> ToolCallResult:
        guarded_arguments = self._apply_worker_guardrails(request)
        if isinstance(guarded_arguments, ToolCallResult):
            return guarded_arguments

        context = self._build_execution_context(request)
        arguments = self._normalize_launch_arguments(request, guarded_arguments)

        denied_result = await self._check_permission_gateway(
            request=request,
            arguments=arguments,
            workspace=context.workspace,
        )
        if denied_result is not None:
            return denied_result

        self._log_tool_start(request, arguments)
        invocation_result = await self._invoke_tool(request, arguments, context)
        return self._to_tool_call_result(request, arguments, invocation_result)

    def _apply_worker_guardrails(
        self, request: _RegisteredToolExecutionRequest
    ) -> dict[str, Any] | ToolCallResult:
        arguments, guardrail_error = self._host._apply_execution_guardrails(
            execution_preset=request.execution_preset,
            tool_name=request.tool_name,
            arguments=request.arguments,
            execution_workspace=request.execution_workspace,
        )
        if not guardrail_error:
            return arguments

        guardrail_error_code = self._host._classify_guardrail_error_code(
            tool_name=request.tool_name,
            error_text=guardrail_error,
        )
        if full_content_logging_enabled():
            logger.warning(
                "[FunctionCalling] Blocked by guardrail: %s | execution_preset=%s | "
                "workspace=%s | args=%s | reason=%s",
                request.tool_name,
                request.execution_preset,
                request.workspace_root,
                arguments,
                guardrail_error,
            )
        else:
            logger.warning(
                "[FunctionCalling] Blocked by guardrail: %s | "
                "argument_names=%s | reason_chars=%d",
                request.tool_name,
                sorted(arguments),
                len(str(guardrail_error or "")),
            )
        return ToolCallResult(
            tool_call_id=request.tool_call.id,
            tool_name=request.tool_name,
            success=False,
            error=guardrail_error,
            error_code=guardrail_error_code,
            execution_time=time.time() - request.start_time,
        )

    def _build_execution_context(self, request: _RegisteredToolExecutionRequest) -> Any:
        from ....tools.schema import ToolExecutionContext

        tool_info = self._host.tool_registry.get_tool_info(request.tool_name)
        permissions = ["authenticated"]
        if tool_info and tool_info.get("dangerous", False):
            permissions.append("dangerous_tools")

        normalized_session_id = str(request.session_id or "").strip()
        normalized_turn_id = str(request.turn_id or "").strip()
        target_task_agent_id = normalized_session_id or request.user_id
        trace_parent_span_id = (
            self._host._build_tool_span_id(
                normalized_turn_id,
                request.iteration,
                request.tool_call.id,
            )
            if normalized_turn_id and request.iteration is not None and request.iteration > 0
            else ""
        )
        return ToolExecutionContext(
            agent_id=request.execution_agent_id,
            task_id=_execution_task_id(request),
            workspace=request.workspace_root,
            env_vars={
                "user_id": request.user_id,
                "session_id": request.session_id or "",
                "turn_id": request.turn_id or "",
                "execution_preset": request.execution_preset,
                "run_id": request.run_id,
                "run_revision": str(request.run_revision),
                "parent_reasoning_policy": json.dumps(
                    request.reasoning_policy.to_dict()
                    if request.reasoning_policy is not None
                    else {}
                ),
                "parent_reasoning_state": json.dumps(
                    request.reasoning_state.to_dict() if request.reasoning_state is not None else {}
                ),
                "target_task_agent_type": "chat",
                "target_task_agent_id": target_task_agent_id,
                "trace_id": f"trace:{normalized_turn_id}" if normalized_turn_id else "",
                "trace_parent_span_id": trace_parent_span_id,
                "trace_tool_call_id": request.tool_call.id,
                "current_user_text": request.user_message or "",
                "memory_context_workspace": request.execution_workspace or "",
            },
            permissions=permissions,
            cancellation=request.token,
            capabilities=build_tool_capabilities(),
        )

    def _normalize_launch_arguments(
        self,
        request: _RegisteredToolExecutionRequest,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if request.tool_name != "agent":
            return arguments
        return self._host._normalize_agent_launch_arguments(
            arguments=arguments,
        )

    async def _check_permission_gateway(
        self,
        *,
        request: _RegisteredToolExecutionRequest,
        arguments: dict[str, Any],
        workspace: str | None,
    ) -> ToolCallResult | None:
        return await self._host._gate_tool_call(
            tool_call=request.tool_call,
            tool_name=request.tool_name,
            arguments=arguments,
            agent_id=request.execution_agent_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            workspace=workspace,
            execution_preset=request.execution_preset,
            start_time=request.start_time,
            skill_preapproval_rules=request.skill_preapproval_rules,
        )

    def _log_tool_start(
        self,
        request: _RegisteredToolExecutionRequest,
        arguments: dict[str, Any],
    ) -> None:
        if not full_content_logging_enabled():
            logger.info(
                "[FunctionCalling] Executing: %s | argument_names=%s",
                request.tool_name,
                sorted(arguments),
            )
            return
        if request.tool_name in self._host._FILE_SCAN_TOOLS:
            logger.info(
                "[FunctionCalling] Executing scan tool: %s | workspace=%s | path=%s | args=%s",
                request.tool_name,
                request.workspace_root,
                self._host._resolve_scan_root_path(
                    arguments.get("path"), request.execution_workspace
                ),
                arguments,
            )
            return
        logger.info(
            "[FunctionCalling] Executing: %s with args: %s",
            request.tool_name,
            arguments,
        )

    async def _invoke_tool(
        self,
        request: _RegisteredToolExecutionRequest,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        from ....events.domain_payloads import TaskContext
        from ...execution.tool_invocation_service import (
            InvocationContext,
            ToolCall as _ServiceToolCall,
            get_tool_invocation_service,
        )

        service = getattr(self._host, "_tool_invocation_service", None)
        if service is None:
            service = get_tool_invocation_service(self._host.tool_registry)
            self._host._tool_invocation_service = service

        return await service.invoke(
            _ServiceToolCall(name=request.tool_name, args=arguments),
            InvocationContext(
                tool_category="external_tool",
                task_context=TaskContext(
                    session_id=request.session_id,
                    turn_id=request.turn_id,
                    task_id=getattr(context, "task_id", None),
                    user_id=request.user_id,
                ),
                execution_context=context,
            ),
        )

    def _to_tool_call_result(
        self,
        request: _RegisteredToolExecutionRequest,
        arguments: dict[str, Any],
        result: Any,
    ) -> ToolCallResult:
        execution_time = time.time() - request.start_time
        if not result.success:
            if full_content_logging_enabled():
                logger.warning(
                    "[FunctionCalling] Tool failed: %s | error=%s | code=%s",
                    request.tool_name,
                    result.error,
                    result.error_code,
                )
            else:
                logger.warning(
                    "[FunctionCalling] Tool failed: %s | error_chars=%d | code=%s",
                    request.tool_name,
                    len(str(result.error or "")),
                    result.error_code,
                )
        self._log_slow_scan(request, arguments, execution_time)
        return ToolCallResult(
            tool_call_id=request.tool_call.id,
            tool_name=request.tool_name,
            success=result.success,
            data=result.data,
            error=result.error,
            error_code=getattr(result, "error_code", None),
            execution_time=execution_time,
        )

    def _log_slow_scan(
        self,
        request: _RegisteredToolExecutionRequest,
        arguments: dict[str, Any],
        execution_time: float,
    ) -> None:
        if (
            request.tool_name not in self._host._FILE_SCAN_TOOLS
            or execution_time < self._host._SLOW_SCAN_WARNING_SECONDS
        ):
            return
        if not full_content_logging_enabled():
            logger.warning(
                "[FunctionCalling] Slow scan tool: %s | elapsed_ms=%.1f | " "argument_names=%s",
                request.tool_name,
                execution_time * 1000,
                sorted(arguments),
            )
            return
        logger.warning(
            "[FunctionCalling] Slow scan tool: %s | workspace=%s | path=%s | elapsed_ms=%.1f | args=%s",
            request.tool_name,
            request.workspace_root,
            self._host._resolve_scan_root_path(arguments.get("path"), request.execution_workspace),
            execution_time * 1000,
            arguments,
        )
