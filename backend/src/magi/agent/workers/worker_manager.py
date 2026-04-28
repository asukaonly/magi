"""
Worker manager for launching and tracking specialized worker agents.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from ...agent.orchestration import WorkerResult, get_orchestration_store
from ...config.models import ThinkingDepth
from ...core.logger import get_logger
from ...agent.execution.function_calling import FunctionCallingOrchestrator
from ...runtime_trace import RuntimeTraceStore
from ...llm.streaming_events import stream_source
from ...tools.registry import ToolRegistry, tool_registry
from .worker_actions import WorkerActionMixin
from .worker_prompting import WorkerPromptMixin
from .worker_result_validation import WorkerResultValidationMixin
from .worker_schema import WorkerSchemaMixin
from .worker_state import (
    DEFAULT_WORKER_MAX_ITERATIONS,
    WORKER_AGENT_COMPLETED,
    WORKER_AGENT_FAILED,
    WORKER_AGENT_PROGRESS,
    WorkerRunState,
    optional_string,
)
from .worker_status import WorkerStatusMixin
from .worker_trace import WorkerTraceMixin
from ...tools.schema import (
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
)

logger = get_logger(__name__)


class WorkerAgentManager(
    WorkerActionMixin,
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
    TYPE_EXPLORE = "Explore"
    TYPE_PLAN = "Plan"

    _WORKER_TYPE_MAP = {
        "general-purpose": TYPE_GENERAL,
        "general_purpose": TYPE_GENERAL,
        "general": TYPE_GENERAL,
        "explore": TYPE_EXPLORE,
        "Explore": TYPE_EXPLORE,
        "plan": TYPE_PLAN,
        "Plan": TYPE_PLAN,
    }

    _EXPLORE_TOOL_CANDIDATES = ["glob", "grep", "file_read"]
    _PLAN_TOOL_CANDIDATES = ["glob", "grep", "file_read", "web-search"]

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

    async def _launch_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        run_in_background = bool(parameters.get("run_in_background", False))
        run_state = await self._start_worker(parameters, context)
        if isinstance(run_state, ToolResult):
            return run_state

        if run_in_background:
            return ToolResult(
                success=True,
                data={
                    "worker_id": run_state.worker_id,
                    "status": run_state.status,
                    "subagent_type": run_state.subagent_type,
                    "description": run_state.description,
                    "run_in_background": True,
                    "orchestration_id": run_state.orchestration_id,
                    "subtask_id": run_state.subtask_id,
                    "target_task_agent_type": run_state.target_task_agent_type,
                    "target_task_agent_id": run_state.target_task_agent_id,
                    "needs_await": True,
                },
            )

        if run_state.task is not None:
            # Keep worker task alive even if caller-side timeout/cancellation occurs.
            await asyncio.shield(run_state.task)
        return self._build_run_result(run_state)

    async def _start_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> WorkerRunState | ToolResult:
        if self._llm_adapter is None:
            return ToolResult(
                success=False,
                error="Agent tool is not configured with an LLM adapter",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        subagent_type = self._normalize_subagent_type(str(parameters.get("subagent_type", "")))
        if not subagent_type:
            return ToolResult(
                success=False,
                error="Unsupported subagent_type. Expected one of: general-purpose, Explore, Plan",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        description = str(parameters.get("description", "")).strip()
        prompt = str(parameters.get("prompt", "")).strip()
        max_iterations = int(parameters.get("max_iterations", DEFAULT_WORKER_MAX_ITERATIONS))
        orchestration_id = optional_string(parameters.get("orchestration_id"))
        subtask_id = optional_string(parameters.get("subtask_id"))
        retry_count = int(parameters.get("retry_count", 0))
        parent_context_summary = str(parameters.get("parent_context_summary", "")).strip()
        turn_id = optional_string(parameters.get("turn_id") or context.env_vars.get("turn_id"))

        user_id = str(context.env_vars.get("user_id", "unknown"))
        session_id = str(context.env_vars.get("session_id", ""))
        parent_task_agent_type = str(
            parameters.get("parent_task_agent_type")
            or context.env_vars.get("parent_task_agent_type")
            or parameters.get("target_task_agent_type")
            or context.env_vars.get("target_task_agent_type")
            or "chat"
        )
        parent_task_agent_id = str(
            parameters.get("parent_task_agent_id")
            or context.env_vars.get("parent_task_agent_id")
            or parameters.get("target_task_agent_id")
            or context.env_vars.get("target_task_agent_id")
            or user_id
            or "default"
        )
        target_task_agent_type = str(
            parameters.get("target_task_agent_type") or parent_task_agent_type
        )
        target_task_agent_id = str(parameters.get("target_task_agent_id") or parent_task_agent_id)

        worker_id = f"worker_{uuid.uuid4().hex[:10]}"
        created_at = time.time()
        started_at_ms = int(created_at * 1000)
        run_id = (
            str(parameters.get("run_id") or context.env_vars.get("run_id") or "").strip() or None
        )
        try:
            run_revision = int(
                parameters.get("run_revision") or context.env_vars.get("run_revision") or 0
            )
        except (TypeError, ValueError):
            run_revision = 0
        run_state = WorkerRunState(
            worker_id=worker_id,
            subagent_type=subagent_type,
            description=description,
            prompt=prompt,
            orchestration_id=orchestration_id,
            subtask_id=subtask_id,
            parent_task_agent_type=parent_task_agent_type,
            parent_task_agent_id=parent_task_agent_id,
            target_task_agent_type=target_task_agent_type,
            target_task_agent_id=target_task_agent_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            run_revision=run_revision,
            created_at=created_at,
            updated_at=created_at,
            retry_count=retry_count,
            parent_context_summary=parent_context_summary,
            started_at_ms=started_at_ms,
            started_monotonic=time.monotonic(),
        )

        selected_tools = self._resolve_tools_for_type(subagent_type)
        run_state.selected_tools = list(selected_tools)
        worker_system_prompt = self._build_worker_system_prompt(
            worker_id=worker_id,
            subagent_type=subagent_type,
            description=description,
            selected_tools=selected_tools,
            execution_workspace=context.workspace,
        )

        run_state.task = asyncio.create_task(
            self._run_worker(
                run_state=run_state,
                worker_system_prompt=worker_system_prompt,
                selected_tools=selected_tools,
                max_iterations=max_iterations,
                execution_workspace=context.workspace,
            ),
            name=f"agent-tool-{worker_id}",
        )

        async with self._lock:
            self._runs[worker_id] = run_state
            self._trim_history(max_runs=100)
        await self._emit_worker_dispatch_trace(run_state)
        await self._emit_worker_attempt_started_trace(run_state)
        await self._emit_worker_started_trace(run_state)
        return run_state

    async def _launch_workers_batch(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        workers = parameters.get("workers")
        if not isinstance(workers, list) or not workers:
            return ToolResult(
                success=False,
                error="workers must be a non-empty array",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        run_in_background = bool(parameters.get("run_in_background", False))
        parallel = bool(parameters.get("parallel", True))
        default_max_iterations = int(
            parameters.get("max_iterations", DEFAULT_WORKER_MAX_ITERATIONS)
        )

        run_states: List[WorkerRunState] = []
        for worker in workers:
            worker_params = dict(parameters)
            worker_params.update(worker if isinstance(worker, dict) else {})
            worker_params["max_iterations"] = int(
                worker.get("max_iterations", default_max_iterations)
            )
            run_state = await self._start_worker(worker_params, context)
            if isinstance(run_state, ToolResult):
                return run_state
            run_states.append(run_state)

            if not parallel and not run_in_background and run_state.task is not None:
                await run_state.task

        if not run_in_background and parallel:
            tasks = [state.task for state in run_states if state.task is not None]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        data = {
            "worker_count": len(run_states),
            "run_in_background": run_in_background,
            "parallel": parallel,
        }
        orchestration_ids = {
            state.orchestration_id for state in run_states if state.orchestration_id
        }
        if len(orchestration_ids) == 1:
            data["orchestration_id"] = next(iter(orchestration_ids))
        if run_in_background:
            data["status"] = "running"
            data["worker_ids"] = [state.worker_id for state in run_states]
            return ToolResult(success=True, data=data)

        data["workers"] = [self._serialize_run_state(state) for state in run_states]
        all_success = all(state.status == "completed" for state in run_states)
        return ToolResult(
            success=all_success,
            data=data,
            error=None if all_success else "Some workers failed",
            error_code=None if all_success else ToolErrorCode.EXECUTION_ERROR.value,
        )

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
            # Prepend parent context summary to system prompt when inherited.
            effective_system_prompt = worker_system_prompt
            if run_state.parent_context_summary:
                effective_system_prompt = (
                    worker_system_prompt + "\n\n--- PARENT CONVERSATION CONTEXT ---\n"
                    "The following is a summary of the parent agent's conversation "
                    "that led to your creation. Use it for background context only; "
                    "focus on your assigned task.\n\n"
                    + run_state.parent_context_summary
                    + "\n--- END PARENT CONTEXT ---\n"
                )

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
                    user_message=run_state.prompt,
                    system_prompt=effective_system_prompt,
                    selected_tools=selected_tools,
                    user_id=run_state.user_id,
                    session_id=run_state.session_id or run_state.worker_id,
                    turn_id=run_state.turn_id,
                    conversation_history=[],
                    max_iterations=max_iterations,
                    thinking_depth=ThinkingDepth.HIGH
                    if run_state.subagent_type == self.TYPE_PLAN
                    else ThinkingDepth.NONE,
                    intent=f"worker_{run_state.subagent_type.lower()}",
                    execution_agent_id=run_state.worker_id,
                    execution_workspace=execution_workspace,
                    llm_timeout_seconds=180.0
                    if run_state.subagent_type == self.TYPE_PLAN
                    else None,
                    final_response_json_mode=True,
                )
            run_state.completed_at = time.time()
            run_state.updated_at = run_state.completed_at
            run_state.failure_reason = outcome.failure_reason
            validated_result: Optional[WorkerResult] = None
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
                },
                public_payload={
                    "stage": "failed",
                    "error": run_state.error,
                    "result_preview": run_state.result_preview,
                },
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
