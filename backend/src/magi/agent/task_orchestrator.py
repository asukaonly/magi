"""Shared parent-task orchestration for task agents."""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from ..core.logger import get_logger
from ..agent.runtime.contracts import FactRecord
from ..tools.registry import ToolRegistry
from .orchestration import (
    OrchestrationExecutionResult,
    RETRIABLE_WORKER_FAILURES,
    SubtaskDefinition,
    SubtaskPlan,
    TaskOrchestrationState,
    WorkerResult,
    get_orchestration_store,
)
from .task_orchestration_workspace import TaskOrchestrationWorkspaceMixin
logger = get_logger(__name__)

WorkerPlanCallback = Callable[[str, list[dict[str, Any]], dict[str, Any], str, str, str | None, int], Awaitable[SubtaskPlan]]
AggregateCallback = Callable[[TaskOrchestrationState], Awaitable[str]]
HistoryCallback = Callable[[str, str], None]
SessionWorkspaceProvider = Callable[..., Awaitable[str | None] | str | None]
ControlSessionStoreProvider = Callable[[], Any]

DEFAULT_WORKER_RETRY_BUDGET = 1
LLM_RATE_LIMIT_RETRY_BUDGET = 10
LLM_RATE_LIMIT_BACKOFF_BASE_SECONDS = 1.0
LLM_RATE_LIMIT_BACKOFF_MAX_SECONDS = 60.0


