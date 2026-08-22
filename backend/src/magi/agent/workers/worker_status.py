"""Worker run status, await, and serialization helpers."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Protocol, cast

from ...tools.schema import ToolErrorCode, ToolResult
from .worker_state import WorkerRunState


class _WorkerStatusHostProtocol(Protocol):
    _lock: asyncio.Lock
    _runs: Dict[str, WorkerRunState]


class WorkerStatusMixin:
    """Resolve worker status, await running tasks, and serialize run state."""

    async def _get_worker_status(self, worker_id: str) -> ToolResult:
        host = cast(_WorkerStatusHostProtocol, self)
        async with host._lock:
            run_state = host._runs.get(worker_id)
        if run_state is None:
            return ToolResult(
                success=False,
                error=f"Worker not found: {worker_id}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )
        await self._refresh_run_state(run_state)
        return ToolResult(success=True, data=self._serialize_run_state(run_state))

    async def _get_workers_status(self, worker_ids: List[str]) -> ToolResult:
        host = cast(_WorkerStatusHostProtocol, self)
        workers = []
        missing_ids = []
        for worker_id in worker_ids:
            async with host._lock:
                run_state = host._runs.get(worker_id)
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
            error=(None if success else f"Some workers not found: {', '.join(missing_ids)}"),
            error_code=None if success else ToolErrorCode.TOOL_NOT_FOUND.value,
        )

    async def _await_worker(self, worker_id: str, timeout_seconds: int) -> ToolResult:
        host = cast(_WorkerStatusHostProtocol, self)
        async with host._lock:
            run_state = host._runs.get(worker_id)
        if run_state is None:
            return ToolResult(
                success=False,
                error=f"Worker not found: {worker_id}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )

        if run_state.task is not None and not run_state.task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(run_state.task), timeout=float(timeout_seconds)
                )
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
        host = cast(_WorkerStatusHostProtocol, self)
        run_states, missing_ids = await _resolve_run_states(host, worker_ids)
        if missing_ids:
            return ToolResult(
                success=False,
                error=f"Some workers not found: {', '.join(missing_ids)}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
                data={"missing_worker_ids": missing_ids},
            )

        timeout_result = await self._await_pending_worker_tasks(
            run_states,
            timeout_seconds,
        )
        if timeout_result is not None:
            return timeout_result

        for state in run_states:
            await self._refresh_run_state(state)

        return self._build_workers_result(run_states)

    async def _await_pending_worker_tasks(
        self,
        run_states: List[WorkerRunState],
        timeout_seconds: int,
    ) -> ToolResult | None:
        pending_tasks = _pending_worker_tasks(run_states)
        if not pending_tasks:
            return None
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(asyncio.shield(task) for task in pending_tasks),
                    return_exceptions=True,
                ),
                timeout=float(timeout_seconds),
            )
            return None
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Waiting for workers timed out after {timeout_seconds}s",
                error_code=ToolErrorCode.TIMEOUT.value,
                data={"workers": [self._serialize_run_state(state) for state in run_states]},
            )

    def _build_workers_result(self, run_states: List[WorkerRunState]) -> ToolResult:
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
        if task.cancelled():
            _mark_cancelled_run_state(run_state)
            return
        try:
            task.result()
        except asyncio.CancelledError:
            _mark_cancelled_run_state(run_state)
        except Exception as exc:
            run_state.status = "failed"
            run_state.error = str(exc)
            run_state.updated_at = time.time()
            run_state.completed_at = run_state.updated_at

    def _build_run_result(self, run_state: WorkerRunState) -> ToolResult:
        success = run_state.status == "completed"
        error_code = (
            ToolErrorCode.CANCELLED.value
            if run_state.status == "cancelled"
            else ToolErrorCode.EXECUTION_ERROR.value
        )
        return ToolResult(
            success=success,
            data=self._serialize_run_state(run_state),
            error=None if success else run_state.error or "Worker execution failed",
            error_code=None if success else error_code,
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

    def _trim_history(self, max_runs: int) -> None:
        host = cast(_WorkerStatusHostProtocol, self)
        if len(host._runs) <= max_runs:
            return
        sorted_runs = sorted(host._runs.values(), key=lambda item: item.created_at)
        to_remove = len(sorted_runs) - max_runs
        for run_state in sorted_runs[:to_remove]:
            if run_state.status == "running":
                continue
            host._runs.pop(run_state.worker_id, None)

    def _compact_value(self, value: Any, limit: int = 500) -> str:
        text = str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + "...(truncated)"


async def _resolve_run_states(
    host: _WorkerStatusHostProtocol,
    worker_ids: List[str],
) -> tuple[List[WorkerRunState], List[str]]:
    run_states: List[WorkerRunState] = []
    missing_ids: List[str] = []
    for worker_id in worker_ids:
        async with host._lock:
            run_state = host._runs.get(worker_id)
        if run_state is None:
            missing_ids.append(worker_id)
            continue
        run_states.append(run_state)
    return run_states, missing_ids


def _pending_worker_tasks(run_states: List[WorkerRunState]) -> List[Any]:
    return [state.task for state in run_states if state.task is not None and not state.task.done()]


def _mark_cancelled_run_state(run_state: WorkerRunState) -> None:
    run_state.status = "cancelled"
    run_state.error = "Worker cancelled"
    run_state.failure_reason = "CANCELLED"
    run_state.updated_at = time.time()
    run_state.completed_at = run_state.updated_at
