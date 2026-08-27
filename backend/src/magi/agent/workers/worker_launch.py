"""Worker launch lifecycle helpers for the agent tool."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, cast

from ..cancel import EventCancelToken
from ..execution.task_budget import reserve_task_worker_launches
from ...core.logger import get_logger
from ...tools.schema import ToolErrorCode, ToolExecutionContext, ToolResult
from ..background.contracts import BackgroundTaskSpec, BackgroundTaskTriggerSource
from .worker_state import (
    DEFAULT_WORKER_MAX_ITERATIONS,
    MAX_WORKER_MAX_ITERATIONS,
    WorkerRunState,
    optional_string,
)
from .worker_prompting import WorkerPromptLayers
from .child_preset import (
    ChildRunPreset,
    parent_reasoning_policy_from_env,
    parent_reasoning_state_from_env,
    parse_child_preset,
    resolve_child_reasoning_policy,
)

logger = get_logger(__name__)


class _WorkerStartRejected(Exception):
    """Reject one staged worker start without cancelling its caller task."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class _WorkerStartSpec:
    preset: ChildRunPreset
    description: str
    prompt: str
    max_iterations: int
    retry_count: int
    parent_context_summary: str
    turn_id: str | None
    user_id: str
    session_id: str
    parent_task_agent_type: str
    parent_task_agent_id: str
    target_task_agent_type: str
    target_task_agent_id: str
    parent_run_id: str | None
    run_revision: int
    ownership: str
    owner_run_id: str | None
    reasoning_policy: Any
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
    _pending_runs: Dict[str, WorkerRunState]
    _cancelled_run_keys: Dict[tuple[str, str, int], float]
    _background_task_manager: Any

    async def _start_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
        *,
        start_gate: asyncio.Event | None = None,
        defer_commit: bool = False,
    ) -> WorkerRunState | ToolResult: ...

    def _normalize_preset(self, preset: str) -> str: ...

    def _resolve_tools_for_preset(self, preset: str) -> List[str]: ...

    def _build_worker_prompt_layers(
        self,
        *,
        worker_id: str,
        preset: str,
        description: str,
        selected_tools: List[str],
    ) -> WorkerPromptLayers: ...

    async def _run_worker(
        self,
        run_state: WorkerRunState,
        prompt_layers: WorkerPromptLayers,
        selected_tools: List[str],
        max_iterations: int,
        execution_workspace: str,
    ) -> None: ...

    async def _handle_cancelled_error(self, run_state: WorkerRunState) -> None: ...

    async def _emit_worker_cancelled_trace(self, run_state: WorkerRunState) -> None: ...

    async def _emit_worker_terminal_trace(
        self,
        run_state: WorkerRunState,
        status: str,
    ) -> None: ...

    async def _emit_worker_attempt_terminal_trace(
        self,
        run_state: WorkerRunState,
        status: str,
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
        if run_in_background:
            return await self._launch_background_child(parameters, context)
        run_state = await host._start_worker(parameters, context)
        if isinstance(run_state, ToolResult):
            return run_state

        if run_state.task is not None:
            await _await_foreground_worker(host, run_state)
        return host._build_run_result(run_state)

    async def _launch_background_child(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        host = cast(_WorkerLaunchHostProtocol, self)
        manager = host._background_task_manager
        if manager is None:
            return ToolResult(
                success=False,
                error="Background child runtime is unavailable",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )
        spec = _resolve_worker_start_spec(host, parameters, context)
        if isinstance(spec, ToolResult):
            return spec
        selected_tools = host._resolve_tools_for_preset(spec.preset.value)
        prompt_layers = host._build_worker_prompt_layers(
            worker_id="background",
            preset=spec.preset.value,
            description=spec.description,
            selected_tools=selected_tools,
        )
        await reserve_task_worker_launches(1)
        task = await manager.enqueue(
            BackgroundTaskSpec(
                user_id=spec.user_id,
                session_id=spec.session_id,
                origin_turn_id=spec.turn_id or "",
                title=spec.description,
                goal=spec.prompt,
                selected_tools=selected_tools,
                system_prompt=prompt_layers.system_prompt,
                working_context=prompt_layers.working_context,
                ephemeral_context=spec.parent_context_summary or None,
                execution_preset=f"child_{spec.preset.value}",
                reasoning_policy=spec.reasoning_policy.to_dict(),
                parent_run_id=spec.parent_run_id,
                final_response_json_mode=True,
                workspace_path=spec.execution_workspace,
                trigger_source=BackgroundTaskTriggerSource.RULE,
                max_iterations=spec.max_iterations,
                task_budget_root_turn_id=spec.turn_id,
                context_sources=(
                    {
                        "provider": "child_run",
                        "preset": spec.preset.value,
                        "parent_run_id": spec.parent_run_id,
                        "ownership": "background",
                    },
                ),
            )
        )
        return ToolResult(
            success=True,
            data={
                "worker_id": task.task_id,
                "child_run_id": task.task_id,
                "status": task.status.value,
                "preset": spec.preset.value,
                "description": spec.description,
                "run_in_background": True,
                "needs_await": True,
                "ownership": "background",
                "parent_run_id": spec.parent_run_id,
            },
        )

    async def _start_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
        *,
        start_gate: asyncio.Event | None = None,
        defer_commit: bool = False,
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

        selected_tools = host._resolve_tools_for_preset(spec.preset.value)
        run_state.selected_tools = list(selected_tools)
        prompt_layers = host._build_worker_prompt_layers(
            worker_id=run_state.worker_id,
            preset=spec.preset.value,
            description=spec.description,
            selected_tools=selected_tools,
        )

        worker_start_gate = start_gate or asyncio.Event()
        start_trace_attempted = False
        try:
            await _register_pending_worker_run(host, run_state)
            start_trace_attempted = True
            await _emit_worker_start_traces(host, run_state)
            run_state.task = _create_worker_task(
                host,
                run_state,
                prompt_layers=prompt_layers,
                selected_tools=selected_tools,
                max_iterations=spec.max_iterations,
                execution_workspace=spec.execution_workspace,
                start_gate=worker_start_gate,
            )
            if not defer_commit:
                await _commit_worker_runs(host, [run_state])
                if start_gate is None:
                    worker_start_gate.set()
        except _WorkerStartRejected as exc:
            await _rollback_worker_starts(
                host,
                [run_state],
                reason=exc.reason,
                terminalize_traces=start_trace_attempted,
            )
            return _worker_start_rejected_result(exc.reason)
        except BaseException:
            await _rollback_worker_starts(
                host,
                [run_state],
                reason="worker_start_failed",
                terminalize_traces=start_trace_attempted,
            )
            raise
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
        worker_params = _preflight_batch_workers(
            host,
            workers,
            parameters=parameters,
            context=context,
            options=options,
        )
        if isinstance(worker_params, ToolResult):
            return worker_params
        if options.run_in_background:
            return await self._launch_background_batch(worker_params, context)
        run_states = await self._start_batch_workers(
            worker_params,
            context=context,
            options=options,
        )
        if isinstance(run_states, ToolResult):
            return run_states
        await _await_parallel_batch_if_needed(host, run_states, options)
        return _build_batch_result(host, run_states, options)

    async def _launch_background_batch(
        self,
        worker_params: List[Dict[str, Any]],
        context: ToolExecutionContext,
    ) -> ToolResult:
        launched: list[dict[str, Any]] = []
        for parameters in worker_params:
            result = await self._launch_background_child(parameters, context)
            if not result.success:
                host = cast(_WorkerLaunchHostProtocol, self)
                manager = host._background_task_manager
                for child in launched:
                    await manager.cancel(
                        str(child["child_run_id"]),
                        reason="background_child_batch_rollback",
                    )
                return result
            if isinstance(result.data, dict):
                launched.append(dict(result.data))
        return ToolResult(
            success=True,
            data={
                "status": "pending",
                "children": launched,
                "worker_ids": [item["worker_id"] for item in launched],
                "worker_count": len(launched),
                "run_in_background": True,
                "parallel": True,
            },
        )

    async def _start_batch_workers(
        self,
        worker_params: List[Dict[str, Any]],
        *,
        context: ToolExecutionContext,
        options: _WorkerBatchOptions,
    ) -> List[WorkerRunState] | ToolResult:
        host = cast(_WorkerLaunchHostProtocol, self)
        run_states: List[WorkerRunState] = []
        start_gates: List[asyncio.Event] = []
        try:
            for parameters in worker_params:
                start_gate = asyncio.Event()
                run_state = await host._start_worker(
                    parameters,
                    context,
                    start_gate=start_gate,
                    defer_commit=True,
                )
                if isinstance(run_state, ToolResult):
                    await _rollback_worker_starts(
                        host,
                        run_states,
                        reason="batch_worker_start_failed",
                    )
                    return run_state
                run_states.append(run_state)
                start_gates.append(start_gate)
            await _commit_worker_runs(host, run_states)
        except _WorkerStartRejected as exc:
            await _rollback_worker_starts(
                host,
                run_states,
                reason=exc.reason,
            )
            return _worker_start_rejected_result(exc.reason)
        except BaseException:
            await _rollback_worker_starts(
                host,
                run_states,
                reason="batch_worker_start_failed",
            )
            raise

        if options.run_in_background or options.parallel:
            for start_gate in start_gates:
                start_gate.set()
            return run_states

        try:
            for run_state, start_gate in zip(run_states, start_gates):
                start_gate.set()
                await _await_foreground_worker(host, run_state)
        except BaseException:
            await _cancel_worker_tasks(
                host,
                run_states,
                reason="foreground_worker_wait_terminated",
            )
            raise
        return run_states


def _resolve_worker_start_spec(
    host: _WorkerLaunchHostProtocol,
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
) -> _WorkerStartSpec | ToolResult:
    preset = parse_child_preset(parameters.get("preset", ChildRunPreset.DEFAULT.value))
    if preset is None:
        return ToolResult(
            success=False,
            error="Unsupported preset. Expected default, read_only, workspace_write, or review",
            error_code=ToolErrorCode.INVALID_PARAMETERS.value,
        )

    user_id = str(context.env_vars.get("user_id", "unknown"))
    parent_type, parent_id = _resolve_parent_task_agent(context, user_id)
    parent_run_id, run_revision = _resolve_run_identity(context)
    max_iterations = _resolve_max_iterations(parameters.get("max_iterations"))
    if isinstance(max_iterations, ToolResult):
        return max_iterations
    retry_count = _resolve_retry_count(parameters.get("retry_count"))
    if isinstance(retry_count, ToolResult):
        return retry_count
    description = parameters.get("description")
    prompt = parameters.get("prompt")
    if not isinstance(description, str) or not description.strip():
        return _invalid_start_spec("description must be a non-empty string")
    if not isinstance(prompt, str) or not prompt.strip():
        return _invalid_start_spec("prompt must be a non-empty string")

    return _WorkerStartSpec(
        preset=preset,
        description=description.strip(),
        prompt=prompt.strip(),
        max_iterations=max_iterations,
        retry_count=retry_count,
        parent_context_summary=str(parameters.get("parent_context_summary", "")).strip(),
        turn_id=optional_string(context.env_vars.get("turn_id")),
        user_id=user_id,
        session_id=str(context.env_vars.get("session_id", "")),
        parent_task_agent_type=parent_type,
        parent_task_agent_id=parent_id,
        target_task_agent_type=parent_type,
        target_task_agent_id=parent_id,
        parent_run_id=parent_run_id,
        run_revision=run_revision,
        ownership=("background" if bool(parameters.get("run_in_background", False)) else "parent"),
        owner_run_id=(
            None
            if bool(parameters.get("run_in_background", False))
            else parent_run_id
        ),
        reasoning_policy=resolve_child_reasoning_policy(
            preset=preset,
            parent_policy=parent_reasoning_policy_from_env(context.env_vars),
            parent_state=parent_reasoning_state_from_env(context.env_vars),
        ),
        user_message_generation=_resolve_user_message_generation(context),
        execution_workspace=context.workspace,
    )


def _resolve_parent_task_agent(
    context: ToolExecutionContext,
    user_id: str,
) -> tuple[str, str]:
    parent_type = str(
        context.env_vars.get("parent_task_agent_type")
        or context.env_vars.get("target_task_agent_type")
        or "chat"
    )
    parent_id = str(
        context.env_vars.get("parent_task_agent_id")
        or context.env_vars.get("target_task_agent_id")
        or user_id
        or "default"
    )
    return parent_type, parent_id


def _resolve_run_identity(
    context: ToolExecutionContext,
) -> tuple[str | None, int]:
    run_id = str(context.env_vars.get("run_id") or "").strip()
    try:
        run_revision = int(
            context.env_vars.get("run_revision") or 0
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
        child_run_id=f"child_{uuid.uuid4().hex}",
        preset=spec.preset,
        description=spec.description,
        prompt=spec.prompt,
        parent_task_agent_type=spec.parent_task_agent_type,
        parent_task_agent_id=spec.parent_task_agent_id,
        target_task_agent_type=spec.target_task_agent_type,
        target_task_agent_id=spec.target_task_agent_id,
        user_id=spec.user_id,
        session_id=spec.session_id,
        turn_id=spec.turn_id,
        parent_run_id=spec.parent_run_id,
        run_revision=spec.run_revision,
        ownership=spec.ownership,
        owner_run_id=spec.owner_run_id,
        reasoning_policy=spec.reasoning_policy,
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
    prompt_layers: WorkerPromptLayers,
    selected_tools: List[str],
    max_iterations: int,
    execution_workspace: str,
    start_gate: asyncio.Event | None,
) -> asyncio.Task[None]:
    task = asyncio.create_task(
        _run_worker_after_start_gate(
            host,
            run_state=run_state,
            prompt_layers=prompt_layers,
            selected_tools=selected_tools,
            max_iterations=max_iterations,
            execution_workspace=execution_workspace,
            start_gate=start_gate,
        ),
        name=f"agent-tool-{run_state.worker_id}",
    )
    task.add_done_callback(
        lambda completed: _schedule_cancelled_worker_terminalization(
            host,
            run_state,
            completed,
        )
    )
    return task


async def _run_worker_after_start_gate(
    host: _WorkerLaunchHostProtocol,
    *,
    run_state: WorkerRunState,
    prompt_layers: WorkerPromptLayers,
    selected_tools: List[str],
    max_iterations: int,
    execution_workspace: str,
    start_gate: asyncio.Event | None,
) -> None:
    if start_gate is not None:
        try:
            await start_gate.wait()
        except asyncio.CancelledError:
            if run_state.startup_committed:
                await _best_effort_terminalize_cancelled_worker(host, run_state)
            else:
                _mark_cancelled_worker_state(run_state)
            return
    if run_state.cancel_token is not None and await run_state.cancel_token.is_cancelled():
        if run_state.startup_committed:
            await _best_effort_terminalize_cancelled_worker(host, run_state)
        else:
            _mark_cancelled_worker_state(run_state)
        return
    await host._run_worker(
        run_state=run_state,
        prompt_layers=prompt_layers,
        selected_tools=selected_tools,
        max_iterations=max_iterations,
        execution_workspace=execution_workspace,
    )


def _schedule_cancelled_worker_terminalization(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
    task: asyncio.Task[None],
) -> None:
    if not task.cancelled() or run_state.status != "running" or not run_state.startup_committed:
        return
    terminal_task = asyncio.create_task(
        _best_effort_terminalize_cancelled_worker(host, run_state),
        name=f"agent-tool-terminalize-{run_state.worker_id}",
    )
    terminal_task.add_done_callback(_consume_terminalization_result)


def _consume_terminalization_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        return


async def _commit_worker_runs(
    host: _WorkerLaunchHostProtocol,
    run_states: List[WorkerRunState],
) -> None:
    async with host._lock:
        previous_runs = dict(host._runs)
        previous_pending_runs = dict(host._pending_runs)
        try:
            for run_state in run_states:
                run_key = _worker_run_key(run_state)
                rejection_reason = _worker_start_rejection_reason(
                    host,
                    run_state,
                    run_key=run_key,
                )
                if rejection_reason is not None:
                    raise _WorkerStartRejected(rejection_reason)
            for run_state in run_states:
                host._pending_runs.pop(run_state.worker_id, None)
                host._runs[run_state.worker_id] = run_state
            host._trim_history(max_runs=100)
            if run_states:
                await reserve_task_worker_launches(len(run_states))
            for run_state in run_states:
                run_state.startup_committed = True
        except BaseException:
            host._runs.clear()
            host._runs.update(previous_runs)
            host._pending_runs.clear()
            host._pending_runs.update(previous_pending_runs)
            for run_state in run_states:
                run_state.startup_committed = False
            raise


async def _register_pending_worker_run(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
) -> None:
    async with host._lock:
        if _worker_run_key(run_state) in host._cancelled_run_keys:
            if run_state.cancel_token is not None:
                run_state.cancel_token.cancel("run_cancelled_before_worker_start")
            raise _WorkerStartRejected("run_cancelled_before_worker_start")
        host._pending_runs[run_state.worker_id] = run_state


def _worker_start_rejection_reason(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
    *,
    run_key: tuple[str, str, int],
) -> str | None:
    if host._pending_runs.get(run_state.worker_id) is not run_state:
        return "worker_start_no_longer_pending"
    if run_key in host._cancelled_run_keys:
        return "run_cancelled_before_worker_start"
    if run_state.cancel_token is not None and run_state.cancel_token.reason is not None:
        return str(run_state.cancel_token.reason)
    if run_state.status != "running":
        return "worker_start_no_longer_running"
    return None


def _worker_start_rejected_result(reason: str) -> ToolResult:
    return ToolResult(
        success=False,
        data={"reason": reason},
        error="Worker startup was cancelled before commit",
        error_code=ToolErrorCode.CANCELLED.value,
    )


def _worker_run_key(run_state: WorkerRunState) -> tuple[str, str, int]:
    return (
        run_state.session_id,
        run_state.parent_run_id or "",
        int(run_state.run_revision),
    )


async def _emit_worker_start_traces(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
) -> None:
    await host._emit_worker_dispatch_trace(run_state)
    await host._emit_worker_attempt_started_trace(run_state)
    await host._emit_worker_started_trace(run_state)


async def _await_foreground_worker(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
) -> None:
    task = run_state.task
    if task is None:
        return
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await _cancel_worker_tasks(
            host,
            [run_state],
            reason="foreground_worker_wait_cancelled",
        )
        raise


async def _cancel_worker_tasks(
    host: _WorkerLaunchHostProtocol,
    run_states: List[WorkerRunState],
    *,
    reason: str,
) -> None:
    await _request_worker_task_cancellation(run_states, reason=reason)
    for run_state in run_states:
        await _best_effort_terminalize_cancelled_worker(host, run_state)


async def _request_worker_task_cancellation(
    run_states: List[WorkerRunState],
    *,
    reason: str,
) -> None:
    tasks: List[asyncio.Task[None]] = []
    for run_state in run_states:
        if run_state.cancel_token is not None:
            run_state.cancel_token.cancel(reason)
        task = run_state.task
        if task is None or task.done():
            continue
        task.cancel()
        tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _best_effort_terminalize_cancelled_worker(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
) -> None:
    if not run_state.startup_committed:
        _mark_cancelled_worker_state(run_state)
        return
    if run_state.status != "running":
        return
    try:
        await host._handle_cancelled_error(run_state)
    except asyncio.CancelledError:
        logger.warning(
            "Worker cancellation lifecycle was interrupted | worker_id=%s",
            run_state.worker_id,
        )
    except Exception as exc:
        logger.warning(
            "Worker cancellation lifecycle failed | worker_id=%s error_type=%s",
            run_state.worker_id,
            type(exc).__name__,
        )


async def _rollback_worker_starts(
    host: _WorkerLaunchHostProtocol,
    run_states: List[WorkerRunState],
    *,
    reason: str,
    terminalize_traces: bool = True,
) -> None:
    try:
        for run_state in run_states:
            _mark_cancelled_worker_state(run_state)
        await _request_worker_task_cancellation(run_states, reason=reason)
        if terminalize_traces:
            for run_state in run_states:
                await _best_effort_terminalize_staged_worker(host, run_state)
    except asyncio.CancelledError:
        logger.warning("Worker startup rollback cancellation was interrupted")
    except Exception as exc:
        logger.warning(
            "Worker startup rollback lifecycle failed | error_type=%s",
            type(exc).__name__,
        )
    try:
        async with host._lock:
            for run_state in run_states:
                if host._runs.get(run_state.worker_id) is run_state:
                    host._runs.pop(run_state.worker_id, None)
                if host._pending_runs.get(run_state.worker_id) is run_state:
                    host._pending_runs.pop(run_state.worker_id, None)
    except asyncio.CancelledError:
        logger.warning("Worker startup rollback unregister was interrupted")
    except Exception as exc:
        logger.warning(
            "Worker startup rollback unregister failed | error_type=%s",
            type(exc).__name__,
        )


async def _best_effort_terminalize_staged_worker(
    host: _WorkerLaunchHostProtocol,
    run_state: WorkerRunState,
) -> None:
    terminalizers = (
        ("worker", host._emit_worker_terminal_trace),
        ("worker_attempt", host._emit_worker_attempt_terminal_trace),
    )
    for span_name, terminalize in terminalizers:
        try:
            await terminalize(run_state, "cancelled")
        except asyncio.CancelledError:
            logger.warning(
                "Staged worker trace terminalization was interrupted | worker_id=%s span=%s",
                run_state.worker_id,
                span_name,
            )
        except Exception as exc:
            logger.warning(
                "Staged worker trace terminalization failed | worker_id=%s span=%s error_type=%s",
                run_state.worker_id,
                span_name,
                type(exc).__name__,
            )


def _mark_cancelled_worker_state(run_state: WorkerRunState) -> None:
    run_state.status = "cancelled"
    run_state.error = "Worker cancelled before startup completed"
    run_state.failure_reason = "CANCELLED"
    run_state.updated_at = time.time()
    run_state.completed_at = run_state.updated_at


def _validated_batch_workers(parameters: Dict[str, Any]) -> List[Any] | ToolResult:
    workers = parameters.get("workers")
    if isinstance(workers, list) and workers:
        return workers
    return ToolResult(
        success=False,
        error="workers must be a non-empty array",
        error_code=ToolErrorCode.INVALID_PARAMETERS.value,
    )


def _preflight_batch_workers(
    host: _WorkerLaunchHostProtocol,
    workers: List[Any],
    *,
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
    options: _WorkerBatchOptions,
) -> List[Dict[str, Any]] | ToolResult:
    prepared: List[Dict[str, Any]] = []
    for index, worker in enumerate(workers):
        if not isinstance(worker, dict):
            return _invalid_start_spec(f"workers[{index}] must be an object")
        worker_params = _build_batch_worker_params(worker, parameters, options)
        resolved = _resolve_worker_start_spec(host, worker_params, context)
        if isinstance(resolved, ToolResult):
            return _invalid_start_spec(f"workers[{index}]: {resolved.error}")
        prepared.append(worker_params)
    return prepared


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
    worker_params.update(worker)
    if isinstance(worker, dict) and "max_iterations" in worker:
        worker_params["max_iterations"] = worker["max_iterations"]
    elif options.default_max_iterations is not None:
        worker_params["max_iterations"] = options.default_max_iterations
    return worker_params


def _resolve_max_iterations(value: Any) -> int | ToolResult:
    if value is None:
        return DEFAULT_WORKER_MAX_ITERATIONS
    if isinstance(value, bool) or not isinstance(value, int):
        return _invalid_start_spec("max_iterations must be an integer")
    if not 1 <= value <= MAX_WORKER_MAX_ITERATIONS:
        return _invalid_start_spec(
            f"max_iterations must be between 1 and {MAX_WORKER_MAX_ITERATIONS}"
        )
    return value


def _resolve_retry_count(value: Any) -> int | ToolResult:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        return _invalid_start_spec("retry_count must be an integer")
    if not 0 <= value <= 3:
        return _invalid_start_spec("retry_count must be between 0 and 3")
    return value


def _invalid_start_spec(message: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=message,
        error_code=ToolErrorCode.INVALID_PARAMETERS.value,
    )


async def _await_parallel_batch_if_needed(
    host: _WorkerLaunchHostProtocol,
    run_states: List[WorkerRunState],
    options: _WorkerBatchOptions,
) -> None:
    if options.run_in_background or not options.parallel:
        return
    tasks = [state.task for state in run_states if state.task is not None]
    if tasks:
        try:
            await asyncio.gather(
                *(asyncio.shield(task) for task in tasks),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            await _cancel_worker_tasks(
                host,
                run_states,
                reason="foreground_worker_wait_cancelled",
            )
            raise


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
    return data
