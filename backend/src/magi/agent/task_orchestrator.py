"""Shared parent-task orchestration for task agents."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from ..core.logger import get_logger
from ..core.runtime.contracts import FactRecord
from ..tools.registry import ToolRegistry
from ..tools.schema import ToolExecutionContext
from .orchestration import (
    RETRIABLE_WORKER_FAILURES,
    SubtaskDefinition,
    TaskOrchestrationState,
    get_orchestration_store,
)

logger = get_logger(__name__)

WorkerPlanCallback = Callable[[str, list[dict[str, Any]], dict[str, Any], str, str], Awaitable[dict[str, Any]]]
AggregateCallback = Callable[[TaskOrchestrationState], Awaitable[str]]
HistoryCallback = Callable[[str, str], None]


class TaskOrchestrator:
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
    ) -> None:
        self._runtime_key = runtime_key
        self._tool_registry = tool_registry
        self._plan_subtasks = plan_subtasks
        self._aggregate_orchestration = aggregate_orchestration
        self._register_user_message = register_user_message
        self._parent_task_agent_type = parent_task_agent_type
        self._orchestration_store = get_orchestration_store()

    async def start_orchestration(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        history_key: str,
        correlation_id: Optional[str],
        orchestration_strategy: dict[str, Any],
    ) -> dict[str, Any]:
        plan_payload = await self._plan_subtasks(
            user_message,
            history,
            orchestration_strategy,
            user_id,
            session_id,
        )
        raw_subtasks = plan_payload.get("subtasks") if isinstance(plan_payload, dict) else []
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            return {
                "response": "Failed to generate worker subtasks for this request.",
                "skip_emit": False,
                "root_user_message": user_message,
                "correlation_id": correlation_id,
            }

        orchestration_id = f"orch_{uuid.uuid4().hex[:12]}"
        now = time.time()
        subtasks = [
            SubtaskDefinition(
                subtask_id=f"subtask_{uuid.uuid4().hex[:10]}",
                description=str(item.get("description", "")).strip(),
                subagent_type=str(item.get("subagent_type", "Explore")).strip() or "Explore",
                prompt=str(item.get("prompt", "")).strip(),
                parallel_group=str(item.get("parallel_group", "default")).strip() or "default",
                status="pending",
                created_at=now,
                updated_at=now,
            )
            for item in raw_subtasks
            if isinstance(item, dict)
            and str(item.get("description", "")).strip()
            and str(item.get("prompt", "")).strip()
        ]
        if not subtasks:
            return {
                "response": "Failed to build execution-ready worker subtasks for this request.",
                "skip_emit": False,
                "root_user_message": user_message,
                "correlation_id": correlation_id,
            }

        state = TaskOrchestrationState(
            orchestration_id=orchestration_id,
            user_id=user_id,
            session_id=session_id,
            root_user_message=user_message,
            planner=str(orchestration_strategy.get("planner", "task_agent") or "task_agent"),
            status="running",
            retry_budget=1,
            allow_parallel=bool(orchestration_strategy.get("allow_parallel", True)),
            created_at=now,
            updated_at=now,
            correlation_id=correlation_id,
            subtasks=subtasks,
        )
        await self._orchestration_store.save_orchestration(state)

        launch_error = await self._launch_workers(state)
        if launch_error:
            state.status = "failed"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            return {
                "response": f"Failed to launch worker subtasks: {launch_error}",
                "skip_emit": False,
                "root_user_message": user_message,
                "correlation_id": state.correlation_id,
                "orchestration_id": state.orchestration_id,
            }

        self._register_user_message(history_key, user_message)
        return {
            "response": "",
            "skip_emit": True,
            "orchestration_id": orchestration_id,
        }

    async def process_worker_updates(self, batch_facts: list[Any]) -> dict[str, Any]:
        touched_states: dict[str, TaskOrchestrationState] = {}
        for fact in batch_facts:
            if not isinstance(fact, FactRecord) or fact.event_type not in self.WORKER_AGENT_EVENT_TYPES:
                continue
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            orchestration_id = str(payload.get("orchestration_id", "")).strip()
            subtask_id = str(payload.get("subtask_id", "")).strip()
            if not orchestration_id or not subtask_id:
                continue

            state = touched_states.get(orchestration_id)
            if state is None:
                state = await self._orchestration_store.get_orchestration(orchestration_id)
            if state is None or state.status in {"completed", "failed"}:
                continue

            subtask = state.get_subtask(subtask_id)
            if subtask is None:
                continue

            payload_worker_id = str(payload.get("worker_id", "")).strip()
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
                worker_result = payload.get("worker_result")
                if not isinstance(worker_result, dict) and payload_worker_id:
                    worker_result = await self._orchestration_store.get_worker_result(payload_worker_id)
                if not isinstance(worker_result, dict):
                    subtask.status = "failed"
                    subtask.failure_reason = "INVALID_WORKER_RESULT"
                elif str(worker_result.get("result_status", "success")).strip() == "failed":
                    subtask.worker_result = worker_result
                    subtask.failure_reason = str(
                        worker_result.get("failure_reason") or "WORKER_REPORTED_FAILURE"
                    ).strip()
                    subtask.status = "failed"
                else:
                    subtask.worker_result = worker_result
                    subtask.failure_reason = None
                    subtask.status = "completed"
                subtask.updated_at = now
                state.updated_at = now
                touched_states[state.orchestration_id] = state
                continue

            failure_reason = str(payload.get("failure_reason") or payload.get("error") or "WORKER_FAILED").strip()
            retried = await self._maybe_retry_subtask(state, subtask, failure_reason)
            if not retried:
                subtask.status = "failed"
                subtask.failure_reason = failure_reason
            subtask.updated_at = now
            state.updated_at = now
            touched_states[state.orchestration_id] = state

        for state in touched_states.values():
            await self._orchestration_store.save_orchestration(state)

        completed_payloads: list[dict[str, Any]] = []
        for state in touched_states.values():
            if not self._is_terminal(state):
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
                    {
                        "response": final_response,
                        "skip_emit": False,
                        "root_user_message": state.root_user_message,
                        "correlation_id": state.correlation_id,
                        "orchestration_id": state.orchestration_id,
                        "message_started_at": state.created_at,
                    }
                )

        if not completed_payloads:
            return {"response": "", "skip_emit": True}
        if len(completed_payloads) == 1:
            return completed_payloads[0]

        first = completed_payloads[0]
        return {
            "response": "\n\n".join(
                item["response"]
                for item in completed_payloads
                if str(item.get("response", "")).strip()
            ),
            "skip_emit": False,
            "root_user_message": first.get("root_user_message"),
            "correlation_id": first.get("correlation_id"),
            "orchestration_id": ",".join(
                str(item.get("orchestration_id", ""))
                for item in completed_payloads
                if item.get("orchestration_id")
            ),
            "message_started_at": first.get("message_started_at"),
        }

    async def _launch_workers(self, state: TaskOrchestrationState) -> Optional[str]:
        context = self._build_agent_tool_context(state.user_id, state.session_id)
        worker_payloads = [
            {
                "subagent_type": item.subagent_type,
                "description": item.description,
                "prompt": item.prompt,
                "orchestration_id": state.orchestration_id,
                "subtask_id": item.subtask_id,
                "parent_task_agent_type": self._parent_task_agent_type,
                "parent_task_agent_id": state.user_id,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": state.user_id,
                "retry_count": max(item.attempt_count, 0),
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
                "target_task_agent_id": state.user_id,
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
        if failure_reason not in RETRIABLE_WORKER_FAILURES:
            return False
        if subtask.attempt_count > state.retry_budget:
            return False

        context = self._build_agent_tool_context(state.user_id, state.session_id)
        next_attempt = subtask.attempt_count + 1
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
                "parent_task_agent_id": state.user_id,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": state.user_id,
                "retry_count": next_attempt - 1,
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

    def _build_agent_tool_context(self, user_id: str, session_id: str) -> ToolExecutionContext:
        return ToolExecutionContext(
            agent_id=self._runtime_key,
            workspace=os.getcwd(),
            env_vars={
                "user_id": user_id,
                "session_id": session_id,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": user_id,
                "parent_task_agent_type": self._parent_task_agent_type,
                "parent_task_agent_id": user_id,
            },
            permissions=["authenticated"],
        )

    def _is_terminal(self, state: TaskOrchestrationState) -> bool:
        return bool(state.subtasks) and all(item.status in {"completed", "failed"} for item in state.subtasks)
