"""
Worker manager for launching and tracking specialized worker agents.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from ...agent.orchestration import WorkerResult, get_orchestration_store
from ...config.models import ThinkingDepth
from ...core.logger import get_logger
from ...agent.execution.function_calling import FunctionCallingOrchestrator
from ...agent.turn_input import UserTurnInput
from ...runtime_trace import RuntimeTraceStore
from ...llm.streaming_events import stream_source
from ...tools.registry import ToolRegistry, tool_registry
from .worker_actions import WorkerActionMixin
from .worker_launch import WorkerLaunchMixin
from .worker_prompting import WorkerPromptMixin
from .worker_result_validation import WorkerResultValidationMixin
from .worker_schema import WorkerSchemaMixin
from .worker_state import (
    WORKER_AGENT_COMPLETED,
    WORKER_AGENT_FAILED,
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

    _EXPLORE_TOOL_CANDIDATES = ["glob", "grep", "file_read"]
    _PLAN_TOOL_CANDIDATES = ["glob", "grep", "file_read", "web-search"]
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
    ]

    def __init__(self) -> None:
        self._llm_adapter = None
        self._scenario_llm_pool = None
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
        if permission_gateway_provider is not None:
            self._permission_gateway_provider = permission_gateway_provider

    async def _run_worker(
        self,
        run_state: WorkerRunState,
        worker_system_prompt: str,
        selected_tools: List[str],
        max_iterations: int,
        execution_workspace: str,
    ) -> None:
        await self._publish_worker_fact(
            run_state=run_state,
            event_type=WORKER_AGENT_PROGRESS,
            internal_payload={
                "stage": "started",
                "description": run_state.description,
                "subagent_type": run_state.subagent_type,
            },
            public_payload={
                "stage": "started",
                "description": run_state.description,
                "subagent_type": run_state.subagent_type,
            },
        )

        try:
            executor = FunctionCallingOrchestrator(
                llm_adapter=self._llm_adapter,
                tool_registry=self._tool_registry,
                skill_runner=None,
                tool_result_callback=lambda payload: self._handle_tool_result(run_state, payload),
                loop_event_callback=lambda payload: self._handle_worker_loop_event(
                    run_state, payload
                ),
                runtime_trace_store=self._runtime_trace_store,
                scenario_llm_pool=self._scenario_llm_pool,
                permission_gateway_provider=self._permission_gateway_provider,
            )
            async with stream_source("worker"):
                outcome = await executor.execute_with_tools(
                    turn=UserTurnInput(
                        text=run_state.prompt,
                        attachments=[],
                        user_id=run_state.user_id,
                        session_id=run_state.session_id or run_state.worker_id,
                    ),
                    system_prompt=worker_system_prompt,
                    selected_tools=selected_tools,
                    user_id=run_state.user_id,
                    session_id=run_state.session_id or run_state.worker_id,
                    turn_id=run_state.turn_id,
                    conversation_history=[],
                    max_iterations=max_iterations,
                    thinking_depth=(
                        ThinkingDepth.HIGH
                        if run_state.subagent_type == self.TYPE_PLAN
                        else ThinkingDepth.NONE
                    ),
                    intent=(
                        "worker_explore"
                        if run_state.subagent_type == self.TYPE_EXPLORE
                        else f"worker_{run_state.subagent_type.lower()}"
                    ),
                    execution_agent_id=run_state.worker_id,
                    execution_workspace=execution_workspace,
                    llm_timeout_seconds=(
                        180.0 if run_state.subagent_type == self.TYPE_PLAN else None
                    ),
                    final_response_json_mode=True,
                    cancel_token=run_state.cancel_token,
                    ephemeral_context=run_state.parent_context_summary,
                )
            run_state.completed_at = time.time()
            run_state.updated_at = run_state.completed_at
            run_state.failure_reason = outcome.failure_reason
            validated_result: Optional[WorkerResult] = None
            if outcome.status == "cancelled":
                run_state.status = "cancelled"
                run_state.failure_reason = "CANCELLED"
                run_state.error = "Worker cancelled"
                await self._emit_worker_cancelled_trace(run_state)
                await self._publish_worker_fact(
                    run_state=run_state,
                    event_type=WORKER_AGENT_FAILED,
                    internal_payload={"stage": "cancelled", "error": run_state.error},
                    public_payload={"stage": "cancelled", "error": run_state.error},
                )
                return
            if outcome.succeeded:
                try:
                    validated_result = self._validate_worker_result(
                        subagent_type=run_state.subagent_type,
                        content=outcome.content,
                    )
                except ValueError as exc:
                    run_state.failure_reason = "INVALID_WORKER_RESULT"
                    run_state.error = str(exc)

            if outcome.succeeded and validated_result:
                run_state.result = validated_result.to_dict()
                run_state.result_preview = self._preview_worker_result(validated_result)
                await self._orchestration_store.save_worker_result(
                    worker_id=run_state.worker_id,
                    orchestration_id=run_state.orchestration_id,
                    subtask_id=run_state.subtask_id,
                    worker_result=validated_result,
                )
                if validated_result.result_status == "failed":
                    run_state.status = "failed"
                    run_state.failure_reason = str(
                        validated_result.failure_reason
                        or outcome.failure_reason
                        or "WORKER_REPORTED_FAILURE"
                    ).strip()
                    run_state.error = run_state.failure_reason
                    await self._emit_worker_failed_trace(run_state)
                    await self._publish_worker_fact(
                        run_state=run_state,
                        event_type=WORKER_AGENT_FAILED,
                        internal_payload={
                            "stage": "failed",
                            "error": run_state.error,
                            "error_text": getattr(outcome, "error_text", None),
                            "tool_failures": list(getattr(outcome, "tool_failures", []) or []),
                            "worker_result": validated_result.to_dict(),
                        },
                        public_payload={
                            "stage": "failed",
                            "error": run_state.error,
                            "result_preview": run_state.result_preview,
                        },
                    )
                    return

                run_state.status = "completed"
                await self._emit_worker_completed_trace(run_state)
                await self._publish_worker_fact(
                    run_state=run_state,
                    event_type=WORKER_AGENT_COMPLETED,
                    internal_payload={
                        "stage": "completed",
                        "worker_result": validated_result.to_dict(),
                    },
                    public_payload={
                        "stage": "completed",
                        "result_preview": run_state.result_preview,
                    },
                )
                return

            run_state.status = "failed"
            # Prefer the raw provider/exception text surfaced by the
            # function-calling orchestrator so the worker-attempt span
            # shows the real LLM error (e.g. ``EXECUTION_ERROR: Error
            # code: 400 - ...``) instead of only the classified bucket.
            run_state.error = (
                run_state.error
                or getattr(outcome, "error_text", None)
                or outcome.failure_reason
                or "Worker execution failed"
            )
            await self._emit_worker_failed_trace(run_state)
            await self._publish_worker_fact(
                run_state=run_state,
                event_type=WORKER_AGENT_FAILED,
                internal_payload={
                    "stage": "failed",
                    "error": run_state.error,
                    "error_text": getattr(outcome, "error_text", None),
                    "tool_failures": list(getattr(outcome, "tool_failures", []) or []),
                },
                public_payload={
                    "stage": "failed",
                    "error": run_state.error,
                    "result_preview": run_state.result_preview,
                },
            )
        except asyncio.CancelledError:
            run_state.status = "cancelled"
            run_state.error = "Worker cancelled"
            run_state.failure_reason = "CANCELLED"
            run_state.completed_at = time.time()
            run_state.updated_at = run_state.completed_at
            await self._emit_worker_cancelled_trace(run_state)
            await self._publish_worker_fact(
                run_state=run_state,
                event_type=WORKER_AGENT_FAILED,
                internal_payload={"stage": "cancelled", "error": run_state.error},
                public_payload={"stage": "cancelled", "error": run_state.error},
            )
        except Exception as exc:
            run_state.status = "failed"
            run_state.error = str(exc)
            run_state.completed_at = time.time()
            run_state.updated_at = run_state.completed_at
            logger.error(
                "Worker agent execution failed | worker_id=%s error=%s",
                run_state.worker_id,
                exc,
                exc_info=True,
            )
            await self._emit_worker_failed_trace(run_state)
            await self._publish_worker_fact(
                run_state=run_state,
                event_type=WORKER_AGENT_FAILED,
                internal_payload={
                    "stage": "failed",
                    "error": run_state.error,
                },
                public_payload={
                    "stage": "failed",
                    "error": run_state.error,
                },
            )

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
