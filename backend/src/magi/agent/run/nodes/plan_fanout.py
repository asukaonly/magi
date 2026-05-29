"""PlanFanoutNode: thin adapter wrapping OrchestrationLaunchHandler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .protocol import NodeOutcome, NodeResult

if TYPE_CHECKING:
    from ...task_agents.common.handlers import OrchestrationLaunchHandler
    from ...task_agents.common.contracts import ExecutionRequest


class PlanFanoutNode:
    """Adapter: ``OrchestrationLaunchHandler`` → ``NodeResult``."""

    node_type: str = "plan_fanout"

    __slots__ = ("_handler",)

    def __init__(self, orchestration_launch_handler: "OrchestrationLaunchHandler") -> None:
        self._handler = orchestration_launch_handler

    async def execute(self, request: "ExecutionRequest") -> NodeResult:
        try:
            execution_result = await self._handler.execute(request)
        except Exception as exc:
            return NodeResult(outcome=NodeOutcome.FAILED, error=str(exc))
        return NodeResult(outcome=NodeOutcome.DONE, execution_result=execution_result)

    def snapshot(self) -> dict[str, Any]:
        """PlanFanoutNode is stateless — no in-flight state to capture."""
        return {}

    def restore(self, state: dict[str, Any]) -> None:
        """No-op: stateless."""
        return None


__all__ = ["PlanFanoutNode"]
