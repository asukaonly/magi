"""Worker launch lifecycle helpers for the agent tool."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, cast

from ..cancel import EventCancelToken
from ...tools.schema import ToolErrorCode, ToolExecutionContext, ToolResult
from .worker_state import DEFAULT_WORKER_MAX_ITERATIONS, WorkerRunState, optional_string


@dataclass(frozen=True, slots=True)
class _WorkerStartSpec:
    subagent_type: str
    description: str
    prompt: str
    max_iterations: int
    orchestration_id: str | None
    subtask_id: str | None
    retry_count: int
    parent_context_summary: str
    turn_id: str | None
    user_id: str
    session_id: str
    parent_task_agent_type: str
    parent_task_agent_id: str
    target_task_agent_type: str
    target_task_agent_id: str
    run_id: str | None
    run_revision: int
    user_message_generation: int | None
    execution_workspace: str


@dataclass(frozen=True, slots=True)
class _WorkerBatchOptions:
    run_in_background: bool
    parallel: bool
    default_max_iterations: Any


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

    async def _emit_worker_attempt_started_trace(self, run_state: WorkerRunState) -> None: ...

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

        spec = _resolve_worker_start_spec(host, parameters, context)
        if isinstance(spec, ToolResult):
            return spec

        run_state = _build_worker_run_state(spec)

        selected_tools = host._resolve_tools_for_type(spec.subagent_type)
        run_state.selected_tools = list(selected_tools)
        worker_system_prompt = host._build_worker_system_prompt(
            worker_id=run_state.worker_id,
            subagent_type=spec.subagent_type,
            description=spec.description,
            selected_tools=selected_tools,
            execution_workspace=spec.execution_workspace,
        )

        run_state.task = _create_worker_task(
            host,
            run_state,
            worker_system_prompt=worker_system_prompt,
            selected_tools=selected_tools,
            max_iterations=spec.max_iterations,
            execution_workspace=spec.execution_workspace,
        )

        await _register_worker_run(host, run_state)
        await _emit_worker_start_traces(host, run_state)
        return run_state

    async def _launch_workers_batch(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        host = cast(_WorkerLaunchHostProtocol, self)
        workers = _validated_batch_workers(parameters)
        if isinstance(workers, ToolResult):
            return workers
        options = _resolve_batch_options(parameters)
        run_states = await self._start_batch_workers(
            workers,
            parameters=parameters,
            context=context,
            options=options,
        )
        if isinstance(run_states, ToolResult):
            return run_states
        await _await_parallel_batch_if_needed(run_states, options)
        return _build_batch_result(host, run_states, options)

    async def _start_batch_workers(
        self,
        workers: List[Any],
        *,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
        options: _WorkerBatchOptions,
    ) -> List[WorkerRunState] | ToolResult:
        host = cast(_WorkerLaunchHostProtocol, self)
        run_states: List[WorkerRunState] = []
        for worker in workers:
            worker_params = _build_batch_worker_params(worker, parameters, options)
            run_state = await host._start_worker(worker_params, context)
            if isinstance(run_state, ToolResult):
                return run_state
            run_states.append(run_state)
            if _should_await_batch_worker_immediately(run_state, options):
                task = run_state.task
                if task is not None:
                    await task
        return run_states


def _resolve_worker_start_spec(
    host: _WorkerLaunchHostProtocol,
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
) -> _WorkerStartSpec | ToolResult:
    subagent_type = host._normalize_subagent_type(str(parameters.get("subagent_type", "")))
    if not subagent_type:
        return ToolResult(
            success=False,
            error="Unsupported subagent_type. Expected one of: general-purpose, CodeExplore, Plan",
            error_code=ToolErrorCode.INVALID_PARAMETERS.value,
        )

    user_id = str(context.env_vars.get("user_id", "unknown"))
    parent_type, parent_id = _resolve_parent_task_agent(parameters, context, user_id)
    run_id, run_revision = _resolve_run_identity(parameters, context)
    return _WorkerStartSpec(
        subagent_type=subagent_type,
        description=str(parameters.get("description", "")).strip(),
        prompt=str(parameters.get("prompt", "")).strip(),
        max_iterations=int(parameters.get("max_iterations", DEFAULT_WORKER_MAX_ITERATIONS)),
        orchestration_id=optional_string(parameters.get("orchestration_id")),
        subtask_id=optional_string(parameters.get("subtask_id")),
        retry_count=int(parameters.get("retry_count", 0)),
        parent_context_summary=str(parameters.get("parent_context_summary", "")).strip(),
        turn_id=optional_string(parameters.get("turn_id") or context.env_vars.get("turn_id")),
        user_id=user_id,
        session_id=str(context.env_vars.get("session_id", "")),
        parent_task_agent_type=parent_type,
        parent_task_agent_id=parent_id,
        target_task_agent_type=str(parameters.get("target_task_agent_type") or parent_type),
        target_task_agent_id=str(parameters.get("target_task_agent_id") or parent_id),
        run_id=run_id,
        run_revision=run_revision,
        user_message_generation=_resolve_user_message_generation(context),
        execution_workspace=context.workspace,
    )


def _resolve_parent_task_agent(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
    user_id: str,
) -> tuple[str, str]:
    parent_type = str(
        parameters.get("parent_task_agent_type")
        or context.env_vars.get("parent_task_agent_type")
        or parameters.get("target_task_agent_type")
        or context.env_vars.get("target_task_agent_type")
        or "chat"
    )
    parent_id = str(
        parameters.get("parent_task_agent_id")
        or context.env_vars.get("parent_task_agent_id")
        or parameters.get("target_task_agent_id")
        or context.env_vars.get("target_task_agent_id")
        or user_id
        or "default"
    )
    return parent_type, parent_id


def _resolve_run_identity(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
) -> tuple[str | None, int]:
    run_id = str(parameters.get("run_id") or context.env_vars.get("run_id") or "").strip()
    try:
        run_revision = int(
            parameters.get("run_revision") or context.env_vars.get("run_revision") or 0
        )
    except (TypeError, ValueError):
        run_revision = 0
    return run_id or None, run_revision


def _resolve_user_message_generation(
    context: ToolExecutionContext,
) -> int | None:
    raw_generation = context.env_vars.get("user_message_generation")
    if raw_generation is None or str(raw_generation).strip() == "":
        return None
    if isinstance(raw_generation, bool):
        return None
    try:
        generation = int(raw_generation)
    except (TypeError, ValueError):
        return None
    return generation if generation >= 0 else None


def _build_worker_run_state(spec: _WorkerStartSpec) -> WorkerRunState:
    worker_id = f"worker_{uuid.uuid4().hex[:10]}"
    created_at = time.time()
    return WorkerRunState(
        worker_id=worker_id,
        subagent_type=spec.subagent_type,
        description=spec.description,
        prompt=spec.prompt,
        orchestration_id=spec.orchestration_id,
        subtask_id=spec.subtask_id,
        parent_task_agent_type=spec.parent_task_agent_type,
        parent_task_agent_id=spec.parent_task_agent_id,
        target_task_agent_type=spec.target_task_agent_type,
        target_task_agent_id=spec.target_task_agent_id,
        user_id=spec.user_id,
        session_id=spec.session_id,
        turn_id=spec.turn_id,
        run_id=spec.run_id,
        run_revision=spec.run_revision,
        user_message_generation=spec.user_message_generation,
        created_at=created_at,
        updated_at=created_at,
        retry_count=spec.retry_count,
        parent_context_summary=spec.parent_context_summary,
        started_at_ms=int(created_at * 1000),
        started_monotonic=time.monotonic(),
        cancel_token=EventCancelToken(),
    )


def _create_worker_task(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
    *,
    worker_system_prompt: str,
    selected_tools: List[str],
    max_iterations: int,
    execution_workspace: str,
) -> asyncio.Task[None]:
    return asyncio.create_task(
        host._run_worker(
            run_state=run_state,
            worker_system_prompt=worker_system_prompt,
            selected_tools=selected_tools,
            max_iterations=max_iterations,
            execution_workspace=execution_workspace,
        ),
        name=f"agent-tool-{run_state.worker_id}",
    )


async def _register_worker_run(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
) -> None:
    async with host._lock:
        host._runs[run_state.worker_id] = run_state
        host._trim_history(max_runs=100)


async def _emit_worker_start_traces(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
) -> None:
    await host._emit_worker_dispatch_trace(run_state)
    await host._emit_worker_attempt_started_trace(run_state)
    await host._emit_worker_started_trace(run_state)


def _validated_batch_workers(parameters: Dict[str, Any]) -> List[Any] | ToolResult:
    workers = parameters.get("workers")
    if isinstance(workers, list) and workers:
        return workers
    return ToolResult(
        success=False,
        error="workers must be a non-empty array",
        error_code=ToolErrorCode.INVALID_PARAMETERS.value,
    )


def _resolve_batch_options(parameters: Dict[str, Any]) -> _WorkerBatchOptions:
    return _WorkerBatchOptions(
        run_in_background=bool(parameters.get("run_in_background", False)),
        parallel=bool(parameters.get("parallel", True)),
        default_max_iterations=parameters.get("max_iterations"),
    )


def _build_batch_worker_params(
    worker: Any,
    parameters: Dict[str, Any],
    options: _WorkerBatchOptions,
) -> Dict[str, Any]:
    worker_params = dict(parameters)
    worker_params.update(worker if isinstance(worker, dict) else {})
    if isinstance(worker, dict) and "max_iterations" in worker:
        worker_params["max_iterations"] = int(worker["max_iterations"])
    elif options.default_max_iterations is not None:
        worker_params["max_iterations"] = int(options.default_max_iterations)
    return worker_params


def _should_await_batch_worker_immediately(
    run_state: WorkerRunState,
    options: _WorkerBatchOptions,
) -> bool:
    return not options.parallel and not options.run_in_background and run_state.task is not None


async def _await_parallel_batch_if_needed(
    run_states: List[WorkerRunState],
    options: _WorkerBatchOptions,
) -> None:
    if options.run_in_background or not options.parallel:
        return
    tasks = [state.task for state in run_states if state.task is not None]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _build_batch_result(
    host: _WorkerLaunchHostProtocol,
    run_states: List[WorkerRunState],
    options: _WorkerBatchOptions,
) -> ToolResult:
    data = _build_batch_result_data(run_states, options)
    if options.run_in_background:
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


def _build_batch_result_data(
    run_states: List[WorkerRunState],
    options: _WorkerBatchOptions,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "worker_count": len(run_states),
        "run_in_background": options.run_in_background,
        "parallel": options.parallel,
    }
    orchestration_ids = {state.orchestration_id for state in run_states if state.orchestration_id}
    if len(orchestration_ids) == 1:
        data["orchestration_id"] = next(iter(orchestration_ids))
    return data
