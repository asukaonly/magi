"""Shared parent-task orchestration for task agents."""
from __future__ import annotations

import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from ..core.logger import get_logger
from ..agent.runtime.contracts import FactRecord
from ..events.events import Event, EventTypes
from ..events.domain_payloads import (
    TaskCompleted,
    TaskContext,
    TaskFailed,
    TaskStarted,
    ToolError,
)
from ..tools.registry import ToolRegistry
from .orchestration import (
    OrchestrationExecutionResult,
    SubtaskDefinition,
    SubtaskPlan,
    TaskOrchestrationState,
    WorkerResult,
    get_orchestration_store,
)
from .task_orchestration_todos import TaskOrchestrationTodosMixin
from .task_orchestration_workers import TaskOrchestrationWorkerMixin
from .task_orchestration_workspace import TaskOrchestrationWorkspaceMixin
logger = get_logger(__name__)

WorkerPlanCallback = Callable[[str, list[dict[str, Any]], dict[str, Any], str, str, str | None, int], Awaitable[SubtaskPlan]]
AggregateCallback = Callable[[TaskOrchestrationState], Awaitable[str]]
HistoryCallback = Callable[[str, str], None]
SessionWorkspaceProvider = Callable[..., Awaitable[str | None] | str | None]
ControlSessionStoreProvider = Callable[[], Any]

DEFAULT_WORKER_RETRY_BUDGET = 1


