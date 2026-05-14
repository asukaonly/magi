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
        result = await self._tool_invocation_service.invoke(
            _ServiceToolCall(name="agent", args={
                "action": "launch",
                "workers": worker_payloads,
                "parallel": state.allow_parallel,
                "run_in_background": True,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": parent_task_agent_id,
                "run_id": run_id,
                "run_revision": run_revision,
            }),
            InvocationContext(
                tool_category="orchestrator_internal",
                task_context=TaskContext(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    task_id=state.orchestration_id,
                    user_id=state.user_id,
                ),
                execution_context=context,
            ),
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
        self: Any,
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
        result = await self._tool_invocation_service.invoke(
            _ServiceToolCall(name="agent", args={
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
            }),
            InvocationContext(
                tool_category="orchestrator_internal",
                task_context=TaskContext(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    task_id=state.orchestration_id,
                    user_id=state.user_id,
                ),
                execution_context=context,
            ),
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
        subtask.failure_details = None
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