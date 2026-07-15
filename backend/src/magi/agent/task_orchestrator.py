"""Shared parent-task orchestration for task agents."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

from .cancel import CancelToken
from magi.control.run_control import RunControl
from ..core.logger import get_logger
from ..events.domain_payloads import TaskContext, ToolError
from ..tools.registry import ToolRegistry
from .orchestration import (
    OrchestrationExecutionResult,
    SubtaskPlan,
    TaskOrchestrationState,
    get_orchestration_store,
)
from .task_orchestration_lifecycle import TaskOrchestrationLifecyclePublisher
from .task_orchestration_todos import TaskOrchestrationTodosMixin
from .task_orchestration_transitions import mark_remaining_subtasks_cancelled
from .task_orchestration_updates import TaskOrchestrationUpdateProcessor
from .task_orchestration_workers import TaskOrchestrationWorkerMixin
from .task_orchestration_workspace import TaskOrchestrationWorkspaceMixin
from .orchestration_plan import OrchestrationPlan
from .task_orchestration_start import (
    TaskOrchestrationStartRequest,
    TaskOrchestrationStarter,
)

logger = get_logger(__name__)

WorkerPlanCallback = Callable[
    [str, list[dict[str, Any]], OrchestrationPlan, str, str, str | None, int],
    Awaitable[SubtaskPlan],
]
AggregateCallback = Callable[[TaskOrchestrationState], Awaitable[str]]
HistoryCallback = Callable[[str, str], None]
SessionWorkspaceProvider = Callable[..., Awaitable[str | None] | str | None]
ControlSessionStoreProvider = Callable[[], Any]


class TaskOrchestrator(
    TaskOrchestrationWorkerMixin,
    TaskOrchestrationTodosMixin,
    TaskOrchestrationWorkspaceMixin,
):
    """Runtime parent-task orchestrator shared by task agents."""

    def __init__(
        self,
        runtime_key: str,
        tool_registry: ToolRegistry,
        plan_subtasks: WorkerPlanCallback,
        aggregate_orchestration: AggregateCallback,
        register_user_message: HistoryCallback,
        parent_task_agent_type: str = "chat",
        session_workspace_provider: SessionWorkspaceProvider | None = None,
        control_session_store_provider: ControlSessionStoreProvider | None = None,
    ) -> None:
        self._runtime_key = runtime_key
        self._tool_registry = tool_registry
        self._plan_subtasks = plan_subtasks
        self._aggregate_orchestration = aggregate_orchestration
        self._register_user_message = register_user_message
        self._parent_task_agent_type = parent_task_agent_type
        self._session_workspace_provider = session_workspace_provider
        self._control_session_store_provider = control_session_store_provider
        self._orchestration_store = get_orchestration_store()
        self._lifecycle_publisher = TaskOrchestrationLifecyclePublisher(self)
        self._starter = TaskOrchestrationStarter(self)
        self._update_processor = TaskOrchestrationUpdateProcessor(self)

    @property
    def _event_bus(self):
        if not hasattr(self, "_event_bus_cached"):
            try:
                from ..core.container import get_container

                bus = get_container().message_bus()
            except Exception:
                bus = None
            if bus is None or type(bus).__name__ == "object":

                class _NoopBus:
                    async def publish(self, event):
                        return False

                bus = _NoopBus()
            self._event_bus_cached = bus
        return self._event_bus_cached

    async def _publish_task_lifecycle(
        self,
        *,
        state,
        status: str,
        summary: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        error: Optional[ToolError] = None,
    ) -> None:
        await self._lifecycle_publisher.publish(
            state=state,
            status=status,
            summary=summary,
            error_type=error_type,
            error_message=error_message,
            error=error,
        )

    def _build_task_context(self, state: TaskOrchestrationState) -> TaskContext:
        return TaskContext(
            session_id=state.session_id,
            turn_id=state.turn_id,
            task_id=state.orchestration_id,
            user_id=state.user_id,
        )

    async def start_orchestration(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        run_id: str | None = None,
        run_revision: int = 0,
        turn_id: Optional[str] = None,
        history: list[dict[str, Any]],
        history_key: str,
        correlation_id: Optional[str] = None,
        orchestration_plan: OrchestrationPlan,
        persona_id: str | None = None,
        cancel_token: CancelToken | None = None,
        control: RunControl | None = None,
    ) -> OrchestrationExecutionResult:
        return await self._starter.start(
            TaskOrchestrationStartRequest(
                user_id=user_id,
                session_id=session_id,
                user_message=user_message,
                run_id=run_id,
                run_revision=run_revision,
                turn_id=turn_id,
                history=history,
                history_key=history_key,
                correlation_id=correlation_id,
                orchestration_plan=orchestration_plan,
                persona_id=persona_id,
                cancel_token=cancel_token,
                control=control,
            )
        )

    async def process_worker_updates(
        self,
        batch_facts: list[Any],
    ) -> OrchestrationExecutionResult:
        return await self._update_processor.process(batch_facts)

    async def cancel_run(
        self,
        *,
        session_id: str,
        run_id: str,
        run_revision: int,
        strict_worker_cancellation: bool = False,
    ) -> list[str]:
        """Cancel persisted orchestrations that belong to the specified run."""
        cancelled_ids: list[str] = []
        await self._cancel_live_workers(
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            strict=strict_worker_cancellation,
        )
        candidate_states = await self._orchestration_store.list_orchestrations(
            session_id=session_id,
            statuses=["running", "aggregating", "cancelling"],
        )
        for state in candidate_states:
            if self._extract_run_id(state) != run_id:
                continue
            if self._extract_run_revision(state) != int(run_revision):
                continue
            mark_remaining_subtasks_cancelled(state)
            state.status = "cancelled"
            state.final_response = None
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            await self._publish_task_lifecycle(
                state=state,
                status="cancelled",
                error_type="Cancelled",
                error_message="Orchestration cancelled",
            )
            cancelled_ids.append(state.orchestration_id)
        return cancelled_ids

    async def _cancel_live_workers(
        self,
        *,
        session_id: str,
        run_id: str,
        run_revision: int,
        strict: bool = False,
    ) -> list[str]:
        try:
            agent_tool = self._tool_registry.get_tool("agent")
            manager = getattr(agent_tool, "_manager", None)
            cancel_workers = getattr(manager, "cancel_run_workers", None)
            if not callable(cancel_workers):
                return []
            return await cancel_workers(
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
                reason="session_run_cancelled",
            )
        except Exception as exc:  # noqa: BLE001 - cancellation must still mark orchestration state
            logger.warning(
                "Failed to cancel live worker tasks",
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
                error=str(exc),
            )
            if strict:
                raise RuntimeError(
                    "Failed to cancel live worker tasks before destructive clear"
                ) from exc
            return []

    @staticmethod
    def _extract_run_id(state: TaskOrchestrationState) -> str | None:
        metadata = getattr(state, "metadata", None)
        if isinstance(metadata, dict):
            run_id = str(metadata.get("run_id") or "").strip()
            return run_id or None
        return None

    @staticmethod
    def _extract_run_revision(state: TaskOrchestrationState) -> int:
        metadata = getattr(state, "metadata", None)
        if not isinstance(metadata, dict):
            return 0
        try:
            return int(metadata.get("run_revision") or 0)
        except (TypeError, ValueError):
            return 0
