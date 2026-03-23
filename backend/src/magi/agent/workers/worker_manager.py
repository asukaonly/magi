"""
Worker manager for launching and tracking specialized worker agents.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...agent.orchestration import WorkerEvidence, WorkerFinding, WorkerResult, get_orchestration_store
from ...agent.trace import build_trace_timing, now_wall_ms
from ...core.logger import get_logger
from ...events.events import Event, EventLevel
from ...agent.execution.function_calling import FunctionCallingOrchestrator
from ...runtime_trace import (
    RuntimeNotificationRecord,
    RuntimeTraceStore,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceToolRecord,
)
from ...tools.registry import ToolRegistry, tool_registry
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

WORKER_AGENT_PROGRESS = "WORKER_AGENT_PROGRESS"
WORKER_AGENT_COMPLETED = "WORKER_AGENT_COMPLETED"
WORKER_AGENT_FAILED = "WORKER_AGENT_FAILED"


@dataclass
class WorkerRunState:
    """Runtime state for one worker execution."""

    worker_id: str
    subagent_type: str
    description: str
    prompt: str
    orchestration_id: Optional[str]
    subtask_id: Optional[str]
    parent_task_agent_type: str
    parent_task_agent_id: str
    target_task_agent_type: str
    target_task_agent_id: str
    user_id: str
    session_id: str
    turn_id: Optional[str]
    created_at: float
    run_id: str | None = None
    run_revision: int = 0
    status: str = "running"
    updated_at: float = 0.0
    completed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    result_preview: Optional[str] = None
    error: Optional[str] = None
    failure_reason: Optional[str] = None
    retry_count: int = 0
    task: Optional[asyncio.Task] = None
    selected_tools: list[str] = field(default_factory=list)
    started_at_ms: int = 0
    started_monotonic: float = 0.0


class WorkerAgentManager(Tool):
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
        self._tool_registry: ToolRegistry = tool_registry
        self._task_agent_manager = None
        self._message_bus = None
        self._runtime_trace_store: RuntimeTraceStore | None = None
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
                    default=8,
                    min_value=1,
                    max_value=30,
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
        max_iterations = int(parameters.get("max_iterations", 8))
        orchestration_id = _optional_string(parameters.get("orchestration_id"))
        subtask_id = _optional_string(parameters.get("subtask_id"))
        retry_count = int(parameters.get("retry_count", 0))
        turn_id = _optional_string(parameters.get("turn_id") or context.env_vars.get("turn_id"))

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
        default_max_iterations = int(parameters.get("max_iterations", 8))

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
            executor = FunctionCallingOrchestrator(
                llm_adapter=self._llm_adapter,
                tool_registry=self._tool_registry,
                skill_runner=None,
                tool_result_callback=lambda payload: self._handle_tool_result(run_state, payload),
                loop_event_callback=lambda payload: self._handle_worker_loop_event(run_state, payload),
                runtime_trace_store=self._runtime_trace_store,
            )
            outcome = await executor.execute_with_tools(
                user_message=run_state.prompt,
                system_prompt=worker_system_prompt,
                selected_tools=selected_tools,
                user_id=run_state.user_id,
                session_id=run_state.session_id or run_state.worker_id,
                turn_id=run_state.turn_id,
                conversation_history=[],
                max_iterations=max_iterations,
                disable_thinking=False if run_state.subagent_type == self.TYPE_PLAN else True,
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
            run_state.error = run_state.error or outcome.failure_reason or "Worker execution failed"
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

    async def _handle_worker_loop_event(self, run_state: WorkerRunState, payload: Dict[str, Any]) -> None:
        llm_trace = payload.get("llm_trace")
        if not isinstance(llm_trace, dict) or not llm_trace:
            return
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = now_wall_ms()
        started_at_ms = max(0, ended_at_ms - duration_ms)
        stage = str(payload.get("stage") or "unknown")
        iteration = max(0, int(payload.get("iteration") or 0))
        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        span_id = self._build_worker_llm_span_id(
            turn_id=trace_turn_id,
            trace_key=trace_key,
            attempt_index=attempt_index,
            stage=stage,
            iteration=iteration,
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="llm_call",
                name=f"{run_state.subagent_type} worker LLM call",
                status="completed",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                iteration=iteration,
                execution_agent_id=run_state.worker_id,
                result_preview=str(payload.get("response_preview") or "")[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_llm_call(
            TraceLlmCallRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                response_preview=str(payload.get("response_preview") or "")[:240] or None,
            )
        )

    def _build_trace_emitter(self) -> TraceEventEmitter | None:
        if self._message_bus is None:
            return None
        return TraceEventEmitter(emit_runtime_event=self._emit_trace_runtime_event)

    async def _emit_trace_runtime_event(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
        success: bool = True,
    ) -> None:
        _ = success
        await self._publish_worker_bus_event(
            event_type=event_type,
            payload=payload,
            correlation_id=str(correlation_id or payload.get("span_id") or uuid.uuid4()),
        )

    async def _emit_worker_dispatch_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        dispatch_span_id = self._build_worker_dispatch_span_id(trace_turn_id, self._worker_trace_key(run_state))
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=dispatch_span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_root_span_id(trace_turn_id),
                node_type="worker_dispatch",
                name="Worker dispatch",
                status="completed",
                attempt_index=run_state.retry_count + 1,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=run_state.description[:240] or None,
                started_at_ms=run_state.started_at_ms,
                ended_at_ms=run_state.started_at_ms,
                duration_ms=0,
                created_at_ms=run_state.started_at_ms,
                updated_at_ms=run_state.started_at_ms,
            )
        )

    async def _emit_worker_attempt_started_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_dispatch_span_id(trace_turn_id, trace_key),
                node_type="worker_attempt",
                name=f"Attempt {attempt_index}",
                status="running",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                started_at_ms=run_state.started_at_ms,
                created_at_ms=run_state.started_at_ms,
                updated_at_ms=run_state.started_at_ms,
            )
        )

    async def _emit_worker_started_trace(self, run_state: WorkerRunState) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="worker",
                name=f"{run_state.subagent_type} worker",
                status="running",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=run_state.description[:240] or None,
                started_at_ms=run_state.started_at_ms,
                created_at_ms=run_state.started_at_ms,
                updated_at_ms=run_state.started_at_ms,
            )
        )

    async def _emit_worker_completed_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state=run_state, status="completed")
        await self._emit_worker_attempt_terminal_trace(run_state=run_state, status="completed")

    async def _emit_worker_failed_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state=run_state, status="failed")
        await self._emit_worker_attempt_terminal_trace(run_state=run_state, status="failed")

    async def _emit_worker_attempt_terminal_trace(self, run_state: WorkerRunState, status: str) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        ended_at_ms = int((run_state.completed_at or run_state.updated_at or time.time()) * 1000)
        timing = build_trace_timing(
            started_at_ms=run_state.started_at_ms,
            ended_at_ms=ended_at_ms,
            started_monotonic=run_state.started_monotonic or None,
            ended_monotonic=time.monotonic(),
        )
        output_payload = {
            "worker_id": run_state.worker_id,
            "result_preview": run_state.result_preview,
            "failure_reason": run_state.failure_reason,
        }
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_dispatch_span_id(trace_turn_id, trace_key),
                node_type="worker_attempt",
                name=f"Attempt {attempt_index}",
                status=status,
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=output_payload["result_preview"],
                error_text=(
                    run_state.error or run_state.failure_reason or "Worker attempt failed"
                    if status != "completed"
                    else None
                ),
                started_at_ms=timing.started_at_ms,
                ended_at_ms=timing.ended_at_ms or timing.started_at_ms,
                duration_ms=timing.duration_ms or 0,
                created_at_ms=timing.started_at_ms,
                updated_at_ms=timing.ended_at_ms or timing.started_at_ms,
            )
        )

    async def _emit_worker_terminal_trace(self, run_state: WorkerRunState, status: str) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        ended_at_ms = int((run_state.completed_at or run_state.updated_at or time.time()) * 1000)
        timing = build_trace_timing(
            started_at_ms=run_state.started_at_ms,
            ended_at_ms=ended_at_ms,
            started_monotonic=run_state.started_monotonic or None,
            ended_monotonic=time.monotonic(),
        )
        output_payload = {
            "result_preview": run_state.result_preview,
            "result": dict(run_state.result or {}),
            "failure_reason": run_state.failure_reason,
        }
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_attempt_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="worker",
                name=f"{run_state.subagent_type} worker",
                status=status,
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=output_payload["result_preview"],
                error_text=(
                    run_state.error or run_state.failure_reason or "Worker execution failed"
                    if status != "completed"
                    else None
                ),
                started_at_ms=timing.started_at_ms,
                ended_at_ms=timing.ended_at_ms or timing.started_at_ms,
                duration_ms=timing.duration_ms or 0,
                created_at_ms=timing.started_at_ms,
                updated_at_ms=timing.ended_at_ms or timing.started_at_ms,
            )
        )

    async def _emit_worker_tool_trace(
        self,
        *,
        run_state: WorkerRunState,
        payload: Dict[str, Any],
        result_preview: str,
    ) -> None:
        trace_turn_id = self._resolve_trace_turn_id(run_state)
        if self._runtime_trace_store is None or trace_turn_id is None:
            return

        execution_time_seconds = float(payload.get("execution_time") or 0.0)
        duration_ms = max(0, int(round(execution_time_seconds * 1000)))
        ended_at_ms = now_wall_ms()
        started_at_ms = max(0, ended_at_ms - duration_ms)
        tool_name = str(payload.get("tool_name") or "unknown")
        trace_key = self._worker_trace_key(run_state)
        attempt_index = run_state.retry_count + 1
        tool_span_id = self._build_worker_tool_span_id(
            turn_id=trace_turn_id,
            trace_key=trace_key,
            attempt_index=attempt_index,
            tool_call_id=str(payload.get("tool_call_id") or "") or None,
            tool_name=tool_name,
        )

        success = bool(payload.get("success"))
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=tool_span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                parent_span_id=self._build_worker_span_id(trace_turn_id, trace_key, attempt_index),
                node_type="tool_call",
                name=f"{tool_name} tool call",
                status="completed" if success else "failed",
                attempt_index=attempt_index,
                retry_count=run_state.retry_count,
                execution_agent_id=run_state.worker_id,
                result_preview=result_preview,
                error_text=str(payload.get("error") or "") or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_tool_call(
            TraceToolRecord(
                span_id=tool_span_id,
                trace_id=self._build_trace_id(trace_turn_id),
                turn_id=trace_turn_id,
                tool_name=tool_name,
                tool_call_id=str(payload.get("tool_call_id") or "") or None,
                arguments_json=json.dumps(payload.get("arguments") or {}),
                success=success,
                execution_time_ms=duration_ms,
                error_code=str(payload.get("error_code") or "") or None,
                error_message=str(payload.get("error") or "") or None,
                result_preview=result_preview,
            )
        )

    def _resolve_trace_turn_id(self, run_state: WorkerRunState) -> str | None:
        normalized_turn_id = str(run_state.turn_id or "").strip()
        return normalized_turn_id or None

    @staticmethod
    def _build_trace_id(turn_id: str) -> str:
        return f"trace:{turn_id}"

    @staticmethod
    def _build_root_span_id(turn_id: str) -> str:
        return f"{turn_id}:turn"

    @staticmethod
    def _build_worker_dispatch_span_id(turn_id: str, trace_key: str) -> str:
        return f"{turn_id}:worker_dispatch:{trace_key}"

    @staticmethod
    def _build_worker_attempt_span_id(turn_id: str, trace_key: str, attempt_index: int) -> str:
        return f"{turn_id}:worker_attempt:{trace_key}:{attempt_index}"

    @staticmethod
    def _build_worker_span_id(turn_id: str, trace_key: str, attempt_index: int) -> str:
        return f"{turn_id}:worker:{trace_key}:{attempt_index}"

    @staticmethod
    def _build_worker_llm_span_id(turn_id: str, trace_key: str, attempt_index: int, stage: str, iteration: int) -> str:
        return f"{turn_id}:worker_llm:{trace_key}:{attempt_index}:{stage}:{iteration}"

    @staticmethod
    def _build_worker_tool_span_id(
        turn_id: str,
        trace_key: str,
        attempt_index: int,
        tool_call_id: str | None,
        tool_name: str,
    ) -> str:
        if tool_call_id:
            return f"{turn_id}:worker_tool:{trace_key}:{attempt_index}:{tool_call_id}"
        return f"{turn_id}:worker_tool:{trace_key}:{attempt_index}:{tool_name}"

    @staticmethod
    def _worker_trace_key(run_state: WorkerRunState) -> str:
        return str(run_state.subtask_id or run_state.worker_id)

    @staticmethod
    def _build_worker_trace_tags(run_state: WorkerRunState) -> Dict[str, Any]:
        return {
            "role": "worker",
            "worker_id": run_state.worker_id,
            "worker_type": run_state.subagent_type,
            "orchestration_id": run_state.orchestration_id,
            "subtask_id": run_state.subtask_id,
            "parent_task_agent_type": run_state.parent_task_agent_type,
            "parent_task_agent_id": run_state.parent_task_agent_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
        }

    async def _publish_worker_fact(
        self,
        run_state: WorkerRunState,
        event_type: str,
        internal_payload: Dict[str, Any],
        public_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            from ...agent.runtime.contracts import FactRecord

            manager = self._task_agent_manager
            if manager is None:
                raise RuntimeError("task agent manager unavailable")
        except Exception as exc:
            logger.debug(
                "Worker fact publish skipped (runtime unavailable) | worker_id=%s error=%s",
                run_state.worker_id,
                exc,
            )
            return

        now = time.time()
        internal_data = {
            "worker_id": run_state.worker_id,
            "worker_status": run_state.status,
            "worker_subagent_type": run_state.subagent_type,
            "worker_description": run_state.description,
            "failure_reason": run_state.failure_reason,
            "orchestration_id": run_state.orchestration_id,
            "subtask_id": run_state.subtask_id,
            "parent_task_agent_type": run_state.parent_task_agent_type,
            "parent_task_agent_id": run_state.parent_task_agent_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
            "user_id": run_state.user_id,
            "session_id": run_state.session_id,
            "turn_id": run_state.turn_id,
            "run_id": run_state.run_id,
            "run_revision": run_state.run_revision,
            "timestamp": now,
            **internal_payload,
        }
        fact = FactRecord(
            agent_id=f"{run_state.target_task_agent_type}:{run_state.target_task_agent_id}",
            event_type=event_type,
            payload=internal_data,
            agent_type=run_state.target_task_agent_type,
            agent_instance_id=run_state.target_task_agent_id,
            timestamp=now,
            correlation_id=run_state.worker_id,
        )
        await manager.add_fact_to_agent(run_state.target_task_agent_type, run_state.target_task_agent_id, fact)
        external_data = {
            "worker_id": run_state.worker_id,
            "worker_status": run_state.status,
            "worker_subagent_type": run_state.subagent_type,
            "worker_description": run_state.description,
            "failure_reason": run_state.failure_reason,
            "orchestration_id": run_state.orchestration_id,
            "subtask_id": run_state.subtask_id,
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
            "user_id": run_state.user_id,
            "session_id": run_state.session_id,
            "turn_id": run_state.turn_id,
            "run_id": run_state.run_id,
            "run_revision": run_state.run_revision,
            "timestamp": now,
            **(public_payload or internal_payload),
        }
        await self._publish_worker_bus_event(event_type=event_type, payload=external_data, correlation_id=run_state.worker_id)

    async def _publish_worker_bus_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> None:
        try:
            message_bus = self._message_bus
            if message_bus is None:
                return
            await message_bus.publish(
                Event(
                    type=event_type,
                    data=payload,
                    source="agent_tool",
                    level=EventLevel.INFO,
                    correlation_id=correlation_id,
                )
            )
        except Exception as exc:
            logger.debug(f"Failed to publish worker bus event | event_type={event_type} error={exc}")
        await self._publish_trace_update_notification(payload)

    async def _publish_trace_update_notification(self, payload: Dict[str, Any]) -> None:
        if self._runtime_trace_store is None:
            return
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip() or None
        if not user_id or not session_id or not turn_id:
            return
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="trace_update",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json="{}",
                created_at_ms=now_wall_ms(),
            )
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
            return sorted([name for name in available_tools if name != "agent"])
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
                "Any response that is not a single valid JSON object will be treated as failure."
            )
        else:
            role_rules = (
                "Act as a general-purpose leaf execution agent for one bounded task. "
                "Return ONLY valid JSON with this schema: "
                '{"result_status":"success|partial|failed","summary":"string","findings":[{"title":"string","detail":"string"}],"evidence":[{"path":"string","detail":"string"}],"gaps":["string"],"next_steps":["string"],"failure_reason":"string|null"}. '
                "Any response that is not a single valid JSON object will be treated as failure."
            )
        return "\n".join([base_rules, environment_rules, role_rules, tool_rules])

    def _build_worker_environment_rules(self, execution_workspace: Optional[str]) -> str:
        workspace_root = os.path.realpath(
            os.path.expandvars(os.path.expanduser(execution_workspace or os.getcwd()))
        )
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

    def _build_explore_role_rules(self, description: str) -> str:
        lowered = description.lower()
        profile = self._select_explore_prompt_profile(lowered)
        common_rules = """
