"""
Agent tool for launching specialized worker agents.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...core.logger import get_logger
from ...events.events import Event, EventLevel
from ..function_calling import FunctionCallingExecutor
from ..registry import ToolRegistry, tool_registry
from ..schema import (
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
    target_task_agent_type: str
    target_task_agent_id: str
    user_id: str
    session_id: str
    created_at: float
    status: str = "running"
    updated_at: float = 0.0
    completed_at: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None


class AgentTool(Tool):
    """Launch and manage worker agents for complex multi-step tasks."""

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
        self._runs: Dict[str, WorkerRunState] = {}
        self._lock = asyncio.Lock()
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

    def configure(self, llm_adapter, tool_registry_instance: Optional[ToolRegistry] = None) -> None:
        """Inject runtime dependencies after bootstrap."""
        self._llm_adapter = llm_adapter
        if tool_registry_instance is not None:
            self._tool_registry = tool_registry_instance

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
                    "target_task_agent_type": run_state.target_task_agent_type,
                    "target_task_agent_id": run_state.target_task_agent_id,
                },
            )

        if run_state.task is not None:
            await run_state.task
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

        user_id = str(context.env_vars.get("user_id", "unknown"))
        session_id = str(context.env_vars.get("session_id", ""))
        target_task_agent_type = str(parameters.get("target_task_agent_type") or context.env_vars.get("target_task_agent_type") or "chat")
        target_task_agent_id = str(parameters.get("target_task_agent_id") or context.env_vars.get("target_task_agent_id") or user_id or "default")

        worker_id = f"worker_{uuid.uuid4().hex[:10]}"
        created_at = time.time()
        run_state = WorkerRunState(
            worker_id=worker_id,
            subagent_type=subagent_type,
            description=description,
            prompt=prompt,
            target_task_agent_type=target_task_agent_type,
            target_task_agent_id=target_task_agent_id,
            user_id=user_id,
            session_id=session_id,
            created_at=created_at,
            updated_at=created_at,
        )

        selected_tools = self._resolve_tools_for_type(subagent_type)
        worker_system_prompt = self._build_worker_system_prompt(
            worker_id=worker_id,
            subagent_type=subagent_type,
            description=description,
            selected_tools=selected_tools,
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
            "workers": [self._serialize_run_state(state) for state in run_states],
        }
        if run_in_background:
            return ToolResult(success=True, data=data)

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
            event_payload={
                "stage": "started",
                "description": run_state.description,
                "subagent_type": run_state.subagent_type,
            },
        )

        try:
            executor = FunctionCallingExecutor(
                llm_adapter=self._llm_adapter,
                tool_registry=self._tool_registry,
                skill_executor=None,
                tool_result_callback=lambda payload: self._handle_tool_result(run_state, payload),
            )
            result_text = await executor.execute_with_tools(
                user_message=run_state.prompt,
                system_prompt=worker_system_prompt,
                selected_tools=selected_tools,
                user_id=run_state.user_id,
                session_id=run_state.session_id or run_state.worker_id,
                conversation_history=[],
                max_iterations=max_iterations,
                disable_thinking=False if run_state.subagent_type == self.TYPE_PLAN else True,
                intent=f"worker_{run_state.subagent_type.lower()}",
                execution_agent_id=run_state.worker_id,
                execution_workspace=execution_workspace,
            )

            run_state.status = "completed"
            run_state.result = str(result_text)
            run_state.completed_at = time.time()
            run_state.updated_at = run_state.completed_at

            await self._publish_worker_fact(
                run_state=run_state,
                event_type=WORKER_AGENT_COMPLETED,
                event_payload={
                    "stage": "completed",
                    "result": run_state.result,
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
            await self._publish_worker_fact(
                run_state=run_state,
                event_type=WORKER_AGENT_FAILED,
                event_payload={
                    "stage": "failed",
                    "error": run_state.error,
                },
            )

    async def _handle_tool_result(self, run_state: WorkerRunState, payload: Dict[str, Any]) -> None:
        await self._publish_worker_fact(
            run_state=run_state,
            event_type=WORKER_AGENT_PROGRESS,
            event_payload={
                "stage": "tool_result",
                "tool_name": payload.get("tool_name"),
                "success": bool(payload.get("success")),
                "execution_time": float(payload.get("execution_time") or 0.0),
                "error": payload.get("error"),
                "result_preview": self._compact_value(payload.get("data")),
            },
        )

    async def _publish_worker_fact(
        self,
        run_state: WorkerRunState,
        event_type: str,
        event_payload: Dict[str, Any],
    ) -> None:
        try:
            from ...core.runtime.contracts import FactRecord
            from ...runtime import get_agent_runtime

            runtime = get_agent_runtime()
            manager = runtime.get_task_agent_manager()
        except Exception as exc:
            logger.debug(
                "Worker fact publish skipped (runtime unavailable) | worker_id=%s error=%s",
                run_state.worker_id,
                exc,
            )
            return

        now = time.time()
        payload = {
            "worker_id": run_state.worker_id,
            "worker_status": run_state.status,
            "worker_subagent_type": run_state.subagent_type,
            "worker_description": run_state.description,
            "user_id": run_state.user_id,
            "session_id": run_state.session_id,
            "timestamp": now,
            **event_payload,
        }
        fact = FactRecord(
            agent_id=f"{run_state.target_task_agent_type}:{run_state.target_task_agent_id}",
            event_type=event_type,
            payload=payload,
            agent_type=run_state.target_task_agent_type,
            agent_instance_id=run_state.target_task_agent_id,
            timestamp=now,
            correlation_id=run_state.worker_id,
        )
        await manager.add_fact_to_agent(run_state.target_task_agent_type, run_state.target_task_agent_id, fact)
        await self._publish_worker_bus_event(event_type=event_type, payload=payload, correlation_id=run_state.worker_id)

    async def _publish_worker_bus_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> None:
        try:
            from ...core.container import get_container

            container = get_container()
            message_bus = container.message_bus()
            if message_bus is None or type(message_bus).__name__ == "object":
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
            "target_task_agent_type": run_state.target_task_agent_type,
            "target_task_agent_id": run_state.target_task_agent_id,
            "created_at": run_state.created_at,
            "updated_at": run_state.updated_at,
            "completed_at": run_state.completed_at,
            "result": run_state.result,
            "error": run_state.error,
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
    ) -> str:
        base_rules = (
            f"You are worker agent {worker_id}. "
            f"Task summary: {description}. "
            "You can use tools autonomously and should keep reasoning concise. "
            "Return a clear final answer with key findings and evidence."
        )
        tool_rules = (
            "Only use these tools: " + ", ".join(selected_tools)
            if selected_tools
            else "No tools are available. Reason directly from prompt context."
        )
        if subagent_type == self.TYPE_EXPLORE:
            role_rules = (
                "Focus on layered codebase exploration instead of one-shot root scans.\n"
                "Explore in this order: frontend -> backend -> ops/runtime -> docs/specs.\n"
                "For each layer, first discover with targeted glob patterns, then validate with grep/file_read,\n"
                "and produce 2-4 concise findings with exact file paths.\n"
                "Avoid broad commands like `ls -la <repo_root>` and avoid dumping huge file trees.\n"
                "Ignore generated/vendor paths unless explicitly requested (node_modules, dist, build, .git, .venv)."
            )
        elif subagent_type == self.TYPE_PLAN:
            role_rules = (
                "Act as a software architect. Produce a practical implementation plan "
                "with ordered steps, critical files, and trade-offs."
            )
        else:
            role_rules = (
                "Act as a general-purpose execution agent for complex multi-step tasks. "
                "Break down work and use tools proactively when uncertain."
            )
        return "\n".join([base_rules, role_rules, tool_rules])

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
