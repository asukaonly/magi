"""ReplyNode: thin adapter wrapping DirectLLMHandler.

Phase C scope: stateless adapter delegating to DirectLLMHandler and
wrapping the ExecutionResult in NodeResult. No business logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protocol import NodeOutcome, NodeResult

if TYPE_CHECKING:
    from ...task_agents.chat.direct_handler import DirectLLMHandler
    from ...task_agents.common.contracts import ExecutionRequest


class ReplyNode:
    """Adapter: ``DirectLLMHandler`` → ``NodeResult``."""

    node_type: str = "reply"

    __slots__ = ("_handler",)

    def __init__(self, direct_llm_handler: "DirectLLMHandler") -> None:
        self._handler = direct_llm_handler

    async def execute(self, request: "ExecutionRequest") -> NodeResult:
        try:
            execution_result = await self._handler.execute(request)
        except Exception as exc:
            return NodeResult(outcome=NodeOutcome.FAILED, error=str(exc))
        return NodeResult(outcome=NodeOutcome.DONE, execution_result=execution_result)


__all__ = ["ReplyNode"]
