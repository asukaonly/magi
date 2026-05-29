"""ToolLoopNode: thin adapter wrapping FunctionCallingHandler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .protocol import NodeOutcome, NodeResult

if TYPE_CHECKING:
    from ...task_agents.chat.handlers import FunctionCallingHandler
    from ...task_agents.common.contracts import ExecutionRequest


class ToolLoopNode:
    """Adapter: ``FunctionCallingHandler`` → ``NodeResult``."""

    node_type: str = "tool_loop"

    __slots__ = ("_handler", "_snapshot")

    def __init__(self, function_calling_handler: "FunctionCallingHandler") -> None:
        self._handler = function_calling_handler
        self._snapshot: dict[str, Any] = {}

    async def execute(self, request: "ExecutionRequest") -> NodeResult:
        try:
            execution_result = await self._handler.execute(request)
        except Exception as exc:
            return NodeResult(outcome=NodeOutcome.FAILED, error=str(exc))
        # Phase E: capture in-flight snapshot from the FC execution_outcome
        # if the loop detached / suspended / retracted with a snapshot.
        from ...task_agents.common.contracts import FunctionCallingExecutionResult
        if isinstance(execution_result, FunctionCallingExecutionResult):
            outcome_dict = execution_result.execution_outcome or {}
            inner_snap = outcome_dict.get("snapshot")
            if isinstance(inner_snap, dict):
                self._snapshot = dict(inner_snap)
        return NodeResult(outcome=NodeOutcome.DONE, execution_result=execution_result)

    def snapshot(self) -> dict[str, Any]:
        """Return the OrchestratorSnapshot-shaped dict captured from the
        most recent execute() call (or an empty dict if the FC loop ran
        to completion / never ran)."""
        return dict(self._snapshot)

    def restore(self, state: dict[str, Any]) -> None:
        """Store the snapshot dict; a subsequent execute() implementation
        in Phase F+ may consume it to seed the FC loop's initial_messages.

        Phase E scope: round-trip is verified; actual FC-loop reseed is
        deferred to Phase F when BackgroundTaskSpec.initial_run_snapshot
        is fully wired through the dispatcher."""
        self._snapshot = dict(state or {})


__all__ = ["ToolLoopNode"]
