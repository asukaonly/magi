"""
Worker manager for launching and tracking specialized worker agents.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from ...core.logger import get_logger
from ...runtime_trace import RuntimeTraceStore
from ...tools.registry import ToolRegistry, tool_registry
from .child_preset import ChildRunPreset
from .worker_actions import WorkerActionMixin
from .worker_execution import WorkerExecutionMixin
from .worker_launch import WorkerLaunchMixin
from .worker_prompting import WorkerPromptMixin
from .worker_result_validation import WorkerResultValidationMixin
from .worker_schema import WorkerSchemaMixin
from .worker_state import WorkerRunState
from .worker_status import WorkerStatusMixin
from .worker_trace import WorkerTraceMixin
from ...tools.schema import Tool

logger = get_logger(__name__)


class ChildRunCoordinator(
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
    """Manage bounded child-run lifecycle, ownership, budgets, and cancellation."""

    ACTION_LAUNCH = "launch"
    ACTION_STATUS = "status"
    ACTION_AWAIT = "await"
    ACTION_CANCEL = "cancel"

    PRESET_DEFAULT = ChildRunPreset.DEFAULT.value
    PRESET_READ_ONLY = ChildRunPreset.READ_ONLY.value
    PRESET_WORKSPACE_WRITE = ChildRunPreset.WORKSPACE_WRITE.value
    PRESET_REVIEW = ChildRunPreset.REVIEW.value

    def __init__(self) -> None:
        self._llm_adapter = None
        self._scenario_llm_pool = None
        self._active_model_provider = None
        self._tool_registry: ToolRegistry = tool_registry
        self._task_agent_manager = None
        self._message_bus = None
        self._runtime_trace_store: RuntimeTraceStore | None = None
        self._permission_gateway_provider: Callable[[], Any] | None = None
        self._background_task_manager: Any | None = None
        self._runs: Dict[str, WorkerRunState] = {}
        self._pending_runs: Dict[str, WorkerRunState] = {}
        self._cancelled_run_keys: Dict[tuple[str, str, int], float] = {}
        self._lock = asyncio.Lock()
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
        background_task_manager: Any | None = None,
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
        if background_task_manager is not None:
            self._background_task_manager = background_task_manager

    async def clear_user_content(self) -> None:
        """Cancel worker runs and discard their retained prompts and results."""
        async with self._lock:
            run_states = list(self._runs.values()) + list(self._pending_runs.values())
            self._runs.clear()
            self._pending_runs.clear()
            self._cancelled_run_keys.clear()
        for run_state in run_states:
            if run_state.cancel_token is not None:
                run_state.cancel_token.cancel("user_content_cleared")
        live_tasks = [
            run_state.task
            for run_state in run_states
            if run_state.task is not None and not run_state.task.done()
        ]
        for task in live_tasks:
            task.cancel()
        if live_tasks:
            await asyncio.gather(*live_tasks, return_exceptions=True)
        async with self._lock:
            self._runs.clear()
            self._pending_runs.clear()

    async def cancel_run_workers(
        self,
        *,
        session_id: str,
        run_id: str,
        run_revision: int,
        reason: str = "run_cancelled",
        include_transferred: bool = False,
    ) -> list[str]:
        """Request cancellation for every live worker attached to one session run."""
        run_key = (session_id, run_id, int(run_revision))
        async with self._lock:
            self._cancelled_run_keys.pop(run_key, None)
            self._cancelled_run_keys[run_key] = time.monotonic()
            while len(self._cancelled_run_keys) > 1024:
                oldest_key = next(iter(self._cancelled_run_keys))
                self._cancelled_run_keys.pop(oldest_key, None)
            public_states = [
                run_state
                for run_state in self._runs.values()
                if run_state.session_id == session_id
                and run_state.parent_run_id == run_id
                and int(run_state.run_revision) == int(run_revision)
                and run_state.status == "running"
                and (include_transferred or run_state.ownership == "parent")
            ]
            pending_states = [
                run_state
                for run_state in self._pending_runs.values()
                if run_state.session_id == session_id
                and run_state.parent_run_id == run_id
                and int(run_state.run_revision) == int(run_revision)
                and run_state.status == "running"
                and (include_transferred or run_state.ownership == "parent")
            ]
            matching_states = public_states + pending_states
            for run_state in matching_states:
                if run_state.cancel_token is not None:
                    run_state.cancel_token.cancel(reason)

        cancelled_worker_ids = [run_state.worker_id for run_state in matching_states]
        pending_tasks = [
            run_state.task
            for run_state in pending_states
            if run_state.task is not None and not run_state.task.done()
        ]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        live_tasks = [
            run_state.task
            for run_state in public_states
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