class TaskOrchestrator(TaskOrchestrationWorkspaceMixin):
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
            },
            subtasks=subtasks,
        )
        await self._orchestration_store.save_orchestration(state)
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
            cancelled_ids.append(state.orchestration_id)
        return cancelled_ids

    async def _launch_workers(
        self,
        state: TaskOrchestrationState,
        *,
        run_id: str | None = None,
        run_revision: int = 0,
    ) -> Optional[str]:
        if state.status == "cancelling":
            self._mark_remaining_subtasks_cancelled(state)
            state.status = "cancelled"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            return None

        context = await self._build_agent_tool_context(
            state.user_id,
            state.session_id,
            state.workspace_root,
            run_id=run_id,
            run_revision=run_revision,
        )
        parent_task_agent_id = self._resolve_parent_task_agent_id(state.user_id, state.session_id)
        worker_payloads = [
            {
                "subagent_type": item.subagent_type,
                "description": item.description,
                "prompt": item.prompt,
                "orchestration_id": state.orchestration_id,
                "subtask_id": item.subtask_id,
                "parent_task_agent_type": self._parent_task_agent_type,
                "parent_task_agent_id": parent_task_agent_id,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": parent_task_agent_id,
                "retry_count": max(item.attempt_count, 0),
                "run_id": run_id,
                "run_revision": run_revision,
                "turn_id": state.turn_id,
            }
            for item in state.subtasks
        ]
        result = await self._tool_registry.execute(
            "agent",
            {
                "action": "launch",
                "workers": worker_payloads,
                "parallel": state.allow_parallel,
                "run_in_background": True,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": parent_task_agent_id,
                "run_id": run_id,
                "run_revision": run_revision,
            },
            context,
        )
        if not result.success or not isinstance(result.data, dict):
            return str(result.error or "Unknown worker launch error")
        worker_ids = result.data.get("worker_ids")
        if not isinstance(worker_ids, list) or len(worker_ids) != len(state.subtasks):
            return "Worker launch did not return a complete worker id list"

        now = time.time()
        for subtask, worker_id in zip(state.subtasks, worker_ids):
            subtask.worker_id = str(worker_id)
            subtask.status = "running"
            subtask.attempt_count = max(subtask.attempt_count, 1)
            subtask.updated_at = now
        state.updated_at = now
        await self._orchestration_store.save_orchestration(state)
        return None

    async def _maybe_retry_subtask(
        self,
        state: TaskOrchestrationState,
        subtask: SubtaskDefinition,
        failure_reason: str,
    ) -> bool:
        if state.status in {"cancelling", "cancelled"}:
            return False
        if failure_reason not in RETRIABLE_WORKER_FAILURES:
            return False
        retry_budget = self._retry_budget_for_failure(failure_reason, state.retry_budget)
        if subtask.attempt_count > retry_budget:
            return False

        run_id = self._extract_run_id(state)
        run_revision = self._extract_run_revision(state)
        context = await self._build_agent_tool_context(
            state.user_id,
            state.session_id,
            state.workspace_root,
            run_id=run_id,
            run_revision=run_revision,
        )
        parent_task_agent_id = self._resolve_parent_task_agent_id(state.user_id, state.session_id)
        next_attempt = subtask.attempt_count + 1
        delay_seconds = self._retry_delay_seconds(failure_reason, subtask.attempt_count)
        if delay_seconds > 0:
            logger.info(
                "Retrying worker after backoff | orchestration_id=%s subtask_id=%s reason=%s retry=%s/%s delay=%.1fs",
                state.orchestration_id,
                subtask.subtask_id,
                failure_reason,
                next_attempt - 1,
                retry_budget,
                delay_seconds,
            )
            await asyncio.sleep(delay_seconds)
        result = await self._tool_registry.execute(
            "agent",
            {
                "action": "launch",
                "subagent_type": subtask.subagent_type,
                "description": subtask.description,
                "prompt": subtask.prompt,
                "run_in_background": True,
                "orchestration_id": state.orchestration_id,
                "subtask_id": subtask.subtask_id,
                "parent_task_agent_type": self._parent_task_agent_type,
                "parent_task_agent_id": parent_task_agent_id,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": parent_task_agent_id,
                "retry_count": next_attempt - 1,
                "run_id": run_id,
                "run_revision": run_revision,
                "turn_id": state.turn_id,
            },
            context,
        )
        if not result.success or not isinstance(result.data, dict):
            logger.warning(
                "Failed to relaunch worker for retry | orchestration_id=%s subtask_id=%s error=%s",
                state.orchestration_id,
                subtask.subtask_id,
                result.error,
            )
            return False

        worker_id = str(result.data.get("worker_id", "")).strip()
        if not worker_id:
            return False

        subtask.worker_id = worker_id
        subtask.status = "running"
        subtask.failure_reason = None
        subtask.worker_result = None
        subtask.attempt_count = next_attempt
        subtask.updated_at = time.time()
        state.updated_at = subtask.updated_at
        await self._orchestration_store.save_orchestration(state)
        return True

    def _retry_budget_for_failure(self, failure_reason: str, default_budget: int) -> int:
        if failure_reason == "LLM_RATE_LIMIT":
            return max(default_budget, LLM_RATE_LIMIT_RETRY_BUDGET)
        return max(default_budget, 0)

    def _retry_delay_seconds(self, failure_reason: str, attempt_count: int) -> float:
        if failure_reason != "LLM_RATE_LIMIT":
            return 0.0
        retry_index = max(attempt_count, 1)
        delay_seconds = LLM_RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** (retry_index - 1))
        return min(delay_seconds, LLM_RATE_LIMIT_BACKOFF_MAX_SECONDS)

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

    # ------------------------------------------------------------------
    # Planner-owned session todo list
    # ------------------------------------------------------------------

    # Map orchestration subtask statuses onto control-plane TodoStatus
    # values. ``cancelled`` collapses to ``not_started`` so the UI does
    # not display a ghost "in progress" todo after a cancellation.
    _SUBTASK_TO_TODO_STATUS = {
        "pending": "not_started",
        "running": "in_progress",
        "completed": "completed",
        "failed": "completed",
        "cancelled": "not_started",
    }

    async def _publish_session_todos(self, state: TaskOrchestrationState) -> None:
        """Mirror orchestration subtasks onto the session's todo list.

        The control-plane ``ControlSessionStore`` caps ``in_progress`` to
        one item. We honour that by keeping only the first running
        subtask as ``in_progress`` and demoting the rest to
        ``not_started`` for display purposes — their real status remains
        tracked on ``state.subtasks``.
        """
        session_id = str(getattr(state, "session_id", "") or "").strip()
        if not session_id or not state.subtasks:
            return
        if self._control_session_store_provider is None:
            return
        try:
            store = self._control_session_store_provider()
        except Exception:
            # Control plane not wired (e.g. unit tests) — todo mirror is
            # purely a UX concern, never block orchestration on it.
            return

        items: list[dict[str, Any]] = []
        running_seen = False
        for subtask in state.subtasks:
            mapped = self._SUBTASK_TO_TODO_STATUS.get(subtask.status, "not_started")
            if mapped == "in_progress":
                if running_seen:
                    mapped = "not_started"
                else:
                    running_seen = True
            title = (subtask.description or "").strip() or subtask.subtask_id
            items.append(
                {
                    "id": subtask.subtask_id,
                    "content": title,
                    "status": mapped,
                }
            )

        try:
            await store.replace_todos(session_id, items)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "planner_todos.replace_failed",
                session_id=session_id,
                orchestration_id=state.orchestration_id,
                error=str(exc),
            )
            return

        try:
            from .control.chat_state_persister import persist_todo_state_message

            await persist_todo_state_message(
                session_id=session_id,
                user_id=state.user_id,
                turn_id=state.turn_id,
                items=items,
                orchestration_id=state.orchestration_id,
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("planner_todos.persist_failed", exc_info=True)

        try:
            from .control.common.events import publish_control_event

            await publish_control_event(
                "control.todo.updated",
                {
                    "session_id": session_id,
                    "orchestration_id": state.orchestration_id,
                    "items": items,
                },
                session_id=session_id,
                user_id=state.user_id,
                turn_id=state.turn_id,
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("planner_todos.event_failed", exc_info=True)
