"""
Worker manager for launching and tracking specialized worker agents.
"""
from __future__ import annotations

import asyncio
import os
import platform
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ...agent.orchestration import WorkerResult, get_orchestration_store
from ...config.models import ThinkingDepth
from ...core.logger import get_logger
from ...agent.execution.function_calling import FunctionCallingOrchestrator
from ...chat.workspace import get_default_chat_workspace_path
from ...runtime_trace import RuntimeTraceStore
from ...llm.streaming_events import stream_source
from ...tools.registry import ToolRegistry, tool_registry
from .worker_result_validation import WorkerResultValidationMixin
from .worker_state import (
    DEFAULT_WORKER_MAX_ITERATIONS,
    WORKER_AGENT_COMPLETED,
    WORKER_AGENT_FAILED,
    WORKER_AGENT_PROGRESS,
    WorkerRunState,
    optional_string,
)
from .worker_trace import WorkerTraceMixin
from ...tools.schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

logger = get_logger(__name__)

class WorkerAgentManager(WorkerTraceMixin, WorkerResultValidationMixin, Tool):
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

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="agent",
            description=(
                "Launch a specialized worker agent for complex tasks. "
                "Worker types: general-purpose, Explore, Plan. "
                "Supports foreground wait and background execution."
            ),
            category="agent",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    description="Action: launch, status, or await",
                    required=False,
                    default=self.ACTION_LAUNCH,
                    enum=[self.ACTION_LAUNCH, self.ACTION_STATUS, self.ACTION_AWAIT],
                ),
                ToolParameter(
                    name="worker_id",
                    type=ParameterType.STRING,
                    description="Worker id for status/await actions",
                    required=False,
                ),
                ToolParameter(
                    name="worker_ids",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description="Multiple worker ids for batch status/await actions",
                    required=False,
                ),
                ToolParameter(
                    name="subagent_type",
                    type=ParameterType.STRING,
                    description="Worker type: general-purpose, Explore, or Plan",
                    required=False,
                    enum=[
                        self.TYPE_GENERAL,
                        self.TYPE_EXPLORE,
                        self.TYPE_PLAN,
                        "explore",
                        "plan",
                        "general",
                    ],
                ),
                ToolParameter(
                    name="description",
                    type=ParameterType.STRING,
                    description="Short 3-5 word task summary",
                    required=False,
                ),
                ToolParameter(
                    name="prompt",
                    type=ParameterType.STRING,
                    description="Detailed task instructions for the worker agent",
                    required=False,
                ),
                ToolParameter(
                    name="workers",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.OBJECT,
                    description=(
                        "Batch worker definitions. Each item: "
                        "{subagent_type, description, prompt, target_task_agent_type?, "
                        "target_task_agent_id?, max_iterations?}"
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="parallel",
                    type=ParameterType.BOOLEAN,
                    description="Whether batch workers should run in parallel",
                    required=False,
                    default=True,
                ),
                ToolParameter(
                    name="run_in_background",
                    type=ParameterType.BOOLEAN,
                    description="Run asynchronously and return immediately",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="max_iterations",
                    type=ParameterType.INTEGER,
                    description="Maximum internal tool-loop iterations for this worker",
                    required=False,
                    default=20,
                    min_value=1,
                    max_value=50,
                ),
                ToolParameter(
                    name="timeout_seconds",
                    type=ParameterType.INTEGER,
                    description="Timeout in seconds for await action",
                    required=False,
                    default=300,
                    min_value=1,
                    max_value=3600,
                ),
                ToolParameter(
                    name="target_task_agent_type",
                    type=ParameterType.STRING,
                    description="Target task agent type to receive worker facts",
                    required=False,
                    default="chat",
                ),
                ToolParameter(
                    name="target_task_agent_id",
                    type=ParameterType.STRING,
                    description="Target task agent id to receive worker facts",
                    required=False,
                ),
                ToolParameter(
                    name="orchestration_id",
                    type=ParameterType.STRING,
                    description="Parent orchestration id when this worker belongs to a task decomposition",
                    required=False,
                ),
                ToolParameter(
                    name="subtask_id",
                    type=ParameterType.STRING,
                    description="Subtask id within the parent orchestration",
                    required=False,
                ),
                ToolParameter(
                    name="turn_id",
                    type=ParameterType.STRING,
                    description="Conversation turn id associated with the parent user request",
                    required=False,
                ),
                ToolParameter(
                    name="parent_task_agent_type",
                    type=ParameterType.STRING,
                    description="Parent task agent type that owns this worker",
                    required=False,
                ),
                ToolParameter(
                    name="parent_task_agent_id",
                    type=ParameterType.STRING,
                    description="Parent task agent id that owns this worker",
                    required=False,
                ),
                ToolParameter(
                    name="inherit_context",
                    type=ParameterType.BOOLEAN,
                    description=(
                        "Whether to pass a summary of the parent conversation "
                        "to the worker. When false (default), workers start "
                        "with a clean context and only see the prompt."
                    ),
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="retry_count",
                    type=ParameterType.INTEGER,
                    description="Retry attempt count for this worker launch",
                    required=False,
                    default=0,
                    min_value=0,
                    max_value=3,
                ),
            ],
            examples=[
                {
                    "input": {
                        "action": "launch",
                        "subagent_type": "Explore",
                        "description": "scan auth flow",
                        "prompt": "Find where JWT token is created and validated.",
                    },
                    "output": "Returns worker id and status",
                }
            ],
            timeout=300,
            dangerous=False,
            tags=["agent", "worker", "planning", "exploration"],
        )

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

    async def validate_parameters(
        self,
        parameters: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        valid, error = await super().validate_parameters(parameters)
        if not valid:
            return valid, error

        action = str(parameters.get("action", self.ACTION_LAUNCH))
        if action not in {self.ACTION_LAUNCH, self.ACTION_STATUS, self.ACTION_AWAIT}:
            return False, f"Unsupported action: {action}"

        worker_ids = parameters.get("worker_ids")
        has_worker_ids = isinstance(worker_ids, list) and len(worker_ids) > 0
        has_worker_id = bool(str(parameters.get("worker_id", "")).strip())
        if action in {self.ACTION_STATUS, self.ACTION_AWAIT} and not has_worker_id and not has_worker_ids:
            return False, "worker_id or worker_ids is required for status/await actions"

        if action == self.ACTION_LAUNCH:
            workers = parameters.get("workers")
            if isinstance(workers, list) and workers:
                for idx, worker in enumerate(workers):
                    if not isinstance(worker, dict):
                        return False, f"workers[{idx}] must be an object"
                    if not str(worker.get("subagent_type", "")).strip():
                        return False, f"workers[{idx}].subagent_type is required"
                    if not str(worker.get("description", "")).strip():
                        return False, f"workers[{idx}].description is required"
                    if not str(worker.get("prompt", "")).strip():
                        return False, f"workers[{idx}].prompt is required"
            else:
                if not str(parameters.get("subagent_type", "")).strip():
                    return False, "subagent_type is required for launch action"
                if not str(parameters.get("description", "")).strip():
                    return False, "description is required for launch action"
                if not str(parameters.get("prompt", "")).strip():
                    return False, "prompt is required for launch action"

        return True, None

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        action = str(parameters.get("action", self.ACTION_LAUNCH))
        if action == self.ACTION_STATUS:
            worker_ids = parameters.get("worker_ids")
            if isinstance(worker_ids, list) and worker_ids:
                return await self._get_workers_status([str(item) for item in worker_ids if str(item).strip()])
            return await self._get_worker_status(str(parameters.get("worker_id", "")))
        if action == self.ACTION_AWAIT:
            worker_ids = parameters.get("worker_ids")
            if isinstance(worker_ids, list) and worker_ids:
                return await self._await_workers(
                    worker_ids=[str(item) for item in worker_ids if str(item).strip()],
                    timeout_seconds=int(parameters.get("timeout_seconds", 300)),
                )
            return await self._await_worker(
                worker_id=str(parameters.get("worker_id", "")),
                timeout_seconds=int(parameters.get("timeout_seconds", 300)),
            )
        workers = parameters.get("workers")
        if isinstance(workers, list) and workers:
            return await self._launch_workers_batch(parameters, context)
        return await self._launch_worker(parameters, context)

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
        target_task_agent_type = str(parameters.get("target_task_agent_type") or parent_task_agent_type)
        target_task_agent_id = str(parameters.get("target_task_agent_id") or parent_task_agent_id)

        worker_id = f"worker_{uuid.uuid4().hex[:10]}"
        created_at = time.time()
        started_at_ms = int(created_at * 1000)
        run_id = str(parameters.get("run_id") or context.env_vars.get("run_id") or "").strip() or None
        try:
            run_revision = int(parameters.get("run_revision") or context.env_vars.get("run_revision") or 0)
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
        default_max_iterations = int(parameters.get("max_iterations", DEFAULT_WORKER_MAX_ITERATIONS))

        run_states: List[WorkerRunState] = []
        for worker in workers:
            worker_params = dict(parameters)
            worker_params.update(worker if isinstance(worker, dict) else {})
            worker_params["max_iterations"] = int(worker.get("max_iterations", default_max_iterations))
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
        orchestration_ids = {state.orchestration_id for state in run_states if state.orchestration_id}
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
                    worker_system_prompt
                    + "\n\n--- PARENT CONVERSATION CONTEXT ---\n"
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
                loop_event_callback=lambda payload: self._handle_worker_loop_event(run_state, payload),
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
                    thinking_depth=ThinkingDepth.HIGH if run_state.subagent_type == self.TYPE_PLAN else ThinkingDepth.NONE,
                    intent=f"worker_{run_state.subagent_type.lower()}",
                    execution_agent_id=run_state.worker_id,
                    execution_workspace=execution_workspace,
                    llm_timeout_seconds=180.0 if run_state.subagent_type == self.TYPE_PLAN else None,
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

    async def _get_worker_status(self, worker_id: str) -> ToolResult:
        async with self._lock:
            run_state = self._runs.get(worker_id)
        if run_state is None:
            return ToolResult(
                success=False,
                error=f"Worker not found: {worker_id}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )
        await self._refresh_run_state(run_state)
        return ToolResult(success=True, data=self._serialize_run_state(run_state))

    async def _get_workers_status(self, worker_ids: List[str]) -> ToolResult:
        workers = []
        missing_ids = []
        for worker_id in worker_ids:
            async with self._lock:
                run_state = self._runs.get(worker_id)
            if run_state is None:
                missing_ids.append(worker_id)
                continue
            await self._refresh_run_state(run_state)
            workers.append(self._serialize_run_state(run_state))

        success = len(missing_ids) == 0
        return ToolResult(
            success=success,
            data={
                "workers": workers,
                "worker_count": len(workers),
                "missing_worker_ids": missing_ids,
            },
            error=None if success else f"Some workers not found: {', '.join(missing_ids)}",
            error_code=None if success else ToolErrorCode.TOOL_NOT_FOUND.value,
        )

    async def _await_worker(self, worker_id: str, timeout_seconds: int) -> ToolResult:
        async with self._lock:
            run_state = self._runs.get(worker_id)
        if run_state is None:
            return ToolResult(
                success=False,
                error=f"Worker not found: {worker_id}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )

        if run_state.task is not None and not run_state.task.done():
            try:
                # Timeout should stop waiting, not terminate the worker task itself.
                await asyncio.wait_for(asyncio.shield(run_state.task), timeout=float(timeout_seconds))
            except asyncio.TimeoutError:
                return ToolResult(
                    success=False,
                    error=f"Waiting for worker timed out after {timeout_seconds}s",
                    error_code=ToolErrorCode.TIMEOUT.value,
                    data=self._serialize_run_state(run_state),
                )

        await self._refresh_run_state(run_state)
        return self._build_run_result(run_state)

    async def _await_workers(self, worker_ids: List[str], timeout_seconds: int) -> ToolResult:
        run_states = []
        missing_ids = []
        for worker_id in worker_ids:
            async with self._lock:
                run_state = self._runs.get(worker_id)
            if run_state is None:
                missing_ids.append(worker_id)
                continue
            run_states.append(run_state)

        if missing_ids:
            return ToolResult(
                success=False,
                error=f"Some workers not found: {', '.join(missing_ids)}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
                data={"missing_worker_ids": missing_ids},
            )

        pending_tasks = [state.task for state in run_states if state.task is not None and not state.task.done()]
        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(asyncio.shield(task) for task in pending_tasks), return_exceptions=True),
                    timeout=float(timeout_seconds),
                )
            except asyncio.TimeoutError:
                return ToolResult(
                    success=False,
                    error=f"Waiting for workers timed out after {timeout_seconds}s",
                    error_code=ToolErrorCode.TIMEOUT.value,
                    data={"workers": [self._serialize_run_state(state) for state in run_states]},
                )

        for state in run_states:
            await self._refresh_run_state(state)

        all_success = all(state.status == "completed" for state in run_states)
        return ToolResult(
            success=all_success,
            data={"workers": [self._serialize_run_state(state) for state in run_states]},
            error=None if all_success else "Some workers failed",
            error_code=None if all_success else ToolErrorCode.EXECUTION_ERROR.value,
        )

    async def _refresh_run_state(self, run_state: WorkerRunState) -> None:
        task = run_state.task
        if not task or not task.done():
            return
        if run_state.status != "running":
            return
        try:
            task.result()
        except Exception as exc:
            run_state.status = "failed"
            run_state.error = str(exc)
            run_state.updated_at = time.time()
            run_state.completed_at = run_state.updated_at

    def _build_run_result(self, run_state: WorkerRunState) -> ToolResult:
        success = run_state.status == "completed"
        return ToolResult(
            success=success,
            data=self._serialize_run_state(run_state),
            error=None if success else run_state.error or "Worker execution failed",
            error_code=None if success else ToolErrorCode.EXECUTION_ERROR.value,
        )

    def _serialize_run_state(self, run_state: WorkerRunState) -> Dict[str, Any]:
        return {
            "worker_id": run_state.worker_id,
            "status": run_state.status,
            "subagent_type": run_state.subagent_type,
            "description": run_state.description,
            "orchestration_id": run_state.orchestration_id,
            "subtask_id": run_state.subtask_id,
            "turn_id": run_state.turn_id,
            "parent_task_agent_type": run_state.parent_task_agent_type,
            "parent_task_agent_id": run_state.parent_task_agent_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
            "created_at": run_state.created_at,
            "updated_at": run_state.updated_at,
            "completed_at": run_state.completed_at,
            "result": run_state.result,
            "result_preview": run_state.result_preview,
            "error": run_state.error,
            "failure_reason": run_state.failure_reason,
            "retry_count": run_state.retry_count,
        }

    def _normalize_subagent_type(self, subagent_type: str) -> Optional[str]:
        return self._WORKER_TYPE_MAP.get(subagent_type.strip())

    def _resolve_tools_for_type(self, subagent_type: str) -> List[str]:
        available_tools = set(self._tool_registry.list_tools())
        if subagent_type == self.TYPE_GENERAL:
            # ``todo_write`` is planner-owned — the ``TaskOrchestrator``
            # mirrors its subtask list onto the session todo store, so
            # leaf workers must not rewrite it mid-flight.
            return sorted(
                name
                for name in available_tools
                if name not in {"agent", "todo_write"}
            )
        if subagent_type == self.TYPE_EXPLORE:
            return [name for name in self._EXPLORE_TOOL_CANDIDATES if name in available_tools]
        if subagent_type == self.TYPE_PLAN:
            return [name for name in self._PLAN_TOOL_CANDIDATES if name in available_tools]
        return []

    def _build_worker_system_prompt(
        self,
        worker_id: str,
        subagent_type: str,
        description: str,
        selected_tools: List[str],
        execution_workspace: Optional[str] = None,
    ) -> str:
        base_rules = (
            f"You are worker agent {worker_id}. "
            f"Task summary: {description}. "
            "You are a leaf executor. Stay inside the given scope, use tools autonomously when needed, "
            "and return only the requested structured JSON result."
        )
        environment_rules = self._build_worker_environment_rules(execution_workspace)
        tool_rules = (
            "Only use these tools: " + ", ".join(selected_tools)
            if selected_tools
            else "No tools are available. Reason directly from prompt context."
        )
        if subagent_type == self.TYPE_EXPLORE:
            role_rules = self._build_explore_role_rules(description)
        elif subagent_type == self.TYPE_PLAN:
            role_rules = (
                "Act as a software architect. Return ONLY valid JSON with this schema: "
                '{"result_status":"success|partial|failed","summary":"string","findings":[{"title":"string","detail":"string"}],"evidence":[{"path":"string","detail":"string"}],"gaps":["string"],"next_steps":["string"],"failure_reason":"string|null","subtasks":[{"description":"string","subagent_type":"Explore|general-purpose","prompt":"string","parallel_group":"string"}]}. '
                "The plan must be decision-complete, keep subtasks bounded, and not include any final user-facing aggregation. "
                "Start from the most concrete anchor or owning code path you can identify, then split by neighboring responsibilities only when needed. "
                "Prefer execution-ready subtasks organized around concrete entry points, interfaces, modules, or discriminating checks. "
                "Avoid generic subtasks like gathering context or summarizing risks unless the parent request explicitly needs them or ambiguity remains unresolved. "
                "If you name a file, symbol, route, flag, or config key in findings or evidence, confirm it exists in the current code before treating it as fact. "
                "Any response that is not a single valid JSON object will be treated as failure."
            )
        else:
            role_rules = (
                "Act as a general-purpose leaf execution agent for one bounded task. "
                "Return ONLY valid JSON with this schema: "
                '{"result_status":"success|partial|failed","summary":"string","findings":[{"title":"string","detail":"string","path":"string","why_it_matters":"string"}],"evidence":[{"path":"string","detail":"string"}],"gaps":["string"],"next_steps":["string"],"failure_reason":"string|null"}. '
                "Any response that is not a single valid JSON object will be treated as failure."
            )
        return "\n".join([base_rules, environment_rules, role_rules, tool_rules])

    def _build_worker_environment_rules(self, execution_workspace: Optional[str]) -> str:
        workspace_root = self._resolve_execution_workspace(execution_workspace)
        home_dir = os.path.realpath(os.path.expanduser("~"))
        current_time = datetime.now().astimezone().isoformat(timespec="seconds")
        return "\n".join(
            [
                "Execution environment:",
                f"- Workspace root: {workspace_root}",
                f"- Home directory: {home_dir}",
                f"- Operating system: {platform.system()} {platform.release()}",
                f"- Current local time: {current_time}",
                f"- Interpret '~' as: {home_dir}",
                "- Prefer paths under the workspace root unless the prompt explicitly requires another location.",
                "- Do not invent alternative Linux-style or macOS-style home paths when a path is missing; report the missing path instead.",
            ]
        )

    def _resolve_execution_workspace(self, execution_workspace: Optional[str]) -> str:
        raw_workspace = str(execution_workspace or "").strip() or get_default_chat_workspace_path()
        return os.path.realpath(os.path.expandvars(os.path.expanduser(raw_workspace)))

    def _build_explore_role_rules(self, description: str) -> str:
        lowered = description.lower()
        profile = self._select_explore_prompt_profile(lowered)
        common_rules = """
Prioritize bounded exploration over exhaustive scans.
Common rules:
1.Directionality: Start from the layer most likely to contain the answer. If unclear, follow: frontend -> backend -> ops -> docs.
    2.Anchor First: Identify the most concrete likely anchor first (entry file, symbol, route, config, or owning module) and investigate that before widening scope.
2.Precision Search: Use targeted glob patterns to map structure, then grep for logic entry points. Strictly avoid root-level ls -R or dumping non-essential trees.
3.Execution Discipline: For glob calls, default to recursive=false and only recurse when pattern explicitly includes '**'. Never use '*' or '**/*' at repository root.
4.Scope Control: Start from one focused layer (frontend/, backend/, docs/, scripts/) and expand only if needed. Keep every glob/grep call at max_results <= 200.
5.Negative Constraints: Always exclude node_modules, dist, build, .git, .venv, __pycache__, and lock files. Do not read binary files or minified assets.
    6.Claim Validation: If you mention a file, symbol, route, flag, or config key in findings, confirm it exists in the current code before treating it as fact.
6.Incremental Validation: Identify 2-5 validated findings with absolute paths and a brief 'why it matters'. Prefer source-of-truth entry files over broad scans.
7.Response Validation: Your final answer must be one parseable JSON object and nothing else. Any prose, markdown, code fences, or trailing commentary will be treated as failure.
"""
        schema_rules = """
STRICT OUTPUT SCHEMA:
Return ONLY valid JSON with this schema:
{
  "result_status": "success|partial|failed",
  "summary": "string",
  "findings": [{"title": "string", "detail": "string", "path": "string", "why_it_matters": "string"}],
  "evidence": [{"path": "string", "detail": "string"}],
  "gaps": ["string"],
  "next_steps": ["string"],
  "failure_reason": "string|null"
}
Do not emit Markdown, prose before the JSON, or fenced code blocks.
Before sending the final answer, self-check that it can be parsed by json.loads and that all required fields are present.
"""
        return "\n".join([common_rules.strip(), profile, schema_rules.strip()])

    def _select_explore_prompt_profile(self, lowered_description: str) -> str:
        if "repository layout" in lowered_description or "layout" in lowered_description:
            return """
SUBTASK PROFILE: Repository Layout
- Primary goal: map the top-level structure, major directories, and ownership boundaries.
- Start with immediate children of the repository root and major first-level folders before any recursive scan.
- Prefer directory and manifest evidence over reading many implementation files.
- Do not drift into detailed frontend/backend logic unless it is necessary to explain module boundaries.
""".strip()
        if "technology stack" in lowered_description or "tech stack" in lowered_description:
            return """
SUBTASK PROFILE: Technology Stack
- Primary goal: identify frameworks, runtimes, storage, package managers, and deployment/runtime targets.
- Prioritize dependency manifests, lockfiles, config files, boot files, and build scripts.
- Avoid broad source-code traversal unless a manifest is ambiguous and needs confirmation.
- Call out the evidence file that confirms each stack claim.
""".strip()
        if "frontend structure" in lowered_description or "frontend" in lowered_description:
            return """
SUBTASK PROFILE: Frontend Structure
- Primary goal: explain frontend organization, bootstrap flow, routing, stores, and key UI entry points.
- Start from frontend entry files, router setup, app shell, and major feature folders.
- Prefer reading index, main, router, page, and store files before component-level exploration.
- Do not spend time on backend or docs unless they directly explain the frontend boundary.
""".strip()
        if "backend modules" in lowered_description or "backend" in lowered_description:
            return """
SUBTASK PROFILE: Backend Modules
- Primary goal: explain backend module boundaries, runtime startup, task-agent chain, APIs, and execution flow.
- Start from backend bootstrap/backend.py and app entry files, then trace the task-agent and worker chain.
- Prefer source-of-truth files such as backend app creation, bootstrap wiring, router wiring, and agent runtime modules.
- Do not drift into frontend structure or docs unless they are required to explain a backend dependency.
""".strip()
        if "project progress" in lowered_description or "progress" in lowered_description:
            return """
SUBTASK PROFILE: Project Progress
- Primary goal: infer current project status, active migration work, and unfinished areas.
- Prioritize README, PROGRESS, CHANGELOG, migration plans, release notes, TODO-style docs, and roadmap files.
- Use source code only as supporting evidence when documentation is stale or missing.
- Do not spend time mapping the whole codebase; stay focused on status signals and recent direction.
""".strip()
        return """
SUBTASK PROFILE: Generic Exploration
- Primary goal: gather the minimum source-of-truth evidence needed to answer this bounded exploration request.
- Start from the most likely folder and expand only when evidence is incomplete.
- Prefer entry files, manifests, and coordinator modules over exhaustive file reads.
- Keep the result narrow, evidence-driven, and scoped to the assigned subtask.
""".strip()

    def _trim_history(self, max_runs: int) -> None:
        if len(self._runs) <= max_runs:
            return
        sorted_runs = sorted(self._runs.values(), key=lambda item: item.created_at)
        to_remove = len(sorted_runs) - max_runs
        for run_state in sorted_runs[:to_remove]:
            if run_state.status == "running":
                continue
            self._runs.pop(run_state.worker_id, None)

    def _compact_value(self, value: Any, limit: int = 500) -> str:
        text = str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + "...(truncated)"
