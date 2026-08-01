"""Worker launch and retry helpers for task orchestration."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from ..core.logger import get_logger
from ..events.domain_payloads import TaskContext
from .execution.tool_invocation_service import (
    InvocationContext,
    ToolCall as _ServiceToolCall,
)
from .orchestration import (
    RETRIABLE_WORKER_FAILURES,
    SubtaskDefinition,
    TaskOrchestrationState,
)
from .task_orchestration_transitions import mark_remaining_subtasks_cancelled

logger = get_logger(__name__)

# Worker-side LLM rate-limit retry policy. The exact ceiling is empirical:
# in practice a transient 429 burst from the upstream LLM clears within a
# handful of attempts, but we want enough budget to ride out a longer
# throttling window without aborting an in-flight orchestration. Backoff
# starts at 1s and caps at 60s — anything larger and the user perceives
# the orchestration as hung. If you change these, also revisit the
# error-classifier retry policy used by the function-calling path so the
# two stay roughly aligned.
LLM_RATE_LIMIT_RETRY_BUDGET = 10
LLM_RATE_LIMIT_BACKOFF_BASE_SECONDS = 1.0
LLM_RATE_LIMIT_BACKOFF_MAX_SECONDS = 60.0


class TaskOrchestrationWorkerMixin:
    """Launch worker agents and retry transient worker failures."""

    @property
    def _tool_invocation_service(self):
        from .execution.tool_invocation_service import get_tool_invocation_service

        if not hasattr(self, "_tool_invocation_service_cached"):
            self._tool_invocation_service_cached = get_tool_invocation_service(self._tool_registry)
        return self._tool_invocation_service_cached

    async def _launch_workers(
        self: Any,
        state: TaskOrchestrationState,
        *,
        run_id: str | None = None,
        run_revision: int = 0,
    ) -> Optional[str]:
        if await self._cancel_launch_if_needed(state):
            return None

        context = await self._build_agent_tool_context(
            state.user_id,
            state.session_id,
            state.workspace_root,
            run_id=run_id,
            run_revision=run_revision,
            user_message_generation=state.user_message_generation,
        )
        parent_task_agent_id = self._resolve_parent_task_agent_id(state.user_id, state.session_id)
        result = await self._invoke_worker_batch_launch(
            state,
            execution_context=context,
            parent_task_agent_id=parent_task_agent_id,
            run_id=run_id,
            run_revision=run_revision,
        )
        worker_ids, error = _parse_batch_worker_ids(result, len(state.subtasks))
        if error:
            return error

        _assign_launched_workers(state, worker_ids)
        await self._orchestration_store.save_orchestration(state)
        return None

    async def _cancel_launch_if_needed(
        self: Any,
        state: TaskOrchestrationState,
    ) -> bool:
        if state.status != "cancelling":
            return False
        mark_remaining_subtasks_cancelled(state)
        state.status = "cancelled"
        state.updated_at = time.time()
        await self._orchestration_store.save_orchestration(state)
        return True

    async def _invoke_worker_batch_launch(
        self: Any,
        state: TaskOrchestrationState,
        *,
        execution_context: Any,
        parent_task_agent_id: str,
        run_id: str | None,
        run_revision: int,
    ) -> Any:
        return await self._tool_invocation_service.invoke(
            _ServiceToolCall(
                name="agent",
                args=_build_batch_launch_args(
                    state,
                    parent_task_agent_type=self._parent_task_agent_type,
                    parent_task_agent_id=parent_task_agent_id,
                    run_id=run_id,
                    run_revision=run_revision,
                ),
            ),
            _build_invocation_context(state, execution_context),
        )

    async def _maybe_retry_subtask(
        self: Any,
        state: TaskOrchestrationState,
        subtask: SubtaskDefinition,
        failure_reason: str,
    ) -> bool:
        retry_budget = self._retry_budget_if_allowed(state, subtask, failure_reason)
        if retry_budget is None:
            return False

        run_id = self._extract_run_id(state)
        run_revision = self._extract_run_revision(state)
        context = await self._build_agent_tool_context(
            state.user_id,
            state.session_id,
            state.workspace_root,
            run_id=run_id,
            run_revision=run_revision,
            user_message_generation=state.user_message_generation,
        )
        parent_task_agent_id = self._resolve_parent_task_agent_id(state.user_id, state.session_id)
        next_attempt = subtask.attempt_count + 1
        await self._sleep_before_retry(
            state,
            subtask,
            failure_reason=failure_reason,
            retry_budget=retry_budget,
            next_attempt=next_attempt,
        )
        result = await self._invoke_retry_launch(
            state,
            subtask,
            execution_context=context,
            parent_task_agent_id=parent_task_agent_id,
            run_id=run_id,
            run_revision=run_revision,
            next_attempt=next_attempt,
        )
        worker_id = _parse_retry_worker_id(result, state, subtask)
        if not worker_id:
            return False

        _assign_retried_worker(state, subtask, worker_id, next_attempt)
        await self._orchestration_store.save_orchestration(state)
        return True

    def _retry_budget_if_allowed(
        self,
        state: TaskOrchestrationState,
        subtask: SubtaskDefinition,
        failure_reason: str,
    ) -> int | None:
        if state.status in {"cancelling", "cancelled"}:
            return None
        if failure_reason not in RETRIABLE_WORKER_FAILURES:
            return None
        retry_budget = self._retry_budget_for_failure(failure_reason, state.retry_budget)
        if subtask.attempt_count > retry_budget:
            return None
        return retry_budget

    async def _sleep_before_retry(
        self,
        state: TaskOrchestrationState,
        subtask: SubtaskDefinition,
        *,
        failure_reason: str,
        retry_budget: int,
        next_attempt: int,
    ) -> None:
        delay_seconds = self._retry_delay_seconds(failure_reason, subtask.attempt_count)
        if delay_seconds <= 0:
            return
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

    async def _invoke_retry_launch(
        self: Any,
        state: TaskOrchestrationState,
        subtask: SubtaskDefinition,
        *,
        execution_context: Any,
        parent_task_agent_id: str,
        run_id: str | None,
        run_revision: int,
        next_attempt: int,
    ) -> Any:
        return await self._tool_invocation_service.invoke(
            _ServiceToolCall(
                name="agent",
                args=_build_retry_launch_args(
                    state,
                    subtask,
                    parent_task_agent_type=self._parent_task_agent_type,
                    parent_task_agent_id=parent_task_agent_id,
                    run_id=run_id,
                    run_revision=run_revision,
                    next_attempt=next_attempt,
                ),
            ),
            _build_invocation_context(state, execution_context),
        )

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


def _build_batch_launch_args(
    state: TaskOrchestrationState,
    *,
    parent_task_agent_type: str,
    parent_task_agent_id: str,
    run_id: str | None,
    run_revision: int,
) -> dict[str, Any]:
    return {
        "action": "launch",
        "workers": _build_worker_payloads(
            state,
            parent_task_agent_type=parent_task_agent_type,
            parent_task_agent_id=parent_task_agent_id,
            run_id=run_id,
            run_revision=run_revision,
        ),
        "parallel": state.allow_parallel,
        "run_in_background": True,
        "target_task_agent_type": parent_task_agent_type,
        "target_task_agent_id": parent_task_agent_id,
        "run_id": run_id,
        "run_revision": run_revision,
    }


def _build_worker_payloads(
    state: TaskOrchestrationState,
    *,
    parent_task_agent_type: str,
    parent_task_agent_id: str,
    run_id: str | None,
    run_revision: int,
) -> list[dict[str, Any]]:
    return [
        {
            "subagent_type": item.subagent_type,
            "description": item.description,
            "prompt": item.prompt,
            "orchestration_id": state.orchestration_id,
            "subtask_id": item.subtask_id,
            "parent_task_agent_type": parent_task_agent_type,
            "parent_task_agent_id": parent_task_agent_id,
            "target_task_agent_type": parent_task_agent_type,
            "target_task_agent_id": parent_task_agent_id,
            "retry_count": max(item.attempt_count, 0),
            "run_id": run_id,
            "run_revision": run_revision,
            "turn_id": state.turn_id,
        }
        for item in state.subtasks
    ]


def _build_retry_launch_args(
    state: TaskOrchestrationState,
    subtask: SubtaskDefinition,
    *,
    parent_task_agent_type: str,
    parent_task_agent_id: str,
    run_id: str | None,
    run_revision: int,
    next_attempt: int,
) -> dict[str, Any]:
    return {
        "action": "launch",
        "subagent_type": subtask.subagent_type,
        "description": subtask.description,
        "prompt": subtask.prompt,
        "run_in_background": True,
        "orchestration_id": state.orchestration_id,
        "subtask_id": subtask.subtask_id,
        "parent_task_agent_type": parent_task_agent_type,
        "parent_task_agent_id": parent_task_agent_id,
        "target_task_agent_type": parent_task_agent_type,
        "target_task_agent_id": parent_task_agent_id,
        "retry_count": next_attempt - 1,
        "run_id": run_id,
        "run_revision": run_revision,
        "turn_id": state.turn_id,
    }


def _build_invocation_context(
    state: TaskOrchestrationState,
    execution_context: Any,
) -> InvocationContext:
    return InvocationContext(
        tool_category="orchestrator_internal",
        task_context=TaskContext(
            session_id=state.session_id,
            turn_id=state.turn_id,
            task_id=state.orchestration_id,
            user_id=state.user_id,
        ),
        execution_context=execution_context,
    )


def _parse_batch_worker_ids(
    result: Any,
    expected_count: int,
) -> tuple[list[Any], str | None]:
    if not result.success or not isinstance(result.data, dict):
        return [], str(result.error or "Unknown worker launch error")
    worker_ids = result.data.get("worker_ids")
    if not isinstance(worker_ids, list) or len(worker_ids) != expected_count:
        return [], "Worker launch did not return a complete worker id list"
    return worker_ids, None


def _parse_retry_worker_id(
    result: Any,
    state: TaskOrchestrationState,
    subtask: SubtaskDefinition,
) -> str | None:
    if not result.success or not isinstance(result.data, dict):
        logger.warning(
            "Failed to relaunch worker for retry | orchestration_id=%s subtask_id=%s error=%s",
            state.orchestration_id,
            subtask.subtask_id,
            result.error,
        )
        return None
    return str(result.data.get("worker_id", "")).strip() or None


def _assign_launched_workers(
    state: TaskOrchestrationState,
    worker_ids: list[Any],
) -> None:
    now = time.time()
    for subtask, worker_id in zip(state.subtasks, worker_ids):
        subtask.worker_id = str(worker_id)
        subtask.status = "running"
        subtask.attempt_count = max(subtask.attempt_count, 1)
        subtask.updated_at = now
    state.updated_at = now


def _assign_retried_worker(
    state: TaskOrchestrationState,
    subtask: SubtaskDefinition,
    worker_id: str,
    next_attempt: int,
) -> None:
    subtask.worker_id = worker_id
    subtask.status = "running"
    subtask.failure_reason = None
    subtask.failure_details = None
    subtask.worker_result = None
    subtask.attempt_count = next_attempt
    subtask.updated_at = time.time()
    state.updated_at = subtask.updated_at
