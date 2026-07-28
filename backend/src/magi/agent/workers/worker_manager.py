"""
Worker manager for launching and tracking specialized worker agents.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from ...agent.orchestration import get_orchestration_store
from ...core.logger import get_logger
from ...runtime_trace import RuntimeTraceStore
from ...tools.registry import ToolRegistry, tool_registry
from .worker_actions import WorkerActionMixin
from .worker_execution import WorkerExecutionMixin
from .worker_launch import WorkerLaunchMixin
from .worker_prompting import WorkerPromptMixin
from .worker_result_validation import WorkerResultValidationMixin
from .worker_schema import WorkerSchemaMixin
from .worker_state import (
    WORKER_AGENT_COMPLETED as WORKER_AGENT_COMPLETED,
    WORKER_AGENT_FAILED as WORKER_AGENT_FAILED,
    WORKER_AGENT_PROGRESS,
    WorkerRunState,
)
from .worker_status import WorkerStatusMixin
from .worker_trace import WorkerTraceMixin
from ...tools.schema import Tool

logger = get_logger(__name__)


class WorkerAgentManager(
    WorkerActionMixin,
    WorkerLaunchMixin,
    WorkerExecutionMixin,
    WorkerTraceMixin,
    WorkerResultValidationMixin,
    WorkerPromptMixin,
    WorkerStatusMixin,
    WorkerSchemaMixin,
    Tool,
):
    """Manage worker-agent launch/status/await lifecycle for orchestration layers."""

    ACTION_LAUNCH = "launch"
    ACTION_STATUS = "status"
    ACTION_AWAIT = "await"

    TYPE_GENERAL = "general-purpose"
    TYPE_EXPLORE = "CodeExplore"
    TYPE_PLAN = "Plan"
    TYPE_CODING = "Coding"

    _WORKER_TYPE_MAP = {
        "general-purpose": TYPE_GENERAL,
        "general_purpose": TYPE_GENERAL,
        "general": TYPE_GENERAL,
        "code-explore": TYPE_EXPLORE,
        "code_explore": TYPE_EXPLORE,
        "CodeExplore": TYPE_EXPLORE,
        "plan": TYPE_PLAN,
        "Plan": TYPE_PLAN,
        "coding": TYPE_CODING,
        "Coding": TYPE_CODING,
        "code": TYPE_CODING,
    }

    _EXPLORE_TOOL_CANDIDATES = ["glob", "grep", "file_read", "find-relevant-tools"]
    _PLAN_TOOL_CANDIDATES = [
        "glob",
        "grep",
        "file_read",
        "web-search",
        "find-relevant-tools",
    ]
    _CODING_TOOL_CANDIDATES = [
        "file_read",
        "file_edit",
        "file_write",
        "file_rollback",
        "file_diff",
        "verify",
        "glob",
        "grep",
        "file_list",
        "file_info",
        "bash",
        "find-relevant-tools",
    ]

    def __init__(self) -> None:
        self._llm_adapter = None
        self._scenario_llm_pool = None
        self._active_model_provider = None
        self._tool_registry: ToolRegistry = tool_registry
        self._task_agent_manager = None
        self._message_bus = None
        self._runtime_trace_store: RuntimeTraceStore | None = None
        self._permission_gateway_provider: Callable[[], Any] | None = None
        self._runs: Dict[str, WorkerRunState] = {}
        self._lock = asyncio.Lock()
        self._orchestration_store = get_orchestration_store()
        super().__init__()

    def configure(
        self,
        llm_adapter,
        tool_registry_instance: Optional[ToolRegistry] = None,
        task_agent_manager=None,
        message_bus=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        scenario_llm_pool=None,
        active_model_provider=None,
        permission_gateway_provider: Callable[[], Any] | None = None,
    ) -> None:
        """Inject runtime dependencies after bootstrap."""
        self._llm_adapter = llm_adapter
        if tool_registry_instance is not None:
            self._tool_registry = tool_registry_instance
        if task_agent_manager is not None:
            self._task_agent_manager = task_agent_manager
        if message_bus is not None:
            self._message_bus = message_bus
        if runtime_trace_store is not None:
            self._runtime_trace_store = runtime_trace_store
        if scenario_llm_pool is not None:
            self._scenario_llm_pool = scenario_llm_pool
        if active_model_provider is not None:
            self._active_model_provider = active_model_provider
        if permission_gateway_provider is not None:
            self._permission_gateway_provider = permission_gateway_provider

    async def cancel_run_workers(
        self,
        *,
        session_id: str,
        run_id: str,
        run_revision: int,
        reason: str = "run_cancelled",
    ) -> list[str]:
        """Request cancellation for every live worker attached to one session run."""
        async with self._lock:
            matching_states = [
                run_state
                for run_state in self._runs.values()
                if run_state.session_id == session_id
                and run_state.run_id == run_id
                and int(run_state.run_revision) == int(run_revision)
                and run_state.status == "running"
            ]

        cancelled_worker_ids: list[str] = []
        for run_state in matching_states:
            if run_state.cancel_token is not None:
                run_state.cancel_token.cancel(reason)
            cancelled_worker_ids.append(run_state.worker_id)
        live_tasks = [
            run_state.task
            for run_state in matching_states
            if run_state.task is not None and not run_state.task.done()
        ]
        if live_tasks:
            _, pending = await asyncio.wait(live_tasks, timeout=2.0)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        return cancelled_worker_ids

    async def _handle_tool_result(self, run_state: WorkerRunState, payload: Dict[str, Any]) -> None:
        result_preview = self._compact_value(payload.get("data"))
        await self._emit_worker_tool_trace(
            run_state=run_state,
            payload=payload,
            result_preview=result_preview,
        )
        await self._publish_worker_fact(
            run_state=run_state,
            event_type=WORKER_AGENT_PROGRESS,
            internal_payload={
                "stage": "tool_result",
                "tool_name": payload.get("tool_name"),
                "success": bool(payload.get("success")),
                "execution_time": float(payload.get("execution_time") or 0.0),
                "error": payload.get("error"),
            },
            public_payload={
                "stage": "tool_result",
                "tool_name": payload.get("tool_name"),
                "success": bool(payload.get("success")),
                "execution_time": float(payload.get("execution_time") or 0.0),
                "error": payload.get("error"),
                "result_preview": result_preview,
            },
        )
