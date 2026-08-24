"""Public action dispatch for the worker agent tool."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, cast

from ...tools.schema import ToolErrorCode, ToolExecutionContext, ToolResult
from ..execution.task_budget import TaskBudgetExceeded
from .worker_state import (
    DEFAULT_WORKER_AWAIT_TIMEOUT_SECONDS,
    MAX_WORKER_MAX_ITERATIONS,
)


class _WorkerValidationBaseProtocol(Protocol):
    async def validate_parameters(
        self,
        parameters: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]: ...


class _WorkerActionHostProtocol(Protocol):
    ACTION_LAUNCH: str
    ACTION_STATUS: str
    ACTION_AWAIT: str
    ACTION_CANCEL: str

    def _normalize_preset(self, preset: str) -> str: ...

    async def _get_worker_status(self, worker_id: str) -> ToolResult: ...

    async def _get_workers_status(self, worker_ids: List[str]) -> ToolResult: ...

    async def _await_worker(self, worker_id: str, timeout_seconds: int) -> ToolResult: ...

    async def _await_workers(self, worker_ids: List[str], timeout_seconds: int) -> ToolResult: ...

    async def _cancel_worker(
        self,
        worker_id: str,
        context: ToolExecutionContext,
    ) -> ToolResult: ...

    async def _cancel_workers(
        self,
        worker_ids: List[str],
        context: ToolExecutionContext,
    ) -> ToolResult: ...

    async def _launch_workers_batch(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult: ...

    async def _launch_worker(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult: ...


class WorkerActionMixin:
    """Validate and dispatch public agent-tool actions."""

    async def validate_parameters(
        self,
        parameters: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        base = cast(_WorkerValidationBaseProtocol, super())
        valid, error = await base.validate_parameters(parameters)
        if not valid:
            return valid, error

        host = cast(_WorkerActionHostProtocol, self)
        action = str(parameters.get("action", host.ACTION_LAUNCH))
        if action not in {
            host.ACTION_LAUNCH,
            host.ACTION_STATUS,
            host.ACTION_AWAIT,
            host.ACTION_CANCEL,
        }:
            return False, f"Unsupported action: {action}"

        worker_ids = parameters.get("worker_ids")
        has_worker_ids = isinstance(worker_ids, list) and len(worker_ids) > 0
        has_worker_id = bool(str(parameters.get("worker_id", "")).strip())
        if isinstance(worker_ids, list) and any(
            not isinstance(item, str) or not item.strip() for item in worker_ids
        ):
            return False, "worker_ids must contain only non-empty strings"
        timeout_seconds = parameters.get("timeout_seconds")
        if isinstance(timeout_seconds, bool):
            return False, "timeout_seconds must be an integer"
        if (
            action in {host.ACTION_STATUS, host.ACTION_AWAIT, host.ACTION_CANCEL}
            and not has_worker_id
            and not has_worker_ids
        ):
            return False, "worker_id or worker_ids is required for status/await/cancel actions"

        if action == host.ACTION_LAUNCH:
            workers = parameters.get("workers")
            if isinstance(workers, list) and workers:
                for idx, worker in enumerate(workers):
                    valid, error = _validate_worker_definition(
                        host,
                        worker,
                        prefix=f"workers[{idx}]",
                        default_max_iterations=parameters.get("max_iterations"),
                    )
                    if not valid:
                        return False, error
            else:
                valid, error = _validate_worker_definition(host, parameters)
                if not valid:
                    return False, error

        return True, None

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        host = cast(_WorkerActionHostProtocol, self)
        action = str(parameters.get("action", host.ACTION_LAUNCH))
        valid, error = await self.validate_parameters(parameters)
        if not valid:
            return ToolResult(
                success=False,
                error=error or "Invalid worker action parameters",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        if action == host.ACTION_STATUS:
            worker_ids = parameters.get("worker_ids")
            if isinstance(worker_ids, list) and worker_ids:
                return await host._get_workers_status(worker_ids)
            return await host._get_worker_status(str(parameters.get("worker_id", "")))
        if action == host.ACTION_AWAIT:
            worker_ids = parameters.get("worker_ids")
            if isinstance(worker_ids, list) and worker_ids:
                return await host._await_workers(
                    worker_ids=worker_ids,
                    timeout_seconds=int(
                        parameters.get("timeout_seconds", DEFAULT_WORKER_AWAIT_TIMEOUT_SECONDS)
                    ),
                )
            return await host._await_worker(
                worker_id=str(parameters.get("worker_id", "")),
                timeout_seconds=int(
                    parameters.get("timeout_seconds", DEFAULT_WORKER_AWAIT_TIMEOUT_SECONDS)
                ),
            )
        if action == host.ACTION_CANCEL:
            worker_ids = parameters.get("worker_ids")
            if isinstance(worker_ids, list) and worker_ids:
                return await host._cancel_workers(worker_ids, context)
            return await host._cancel_worker(
                str(parameters.get("worker_id", "")),
                context,
            )
        try:
            workers = parameters.get("workers")
            if isinstance(workers, list) and workers:
                return await host._launch_workers_batch(parameters, context)
            return await host._launch_worker(parameters, context)
        except TaskBudgetExceeded as exc:
            return ToolResult(
                success=False,
                data={
                    "reason": "task_budget_exceeded",
                    "resource": exc.resource,
                    "limit": exc.limit,
                    "used": exc.used,
                    "requested": exc.requested,
                },
                error=str(exc),
                error_code=ToolErrorCode.POLICY_BLOCKED.value,
            )


def _validate_worker_definition(
    host: _WorkerActionHostProtocol,
    worker: Any,
    *,
    prefix: str = "",
    default_max_iterations: Any = None,
) -> tuple[bool, str | None]:
    label = f"{prefix}." if prefix else ""
    if not isinstance(worker, dict):
        return False, f"{prefix or 'worker'} must be an object"
    raw_preset = worker.get("preset", "default")
    if not isinstance(raw_preset, str) or not host._normalize_preset(raw_preset):
        return False, f"{label}preset is unsupported"
    for field_name in ("description", "prompt"):
        value = worker.get(field_name)
        if not isinstance(value, str) or not value.strip():
            return False, f"{label}{field_name} is required"
    raw_max_iterations = worker.get("max_iterations", default_max_iterations)
    if raw_max_iterations is not None:
        if isinstance(raw_max_iterations, bool) or not isinstance(raw_max_iterations, int):
            return False, f"{label}max_iterations must be an integer"
        if not 1 <= raw_max_iterations <= MAX_WORKER_MAX_ITERATIONS:
            return (
                False,
                f"{label}max_iterations must be between 1 and {MAX_WORKER_MAX_ITERATIONS}",
            )
    raw_retry_count = worker.get("retry_count")
    if raw_retry_count is not None:
        if isinstance(raw_retry_count, bool) or not isinstance(raw_retry_count, int):
            return False, f"{label}retry_count must be an integer"
        if not 0 <= raw_retry_count <= 3:
            return False, f"{label}retry_count must be between 0 and 3"
    return True, None