Prioritize bounded exploration over exhaustive scans.
Common rules:
1.Directionality: Start from the layer most likely to contain the answer. If unclear, follow: frontend -> backend -> ops -> docs.
2.Precision Search: Use targeted glob patterns to map structure, then grep for logic entry points. Strictly avoid root-level ls -R or dumping non-essential trees.
3.Execution Discipline: For glob calls, default to recursive=false and only recurse when pattern explicitly includes '**'. Never use '*' or '**/*' at repository root.
4.Scope Control: Start from one focused layer (frontend/, backend/, docs/, scripts/) and expand only if needed. Keep every glob/grep call at max_results <= 200.
5.Negative Constraints: Always exclude node_modules, dist, build, .git, .venv, __pycache__, and lock files. Do not read binary files or minified assets.
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

    def _validate_worker_result(self, subagent_type: str, content: str) -> WorkerResult:
        stripped = str(content or "").strip()
        if not stripped:
            raise ValueError("Worker returned an empty response")
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("Worker did not return valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Worker result must be a JSON object")
        required_keys = {"result_status", "summary", "findings", "evidence", "gaps", "next_steps"}
        if not required_keys.issubset(set(parsed.keys())):
            raise ValueError("Worker result is missing required fields")
        result_status = str(parsed.get("result_status", "")).strip()
        if result_status not in {"success", "partial", "failed"}:
            raise ValueError("Worker result field 'result_status' must be success, partial, or failed")
        if not isinstance(parsed.get("findings"), list):
            raise ValueError("Worker result field 'findings' must be a list")
        if not isinstance(parsed.get("evidence"), list):
            raise ValueError("Worker result field 'evidence' must be a list")
        if not isinstance(parsed.get("gaps"), list):
            raise ValueError("Worker result field 'gaps' must be a list")
        if not isinstance(parsed.get("next_steps"), list):
            raise ValueError("Worker result field 'next_steps' must be a list")

        worker_result = WorkerResult.from_dict(parsed)
        if not worker_result.summary:
            raise ValueError("Worker result requires a non-empty summary")
        self._validate_findings(worker_result.findings, subagent_type=subagent_type)
        self._validate_evidence(worker_result.evidence)
        self._validate_string_items(worker_result.gaps, field_name="gaps")
        self._validate_string_items(worker_result.next_steps, field_name="next_steps")
        if result_status == "failed" and not str(parsed.get("failure_reason") or "").strip():
            raise ValueError("Failed worker results must include failure_reason")

        if subagent_type == self.TYPE_PLAN:
            subtasks = parsed.get("subtasks")
            if not isinstance(subtasks, list) or not subtasks:
                raise ValueError("Plan worker result must include non-empty subtasks")
            if not worker_result.subtasks:
                raise ValueError("Plan worker subtasks require description, subagent_type, and prompt")
        return worker_result

    def _validate_findings(self, findings: List[WorkerFinding], subagent_type: str) -> None:
        for item in findings:
            title = item.title.strip()
            detail = item.detail.strip()
            if not title or not detail:
                raise ValueError("Each worker finding requires non-empty title and detail")
            if subagent_type != self.TYPE_PLAN:
                path = (item.path or "").strip()
                why_it_matters = (item.why_it_matters or "").strip()
                if not path or not why_it_matters:
                    raise ValueError(
                        "Each worker finding requires non-empty path and why_it_matters"
                    )

    def _validate_evidence(self, evidence: List[WorkerEvidence]) -> None:
        for item in evidence:
            path = item.path.strip()
            detail = item.detail.strip()
            if not path or not detail:
                raise ValueError("Each worker evidence entry requires non-empty path and detail")

    def _validate_string_items(self, values: List[str], field_name: str) -> None:
        for item in values:
            if not str(item).strip():
                raise ValueError(f"Worker result field '{field_name}' cannot contain empty items")

    def _preview_worker_result(self, worker_result: WorkerResult, limit: int = 400) -> str:
        summary = worker_result.summary.strip()
        if summary:
            return summary[:limit]
        if worker_result.findings:
            first = worker_result.findings[0]
            detail = str(first.detail or first.title).strip()
            if detail:
                return detail[:limit]
        return ""


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
