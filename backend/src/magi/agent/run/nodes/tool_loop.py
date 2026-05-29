"""ToolLoopNode: thin adapter wrapping FunctionCallingHandler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protocol import NodeOutcome, NodeResult

if TYPE_CHECKING:
    from ...task_agents.chat.handlers import FunctionCallingHandler
    from ...task_agents.common.contracts import ExecutionRequest


class ToolLoopNode:
    """Adapter: ``FunctionCallingHandler`` → ``NodeResult``."""

    node_type: str = "tool_loop"

    __slots__ = ("_handler",)

    def __init__(self, function_calling_handler: "FunctionCallingHandler") -> None:
        self._handler = function_calling_handler

    async def execute(self, request: "ExecutionRequest") -> NodeResult:
        try:
            execution_result = await self._handler.execute(request)
        except Exception as exc:
            return NodeResult(outcome=NodeOutcome.FAILED, error=str(exc))
        return NodeResult(outcome=NodeOutcome.DONE, execution_result=execution_result)


__all__ = ["ToolLoopNode"]
