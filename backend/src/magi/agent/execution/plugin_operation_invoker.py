"""Bind plugin operations to the governed host tool execution boundary."""

from __future__ import annotations

from typing import Any

from magi_plugin_sdk.runtime import InvocationIdentity
from magi_plugin_sdk.tools import ToolResult

from ...core.tool_context import ToolExecutionContext
from ...events.domain_payloads import TaskContext
from ...plugins.operations import OperationInvoker
from .tool_invocation_service import InvocationContext, ToolCall, ToolInvocationService


def build_plugin_operation_invoker(tool_registry: Any) -> OperationInvoker:
    """Keep effect admission, replay and tracing owned by the agent runtime."""
    async def invoke(
        name: str,
        parameters: dict[str, Any],
        identity: InvocationIdentity,
        execution: ToolExecutionContext,
    ) -> ToolResult:
        task_context = TaskContext(
            session_id=identity.session_id,
            task_id=identity.task_id,
            user_id=identity.principal_id,
            turn_id=execution.env_vars.get("turn_id"),
        )
        return await ToolInvocationService(tool_registry, require_effect_ledger=True).invoke(
            ToolCall(name, parameters),
            InvocationContext("plugin_operation", task_context, execution, trigger=identity.trigger),
        )

    return invoke
