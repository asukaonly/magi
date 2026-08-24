"""Worker run status, await, and serialization helpers."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Protocol, cast

from ...tools.schema import ToolErrorCode, ToolExecutionContext, ToolResult
from .worker_state import WorkerRunState


class _WorkerStatusHostProtocol(Protocol):
    _lock: asyncio.Lock
    _runs: Dict[str, WorkerRunState]
    _background_task_manager: Any


class WorkerStatusMixin:
    """Resolve worker status, await running tasks, and serialize run state."""

    async def _get_worker_status(self, worker_id: str) -> ToolResult:
        host = cast(_WorkerStatusHostProtocol, self)
        async with host._lock:
            run_state = host._runs.get(worker_id)
        if run_state is None:
            return await _background_status(host, worker_id)
        await self._refresh_run_state(run_state)
        return ToolResult(success=True, data=self._serialize_run_state(run_state))

    async def _get_workers_status(self, worker_ids: List[str]) -> ToolResult:
        workers = []
        missing_ids = []
        for worker_id in worker_ids:
            result = await self._get_worker_status(worker_id)
            if not result.success or not isinstance(result.data, dict):
                missing_ids.append(worker_id)
                continue
            workers.append(result.data)

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
            return await _await_background(host, worker_id, timeout_seconds)

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
        results = await asyncio.gather(
            *(self._await_worker(worker_id, timeout_seconds) for worker_id in worker_ids)
        )
        missing_ids = [
            worker_id
            for worker_id, result in zip(worker_ids, results)
            if result.error_code == ToolErrorCode.TOOL_NOT_FOUND.value
        ]
        if missing_ids:
            return ToolResult(
                success=False,
                error=f"Some workers not found: {', '.join(missing_ids)}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
                data={"missing_worker_ids": missing_ids},
            )

        return ToolResult(
            success=all(result.success for result in results),
            data={
                "children": [result.data for result in results if result.data is not None],
            },
            error=(None if all(result.success for result in results) else "Some child runs failed"),
            error_code=(
                None
                if all(result.success for result in results)
                else ToolErrorCode.EXECUTION_ERROR.value
            ),
        )

    async def _cancel_worker(
        self,
        worker_id: str,
        context: ToolExecutionContext,
    ) -> ToolResult:
        host = cast(_WorkerStatusHostProtocol, self)
        async with host._lock:
            run_state = host._runs.get(worker_id)
        if run_state is None:
            background = await _background_task(host, worker_id)
            if background is not None:
                return ToolResult(
                    success=False,
                    data=_serialize_background_child(background),
                    error="Child run ownership has transferred to the background runtime",
                    error_code=ToolErrorCode.POLICY_BLOCKED.value,
                )
            return ToolResult(
                success=False,
                error=f"Child run not found: {worker_id}",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )
        ownership_error = _child_cancel_ownership_error(run_state, context)
        if ownership_error is not None:
            return ToolResult(
                success=False,
                data=self._serialize_run_state(run_state),
                error=ownership_error,
                error_code=ToolErrorCode.POLICY_BLOCKED.value,
            )
        if run_state.status != "running":
            return ToolResult(success=True, data=self._serialize_run_state(run_state))
        if run_state.cancel_token is not None:
            run_state.cancel_token.cancel("targeted_child_cancel")
        task = run_state.task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await self._refresh_run_state(run_state)
        return ToolResult(success=True, data=self._serialize_run_state(run_state))

    async def _cancel_workers(
        self,
        worker_ids: List[str],
        context: ToolExecutionContext,
    ) -> ToolResult:
        results = [await self._cancel_worker(worker_id, context) for worker_id in worker_ids]
        return ToolResult(
            success=all(result.success for result in results),
            data={
                "children": [result.data for result in results if result.data is not None],
            },
            error=(
                None
                if all(result.success for result in results)
                else "One or more child runs could not be cancelled"
            ),
            error_code=(
                None
                if all(result.success for result in results)
                else ToolErrorCode.POLICY_BLOCKED.value
            ),
        )

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
            "child_run_id": run_state.child_run_id,
            "status": run_state.status,
            "preset": run_state.preset.value,
            "parent_run_id": run_state.parent_run_id,
            "ownership": run_state.ownership,
            "description": run_state.description,
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
            "evidence": _child_evidence(run_state),
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


def _child_cancel_ownership_error(
    run_state: WorkerRunState,
    context: ToolExecutionContext,
) -> str | None:
    caller_session_id = str(context.env_vars.get("session_id") or "").strip()
    caller_run_id = str(context.env_vars.get("run_id") or "").strip()
    if not caller_session_id or caller_session_id != run_state.session_id:
        return "Child run belongs to another session"
    if run_state.ownership != "parent":
        return "Child run ownership has transferred to the background runtime"
    if not caller_run_id or caller_run_id != str(run_state.owner_run_id or ""):
        return "Child run belongs to another parent run"
    return None


def _child_evidence(run_state: WorkerRunState) -> dict[str, Any] | None:
    if run_state.status not in {"completed", "failed", "cancelled"}:
        return None
    return {
        "kind": "child_run",
        "evidence_id": f"child:{run_state.child_run_id}",
        "child_run_id": run_state.child_run_id,
        "status": run_state.status,
        "preset": run_state.preset.value,
        "result": run_state.result,
        "failure_reason": run_state.failure_reason,
    }


async def _background_task(
    host: _WorkerStatusHostProtocol,
    child_run_id: str,
) -> Any | None:
    manager = host._background_task_manager
    if manager is None:
        return None
    return await manager.get_task(child_run_id)


async def _background_status(
    host: _WorkerStatusHostProtocol,
    child_run_id: str,
) -> ToolResult:
    task = await _background_task(host, child_run_id)
    if task is None:
        return ToolResult(
            success=False,
            error=f"Child run not found: {child_run_id}",
            error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
        )
    return ToolResult(success=True, data=_serialize_background_child(task))


async def _await_background(
    host: _WorkerStatusHostProtocol,
    child_run_id: str,
    timeout_seconds: int,
) -> ToolResult:
    manager = host._background_task_manager
    if manager is None:
        return await _background_status(host, child_run_id)
    task = await manager.await_terminal(
        child_run_id,
        timeout_seconds=float(timeout_seconds),
    )
    if task is None:
        return ToolResult(
            success=False,
            error=f"Child run not found: {child_run_id}",
            error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
        )
    data = _serialize_background_child(task)
    if not task.status.is_terminal:
        return ToolResult(
            success=False,
            data=data,
            error=f"Waiting for child run timed out after {timeout_seconds}s",
            error_code=ToolErrorCode.TIMEOUT.value,
        )
    success = task.status.value == "succeeded"
    return ToolResult(
        success=success,
        data=data,
        error=None if success else task.error or task.cancel_reason or "Child run failed",
        error_code=None if success else ToolErrorCode.EXECUTION_ERROR.value,
    )


def _serialize_background_child(task: Any) -> dict[str, Any]:
    status_map = {
        "pending": "running",
        "running": "running",
        "cancelling": "running",
        "suspended_waiting_user": "running",
        "succeeded": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    status = status_map.get(task.status.value, task.status.value)
    preset = str(task.spec.execution_preset or "child_default").removeprefix("child_")
    evidence = None
    if task.status.is_terminal:
        evidence = {
            "kind": "child_run",
            "evidence_id": f"child:{task.task_id}",
            "child_run_id": task.task_id,
            "status": status,
            "preset": preset,
            "result": task.result_payload,
            "failure_reason": task.error or task.cancel_reason,
        }
    return {
        "worker_id": task.task_id,
        "child_run_id": task.task_id,
        "status": status,
        "preset": preset,
        "parent_run_id": task.spec.parent_run_id,
        "ownership": "background",
        "description": task.spec.title,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.finished_at,
        "result": task.result_payload,
        "result_preview": task.summary,
        "error": task.error,
        "failure_reason": task.cancel_reason,
        "retry_count": task.attempt_index,
        "evidence": evidence,
    }