class TaskOrchestrator(
    TaskOrchestrationWorkerMixin,
    TaskOrchestrationTodosMixin,
    TaskOrchestrationWorkspaceMixin,
):
    """Runtime parent-task orchestrator shared by task agents."""

    WORKER_AGENT_EVENT_TYPES = {
        "WORKER_AGENT_PROGRESS",
        "WORKER_AGENT_COMPLETED",
        "WORKER_AGENT_FAILED",
    }

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

    @property
    def _event_bus(self):
        if not hasattr(self, "_event_bus_cached"):
            try:
                from ..core.container import Container
                bus = Container.message_bus()
            except Exception:
                bus = None
            if bus is None or type(bus).__name__ == "object":
                class _NoopBus:
                    async def publish(self, event):
                        return False
                bus = _NoopBus()
            self._event_bus_cached = bus
        return self._event_bus_cached

    async def _publish_task_event(self, *, event_type: str, payload) -> None:
        try:
            ctx = getattr(payload, "context", None)
            await self._event_bus.publish(Event(
                type=event_type,
                data=payload,
                source="task_orchestrator",
                correlation_id=getattr(ctx, "turn_id", None) if ctx is not None else None,
            ))
        except Exception:
            logger.exception("publish %s failed", event_type)

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
        turn_id: Optional[str],
        history: list[dict[str, Any]],
        history_key: str,
        correlation_id: Optional[str],
        orchestration_strategy: dict[str, Any],
        persona_id: str | None = None,
    ) -> OrchestrationExecutionResult:
        workspace_root = await self._resolve_workspace_root(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )
        plan_payload = await self._plan_subtasks(
            user_message,
            history,
            orchestration_strategy,
            user_id,
            session_id,
            run_id,
            run_revision,
            workspace_root=workspace_root,
        )
        if not plan_payload.subtasks:
            return OrchestrationExecutionResult(
                response="Failed to generate worker subtasks for this request.",
                skip_emit=False,
                root_user_message=user_message,
                correlation_id=correlation_id,
                turn_id=turn_id,
            )

        orchestration_id = f"orch_{uuid.uuid4().hex[:12]}"
        now = time.time()
        subtasks = [
            SubtaskDefinition(
                subtask_id=f"subtask_{uuid.uuid4().hex[:10]}",
                description=item.description,
                subagent_type=item.subagent_type,
                prompt=item.prompt,
                parallel_group=item.parallel_group,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            for item in plan_payload.subtasks
        ]
        if not subtasks:
            return OrchestrationExecutionResult(
                response="Failed to build execution-ready worker subtasks for this request.",
                skip_emit=False,
                root_user_message=user_message,
                correlation_id=correlation_id,
                turn_id=turn_id,
            )

        state = TaskOrchestrationState(
            orchestration_id=orchestration_id,
            user_id=user_id,
            session_id=session_id,
            root_user_message=user_message,
            turn_id=turn_id,
            planner=str(orchestration_strategy.get("planner", "task_agent") or "task_agent"),
            workspace_root=workspace_root,
            status="running",
            retry_budget=DEFAULT_WORKER_RETRY_BUDGET,
            allow_parallel=bool(orchestration_strategy.get("allow_parallel", True)),
            created_at=now,
            updated_at=now,
            correlation_id=correlation_id,
            metadata={
                "run_id": run_id,
                "run_revision": run_revision,
                "persona_id": str(persona_id or "").strip() or None,
            },
            subtasks=subtasks,
        )
        await self._orchestration_store.save_orchestration(state)
        await self._publish_task_event(
            event_type=EventTypes.TASK_STARTED,
            payload=TaskStarted(
                task_id=state.orchestration_id,
                task_type=state.planner,
                started_at=state.created_at,
                context=self._build_task_context(state),
            ),
        )
        # Planner-owned todo list: publish the planned subtasks as the
        # session's todo list before any worker runs. Worker-side
        # ``todo_write`` is intentionally retired — the planner (i.e. this
        # orchestrator) is the single source of truth for todo lifecycle.
        await self._publish_session_todos(state)

        launch_error = await self._launch_workers(
            state,
            run_id=run_id,
            run_revision=run_revision,
        )
        if launch_error:
            state.status = "failed"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            await self._publish_task_event(
                event_type=EventTypes.TASK_FAILED,
                payload=TaskFailed(
                    task_id=state.orchestration_id,
                    task_type=state.planner,
                    started_at=state.created_at,
                    finished_at=state.updated_at,
                    error=ToolError(
                        type="LaunchError",
                        message=str(launch_error)[:1000],
                    ),
                    context=self._build_task_context(state),
                ),
            )
            return OrchestrationExecutionResult(
                response=f"Failed to launch worker subtasks: {launch_error}",
                skip_emit=False,
                root_user_message=user_message,
                correlation_id=state.correlation_id,
                orchestration_id=state.orchestration_id,
                turn_id=state.turn_id,
            )

        self._register_user_message(history_key, user_message)
        return OrchestrationExecutionResult(
            response="",
            skip_emit=True,
            orchestration_id=orchestration_id,
            turn_id=turn_id,
        )

    async def process_worker_updates(self, batch_facts: list[Any]) -> OrchestrationExecutionResult:
        from .task_agents.common.contracts import WorkerUpdatePayload  # avoid circular import

        touched_states: dict[str, TaskOrchestrationState] = {}
        for fact in batch_facts:
            if not isinstance(fact, FactRecord) or fact.event_type not in self.WORKER_AGENT_EVENT_TYPES:
                continue

            payload = (
                WorkerUpdatePayload.from_dict(fact.payload, fallback_user_id="")
                if isinstance(fact.payload, dict)
                else None
            )
            orchestration_id = str(payload.orchestration_id or "").strip() if payload else ""
            subtask_id = str(payload.subtask_id or "").strip() if payload else ""
            if not orchestration_id or not subtask_id:
                continue

            state = touched_states.get(orchestration_id)
            if state is None:
                state = await self._orchestration_store.get_orchestration(orchestration_id)
            if state is None or state.status in {"completed", "failed", "cancelled"}:
                continue

            subtask = state.get_subtask(subtask_id)
            if subtask is None:
                continue

            payload_worker_id = str(payload.worker_id or "").strip() if payload else ""
            if payload_worker_id and subtask.worker_id and payload_worker_id != subtask.worker_id:
                continue

            now = time.time()
            if fact.event_type == "WORKER_AGENT_PROGRESS":
                if subtask.status == "pending":
                    subtask.status = "running"
                subtask.updated_at = now
                state.updated_at = now
                touched_states[state.orchestration_id] = state
                continue

            if fact.event_type == "WORKER_AGENT_COMPLETED":
                worker_result = payload.worker_result if payload else None
                if worker_result is None and payload_worker_id:
                    worker_result = await self._orchestration_store.get_worker_result(payload_worker_id)
                if not isinstance(worker_result, WorkerResult):
                    subtask.status = "failed"
                    subtask.failure_reason = "INVALID_WORKER_RESULT"
                elif worker_result.result_status == "failed":
                    subtask.worker_result = worker_result
                    subtask.failure_reason = worker_result.failure_reason or "WORKER_REPORTED_FAILURE"
                    subtask.status = "failed"
                else:
                    subtask.worker_result = worker_result
                    subtask.failure_reason = None
                    subtask.status = "completed"
                subtask.updated_at = now
                state.updated_at = now
                touched_states[state.orchestration_id] = state
                continue

            failure_reason = str(
                (payload.failure_reason if payload else None)
                or (payload.error if payload else None)
                or "WORKER_FAILED"
            ).strip()
            retried = await self._maybe_retry_subtask(state, subtask, failure_reason)
            if not retried:
                subtask.status = "failed"
                subtask.failure_reason = failure_reason
            subtask.updated_at = now
            state.updated_at = now
            touched_states[state.orchestration_id] = state

        for state in touched_states.values():
            await self._orchestration_store.save_orchestration(state)
            await self._publish_session_todos(state)

        completed_payloads: list[OrchestrationExecutionResult] = []
        for state in touched_states.values():
            if not self._is_terminal(state):
                continue
            if state.status == "cancelling":
                self._mark_remaining_subtasks_cancelled(state)
                state.status = "cancelled"
                state.updated_at = time.time()
                await self._orchestration_store.save_orchestration(state)
                await self._publish_task_event(
                    event_type=EventTypes.TASK_FAILED,
                    payload=TaskFailed(
                        task_id=state.orchestration_id,
                        task_type=state.planner,
                        started_at=state.created_at,
                        finished_at=state.updated_at,
                        error=ToolError(
                            type="Cancelled",
                            message="Orchestration cancelled",
                        ),
                        context=self._build_task_context(state),
                    ),
                )
                continue
            if state.status == "completed":
                continue
            state.status = "aggregating"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)

            final_response = await self._aggregate_orchestration(state)
            state.final_response = final_response
            state.status = "completed" if final_response.strip() else "failed"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)

            ctx = self._build_task_context(state)
            if state.status == "completed":
                summary_text = (state.final_response or "")[:500] or None
                await self._publish_task_event(
                    event_type=EventTypes.TASK_COMPLETED,
                    payload=TaskCompleted(
                        task_id=state.orchestration_id,
                        task_type=state.planner,
                        started_at=state.created_at,
                        finished_at=state.updated_at,
                        summary=summary_text,
                        context=ctx,
                    ),
                )
            else:
                await self._publish_task_event(
                    event_type=EventTypes.TASK_FAILED,
                    payload=TaskFailed(
                        task_id=state.orchestration_id,
                        task_type=state.planner,
                        started_at=state.created_at,
                        finished_at=state.updated_at,
                        error=ToolError(
                            type="AggregationFailed",
                            message="Aggregator returned empty response",
                        ),
                        context=ctx,
                    ),
                )

            if final_response.strip():
                completed_payloads.append(
                    OrchestrationExecutionResult(
                        response=final_response,
                        skip_emit=False,
                        root_user_message=state.root_user_message,
                        correlation_id=state.correlation_id,
                        orchestration_id=state.orchestration_id,
                        message_started_at=state.created_at,
                        turn_id=state.turn_id,
                    )
                )

        if not completed_payloads:
            return OrchestrationExecutionResult(response="", skip_emit=True)
        if len(completed_payloads) == 1:
            return completed_payloads[0]

        first = completed_payloads[0]
        return OrchestrationExecutionResult(
            response="\n\n".join(
                item.response
                for item in completed_payloads
                if str(item.response).strip()
            ),
            skip_emit=False,
            root_user_message=first.root_user_message,
            correlation_id=first.correlation_id,
            orchestration_id=",".join(
                str(item.orchestration_id or "")
                for item in completed_payloads
                if item.orchestration_id
            ),
            message_started_at=first.message_started_at,
            turn_id=first.turn_id,
        )

    async def cancel_run(
        self,
        *,
        session_id: str,
        run_id: str,
        run_revision: int,
    ) -> list[str]:
        """Cancel persisted orchestrations that belong to the specified run."""
        cancelled_ids: list[str] = []
        candidate_states = await self._orchestration_store.list_orchestrations(
            session_id=session_id,
            statuses=["running", "aggregating", "cancelling"],
        )
        for state in candidate_states:
            if self._extract_run_id(state) != run_id:
                continue
            if self._extract_run_revision(state) != int(run_revision):
                continue
            self._mark_remaining_subtasks_cancelled(state)
            state.status = "cancelled"
            state.final_response = None
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            await self._publish_task_event(
                event_type=EventTypes.TASK_FAILED,
                payload=TaskFailed(
                    task_id=state.orchestration_id,
                    task_type=state.planner,
                    started_at=state.created_at,
                    finished_at=state.updated_at,
                    error=ToolError(
                        type="Cancelled",
                        message="Orchestration cancelled",
                    ),
                    context=self._build_task_context(state),
                ),
            )
            cancelled_ids.append(state.orchestration_id)
        return cancelled_ids

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

    def _mark_remaining_subtasks_cancelled(self, state: TaskOrchestrationState) -> None:
        now = time.time()
        for subtask in state.subtasks:
            if subtask.status in {"completed", "failed", "cancelled"}:
                continue
            subtask.status = "cancelled"
            subtask.updated_at = now

    def _is_terminal(self, state: TaskOrchestrationState) -> bool:
        return bool(state.subtasks) and all(
            item.status in {"completed", "failed", "cancelled"}
            for item in state.subtasks
        )
