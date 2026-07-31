"""Tool execution helpers for ToolRegistry."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..utils.diagnostic_logging import full_content_logging_enabled
from .registry_stats import ToolExecutionStats
from .schema import Tool, ToolErrorCode, ToolExecutionContext, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ToolInvocation:
    requested_name: str
    canonical_name: str
    tool: Tool
    schema: ToolSchema
    stats: ToolExecutionStats


def _normalize_tool_name(tool_name: str) -> str:
    return str(tool_name or "").strip()


def _failure_result(
    *,
    error: str,
    error_code: ToolErrorCode,
    execution_time: float | None = None,
) -> ToolResult:
    result_kwargs: dict[str, Any] = {
        "success": False,
        "error": error,
        "error_code": error_code.value,
    }
    if execution_time is not None:
        result_kwargs["execution_time"] = execution_time
    return ToolResult(**result_kwargs)


def _tool_not_found_result(tool_name: str) -> ToolResult:
    return _failure_result(
        error=f"Tool {tool_name} not found",
        error_code=ToolErrorCode.TOOL_NOT_FOUND,
    )


def _invalid_parameters_result(error_msg: str) -> ToolResult:
    return _failure_result(
        error=error_msg,
        error_code=ToolErrorCode.INVALID_PARAMETERS,
    )


def _timeout_result(timeout: float, execution_time: float) -> ToolResult:
    return _failure_result(
        error=f"Tool execution timeout after {timeout}s",
        error_code=ToolErrorCode.TIMEOUT,
        execution_time=execution_time,
    )


def _execution_error_result(error: Exception, execution_time: float) -> ToolResult:
    return _failure_result(
        error=str(error),
        error_code=ToolErrorCode.EXECUTION_ERROR,
        execution_time=execution_time,
    )


def _schema_permission_result(
    schema: ToolSchema,
    tool_name: str,
    context: ToolExecutionContext,
) -> ToolResult | None:
    if schema.dangerous and "dangerous_tools" not in context.permissions:
        logger.warning("Tool %s requires dangerous_tools permission", tool_name)
        return _failure_result(
            error=f"Tool {tool_name} requires 'dangerous_tools' permission",
            error_code=ToolErrorCode.PERMISSION_DENIED,
        )

    if schema.requires_auth and "authenticated" not in context.permissions:
        logger.warning("Tool %s requires authentication", tool_name)
        return _failure_result(
            error=f"Tool {tool_name} requires authentication",
            error_code=ToolErrorCode.AUTH_REQUIRED,
        )

    if schema.allowed_roles:
        agent_role = context.env_vars.get("role", "guest")
        if agent_role not in schema.allowed_roles:
            logger.warning("Tool %s requires one of roles: %s", tool_name, schema.allowed_roles)
            return _failure_result(
                error=f"Tool {tool_name} requires one of roles: {schema.allowed_roles}",
                error_code=ToolErrorCode.ROLE_NOT_ALLOWED,
            )

    if schema.feature_flags:
        enabled = set(context.enabled_features)
        missing = [flag for flag in schema.feature_flags if flag not in enabled]
        if missing:
            logger.warning("Tool %s requires feature flags: %s", tool_name, missing)
            return _failure_result(
                error=f"Tool {tool_name} requires feature flags: {missing}",
                error_code=ToolErrorCode.PERMISSION_DENIED,
            )

    return None


class ToolRegistryExecutionMixin:
    """Execute registered tools and record execution statistics."""

    _tool_instances: dict[str, Tool]
    _stats: dict[str, ToolExecutionStats]

    def get_tool(self, tool_name: str) -> Tool | None: ...
    def resolve_tool_name(self, tool_name: str) -> str: ...
    def _is_tool_enabled(self, tool_name: str) -> bool: ...

    async def execute(
        self, tool_name: str, parameters: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """
        Execute a tool.

        Args:
            tool_name: Tool name.
            parameters: Tool parameters.
            context: Execution context.

        Returns:
            Execution result.

        .. deprecated::
            Direct callers in business code MUST go through ToolInvocationService.invoke().
            Calling tool_registry.execute() directly bypasses ToolInvocationCompleted
            publication and breaks L4 / runtime_trace pipelines.
        """
        requested_tool_name = _normalize_tool_name(tool_name)
        invocation = self._build_invocation(requested_tool_name)
        if invocation is None:
            return _tool_not_found_result(requested_tool_name)

        blocked = self._check_execution_policy(invocation, tool_name, context)
        if blocked:
            return blocked

        invalid = await self._validate_invocation_parameters(invocation, parameters)
        if invalid:
            return invalid

        return await self._run_invocation(invocation, parameters, context, tool_name)

    def _build_invocation(self, requested_tool_name: str) -> _ToolInvocation | None:
        canonical_tool_name = self.resolve_tool_name(requested_tool_name)
        tool = self.get_tool(canonical_tool_name)
        if not tool:
            return None

        return _ToolInvocation(
            requested_name=requested_tool_name,
            canonical_name=canonical_tool_name,
            tool=tool,
            schema=tool.get_schema(),
            stats=self._stats[canonical_tool_name],
        )

    def _check_execution_policy(
        self,
        invocation: _ToolInvocation,
        display_tool_name: str,
        context: ToolExecutionContext,
    ) -> ToolResult | None:
        if not self._is_tool_enabled(invocation.canonical_name):
            logger.warning("Tool %s is disabled by configuration", invocation.canonical_name)
            return _failure_result(
                error=f"Tool {invocation.canonical_name} is disabled by configuration",
                error_code=ToolErrorCode.POLICY_BLOCKED,
            )

        return _schema_permission_result(invocation.schema, display_tool_name, context)

    async def _validate_invocation_parameters(
        self,
        invocation: _ToolInvocation,
        parameters: dict[str, Any],
    ) -> ToolResult | None:
        valid, error_msg = await invocation.tool.validate_parameters(parameters)
        if valid:
            return None
        return _invalid_parameters_result(error_msg)

    async def _run_invocation(
        self,
        invocation: _ToolInvocation,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
        display_tool_name: str,
    ) -> ToolResult:
        start_time = time.time()
        try:
            result = await self._execute_tool_body(invocation, parameters, context)
            execution_time = time.time() - start_time
            invocation.stats.record_call(result.success, execution_time)
            return await invocation.tool.after_execution(result, context)
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            invocation.stats.record_call(False, execution_time)
            return _timeout_result(invocation.schema.timeout, execution_time)
        except Exception as e:
            execution_time = time.time() - start_time
            invocation.stats.record_call(False, execution_time)
            if full_content_logging_enabled():
                logger.exception("Tool %s execution failed", display_tool_name)
            else:
                logger.warning(
                    "Tool %s execution failed | error_type=%s",
                    display_tool_name,
                    type(e).__name__,
                )
            return _execution_error_result(e, execution_time)

    async def _execute_tool_body(
        self,
        invocation: _ToolInvocation,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        return await asyncio.wait_for(
            invocation.tool.execute(parameters, context),
            timeout=invocation.schema.timeout,
        )

    async def execute_batch(
        self, commands: list[dict[str, Any]], context: ToolExecutionContext, parallel: bool = False
    ) -> list[ToolResult]:
        """
        Execute multiple tools in batch.

        Args:
            commands: Command list [{"tool": name, "parameters": {...}}, ...].
            context: Execution context.
            parallel: Whether to execute in parallel.

        Returns:
            List of results.
        """
        if parallel:
            tasks = [
                self.execute(cmd["tool"], cmd.get("parameters", {}), context) for cmd in commands
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)  # type: ignore[return-value]

        else:
            results = []
            for cmd in commands:
                result = await self.execute(cmd["tool"], cmd.get("parameters", {}), context)
                results.append(result)

                if not result.success:
                    break

            return results


__all__ = ["ToolRegistryExecutionMixin"]
