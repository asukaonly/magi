"""Worker launch lifecycle helpers for the agent tool."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Protocol, cast

from ..cancel import EventCancelToken
from ...tools.schema import ToolErrorCode, ToolExecutionContext, ToolResult
from .worker_state import DEFAULT_WORKER_MAX_ITERATIONS, WorkerRunState, optional_string


class _WorkerLaunchHostProtocol(Protocol):
    _llm_adapter: Any
    _lock: asyncio.Lock
    _runs: Dict[str, WorkerRunState]

    async def _start_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> WorkerRunState | ToolResult: ...

    def _normalize_subagent_type(self, subagent_type: str) -> str: ...

    def _resolve_tools_for_type(self, subagent_type: str) -> List[str]: ...

    def _build_worker_system_prompt(
        self,
        *,
        worker_id: str,
        subagent_type: str,
        description: str,
        selected_tools: List[str],
        execution_workspace: str,
    ) -> str: ...

    async def _run_worker(
        self,
        run_state: WorkerRunState,
        worker_system_prompt: str,
        selected_tools: List[str],
        max_iterations: int,
        execution_workspace: str,
    ) -> None: ...

    def _trim_history(self, max_runs: int) -> None: ...

    def _build_run_result(self, run_state: WorkerRunState) -> ToolResult: ...

    def _serialize_run_state(self, run_state: WorkerRunState) -> Dict[str, Any]: ...

    async def _emit_worker_dispatch_trace(self, run_state: WorkerRunState) -> None: ...

    async def _emit_worker_attempt_started_trace(
        self, run_state: WorkerRunState
    ) -> None: ...

    async def _emit_worker_started_trace(self, run_state: WorkerRunState) -> None: ...


class WorkerLaunchMixin:
    """Start foreground, background, and batch worker runs."""

    async def _launch_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        host = cast(_WorkerLaunchHostProtocol, self)
        run_in_background = bool(parameters.get("run_in_background", False))
        run_state = await host._start_worker(parameters, context)
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
            await asyncio.shield(run_state.task)
        return host._build_run_result(run_state)

    async def _start_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> WorkerRunState | ToolResult:
        host = cast(_WorkerLaunchHostProtocol, self)
        if host._llm_adapter is None:
            return ToolResult(
                success=False,
                error="Agent tool is not configured with an LLM adapter",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        subagent_type = host._normalize_subagent_type(
            str(parameters.get("subagent_type", ""))
        )
        if not subagent_type:
            return ToolResult(
                success=False,
                error="Unsupported subagent_type. Expected one of: general-purpose, Explore, Plan",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        description = str(parameters.get("description", "")).strip()
        prompt = str(parameters.get("prompt", "")).strip()
        max_iterations = int(
            parameters.get("max_iterations", DEFAULT_WORKER_MAX_ITERATIONS)
        )
        orchestration_id = optional_string(parameters.get("orchestration_id"))
        subtask_id = optional_string(parameters.get("subtask_id"))
        retry_count = int(parameters.get("retry_count", 0))
        parent_context_summary = str(
            parameters.get("parent_context_summary", "")
        ).strip()
        turn_id = optional_string(
            parameters.get("turn_id") or context.env_vars.get("turn_id")
        )

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
        target_task_agent_id = str(
            parameters.get("target_task_agent_id") or parent_task_agent_id
        )

        worker_id = f"worker_{uuid.uuid4().hex[:10]}"
        created_at = time.time()
        started_at_ms = int(created_at * 1000)
        run_id = (
            str(
                parameters.get("run_id") or context.env_vars.get("run_id") or ""
            ).strip()
            or None
        )
        try:
            run_revision = int(
                parameters.get("run_revision")
                or context.env_vars.get("run_revision")
                or 0
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
            cancel_token=EventCancelToken(),
        )

        selected_tools = host._resolve_tools_for_type(subagent_type)
        run_state.selected_tools = list(selected_tools)
        worker_system_prompt = host._build_worker_system_prompt(
            worker_id=worker_id,
            subagent_type=subagent_type,
            description=description,
            selected_tools=selected_tools,
            execution_workspace=context.workspace,
        )

        run_state.task = asyncio.create_task(
            host._run_worker(
                run_state=run_state,
                worker_system_prompt=worker_system_prompt,
                selected_tools=selected_tools,
                max_iterations=max_iterations,
                execution_workspace=context.workspace,
            ),
            name=f"agent-tool-{worker_id}",
        )

        async with host._lock:
            host._runs[worker_id] = run_state
            host._trim_history(max_runs=100)
        await host._emit_worker_dispatch_trace(run_state)
        await host._emit_worker_attempt_started_trace(run_state)
        await host._emit_worker_started_trace(run_state)
        return run_state

    async def _launch_workers_batch(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        host = cast(_WorkerLaunchHostProtocol, self)
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

        data: Dict[str, Any] = {
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

        data["workers"] = [host._serialize_run_state(state) for state in run_states]
        all_success = all(state.status == "completed" for state in run_states)
        return ToolResult(
            success=all_success,
            data=data,
            error=None if all_success else "Some workers failed",
            error_code=None if all_success else ToolErrorCode.EXECUTION_ERROR.value,
        )
