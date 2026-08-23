"""Task-agent execution engine for graph-backed turns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..execution.task_budget import task_execution_budget_scope
from ..task_agents.common.contracts import ExecutionMode, ExecutionRequest, ExecutionResult
from .builder import GraphBuilder
from .nodes.plan_fanout import PlanFanoutNode
from .nodes.reply import ReplyNode
from .nodes.tool_loop import ToolLoopNode
from .nodes.validate import ValidateNode
from .registry import NodeRegistry
from .runner import NodeSequenceRunner
from .snapshot import RunSnapshot


class RunSnapshotStore(Protocol):
    """Storage seam for per-run graph execution snapshots."""

    def get_run_snapshot(self, session_id: str, run_id: str) -> RunSnapshot | None:
        """Return a previously saved run snapshot, if one exists."""

    def save_run_snapshot(
        self,
        session_id: str,
        run_id: str,
        snapshot: RunSnapshot,
    ) -> None:
        """Persist the latest run snapshot."""

    def clear_run_snapshot(self, session_id: str, run_id: str) -> None:
        """Clear a completed or stale run snapshot."""


@dataclass(slots=True)
class TaskAgentExecutionOutcome:
    """Result plus route metadata returned by the execution engine."""

    result: ExecutionResult | None
    used_graph: bool = False


class TaskAgentExecutionEngine:
    """Own graph construction, node dispatch, and snapshot persistence."""

    def __init__(
        self,
        *,
        handler_registry: Any,
        tool_registry: Any | None = None,
        snapshot_store: RunSnapshotStore | None = None,
    ) -> None:
        self._handler_registry = handler_registry
        self._snapshot_store = snapshot_store
        self._node_registry = NodeRegistry()
        self._register_node_adapters(tool_registry=tool_registry)
        self._graph_builder = GraphBuilder()
        self._node_sequence_runner = NodeSequenceRunner(
            node_registry=self._node_registry,
        )

    async def execute(self, request: ExecutionRequest) -> TaskAgentExecutionOutcome:
        """Execute one prepared task-agent request."""
        async with task_execution_budget_scope():
            route_decision = getattr(request.intent, "route_decision", None)
            if route_decision is not None:
                node_specs = self._graph_builder.build_node_sequence(route_decision)
                session_id = getattr(getattr(request, "context", None), "session_id", "") or ""
                session_run_id = (
                    getattr(getattr(request, "context", None), "session_run_id", "") or ""
                )
                resume_from = self._resolve_resume_snapshot(
                    session_id=session_id,
                    session_run_id=session_run_id,
                    node_count=len(node_specs),
                )

                runner_result, snapshot = await self._node_sequence_runner.run_with_snapshot(
                    run_id=session_run_id or "",
                    node_specs=node_specs,
                    request=request,
                    resume_from=resume_from,
                )
                self._save_snapshot(
                    session_id=session_id,
                    session_run_id=session_run_id,
                    snapshot=snapshot,
                )
                if runner_result is not None:
                    return TaskAgentExecutionOutcome(result=runner_result, used_graph=True)

            handler = self._handler_registry.get(request.mode)
            return TaskAgentExecutionOutcome(
                result=await handler.execute(request),
                used_graph=False,
            )

    def _register_node_adapters(self, *, tool_registry: Any | None) -> None:
        direct_llm = self._get_handler_or_none(ExecutionMode.DIRECT_LLM)
        function_calling = self._get_handler_or_none(ExecutionMode.FUNCTION_CALLING)
        orchestration_launch = self._get_handler_or_none(ExecutionMode.ORCHESTRATION_LAUNCH)
        if direct_llm is not None:
            self._node_registry.register(ReplyNode(direct_llm_handler=direct_llm))
        if function_calling is not None:
            self._node_registry.register(ToolLoopNode(function_calling_handler=function_calling))
        if orchestration_launch is not None:
            self._node_registry.register(
                PlanFanoutNode(orchestration_launch_handler=orchestration_launch)
            )
        self._node_registry.register(ValidateNode(tool_registry=tool_registry))

    def _get_handler_or_none(self, mode: ExecutionMode) -> Any | None:
        try:
            return self._handler_registry.get(mode)
        except KeyError:
            return None

    def _resolve_resume_snapshot(
        self,
        *,
        session_id: str,
        session_run_id: str,
        node_count: int,
    ) -> RunSnapshot | None:
        if not session_id or not session_run_id or self._snapshot_store is None:
            return None
        stored_snapshot = self._snapshot_store.get_run_snapshot(
            session_id,
            session_run_id,
        )
        if stored_snapshot is None:
            return None
        if stored_snapshot.cursor < node_count:
            return stored_snapshot
        self._snapshot_store.clear_run_snapshot(session_id, session_run_id)
        return None

    def _save_snapshot(
        self,
        *,
        session_id: str,
        session_run_id: str,
        snapshot: RunSnapshot,
    ) -> None:
        if session_id and session_run_id and self._snapshot_store is not None:
            self._snapshot_store.save_run_snapshot(session_id, session_run_id, snapshot)


__all__ = [
    "RunSnapshotStore",
    "TaskAgentExecutionEngine",
    "TaskAgentExecutionOutcome",
]
