"""Tool execution helpers for ToolRegistry."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .registry_stats import ToolExecutionStats
from .schema import Tool, ToolErrorCode, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistryExecutionMixin:
    """Execute registered tools and record execution statistics."""

    _tool_instances: dict[str, Tool]
    _stats: dict[str, ToolExecutionStats]

    def get_tool(self, tool_name: str) -> Tool | None: ...

    async def execute(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Execute a tool.

        Args:
            tool_name: Tool name.
            parameters: Tool parameters.
            context: Execution context.

        Returns:
            Execution result.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} not found",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value
            )

        schema = tool.get_schema()
        stats = self._stats[tool_name]

        if schema.dangerous and "dangerous_tools" not in context.permissions:
            logger.warning(f"Tool {tool_name} requires dangerous_tools permission")
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} requires 'dangerous_tools' permission",
                error_code=ToolErrorCode.PERMISSION_DENIED.value
            )

        if schema.requires_auth and "authenticated" not in context.permissions:
            logger.warning(f"Tool {tool_name} requires authentication")
            return ToolResult(
                success=False,
                error=f"Tool {tool_name} requires authentication",
                error_code=ToolErrorCode.AUTH_REQUIRED.value
            )

        if schema.allowed_roles:
            agent_role = context.env_vars.get("role", "guest")
            if agent_role not in schema.allowed_roles:
                logger.warning(f"Tool {tool_name} requires one of roles: {schema.allowed_roles}")
                return ToolResult(
                    success=False,
                    error=f"Tool {tool_name} requires one of roles: {schema.allowed_roles}",
                    error_code=ToolErrorCode.ROLE_NOT_ALLOWED.value
                )

        if schema.feature_flags:
            enabled = set(context.enabled_features)
            missing = [f for f in schema.feature_flags if f not in enabled]
            if missing:
                logger.warning(f"Tool {tool_name} requires feature flags: {missing}")
                return ToolResult(
                    success=False,
                    error=f"Tool {tool_name} requires feature flags: {missing}",
                    error_code=ToolErrorCode.PERMISSION_DENIED.value
                )

        valid, error_msg = await tool.validate_parameters(parameters)
        if not valid:
            return ToolResult(
                success=False,
                error=error_msg,
                error_code=ToolErrorCode.INVALID_PARAMETERS.value
            )

        start_time = time.time()
        try:
            result = await asyncio.wait_for(
                tool.execute(parameters, context),
                timeout=schema.timeout
            )

            execution_time = time.time() - start_time

            stats.record_call(result.success, execution_time)

            result = await tool.after_execution(result, context)

            return result

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            return ToolResult(
                success=False,
                error=f"Tool execution timeout after {schema.timeout}s",
                error_code=ToolErrorCode.TIMEOUT.value,
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = time.time() - start_time
            stats.record_call(False, execution_time)

            logger.exception(f"Tool {tool_name} execution failed")

            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                execution_time=execution_time
            )

    async def execute_batch(
        self,
        commands: list[dict[str, Any]],
        context: ToolExecutionContext,
        parallel: bool = False
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
                self.execute(cmd["tool"], cmd.get("parameters", {}), context)
                for cmd in commands
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)  # type: ignore[return-value]

        else:
            results = []
            for cmd in commands:
                result = await self.execute(
                    cmd["tool"],
                    cmd.get("parameters", {}),
                    context
                )
                results.append(result)

                if not result.success:
                    break

            return results


__all__ = ["ToolRegistryExecutionMixin"]
