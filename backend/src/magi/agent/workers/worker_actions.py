"""Public action dispatch for the worker agent tool."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, cast

from ...tools.schema import ToolExecutionContext, ToolResult


class _WorkerValidationBaseProtocol(Protocol):
    async def validate_parameters(
        self,
        parameters: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]: ...


class _WorkerActionHostProtocol(Protocol):
    ACTION_LAUNCH: str
    ACTION_STATUS: str
    ACTION_AWAIT: str

    async def _get_worker_status(self, worker_id: str) -> ToolResult: ...

    async def _get_workers_status(self, worker_ids: List[str]) -> ToolResult: ...

    async def _await_worker(self, worker_id: str, timeout_seconds: int) -> ToolResult: ...

    async def _await_workers(self, worker_ids: List[str], timeout_seconds: int) -> ToolResult: ...

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
        if action not in {host.ACTION_LAUNCH, host.ACTION_STATUS, host.ACTION_AWAIT}:
            return False, f"Unsupported action: {action}"

        worker_ids = parameters.get("worker_ids")
        has_worker_ids = isinstance(worker_ids, list) and len(worker_ids) > 0
        has_worker_id = bool(str(parameters.get("worker_id", "")).strip())
        if (
            action in {host.ACTION_STATUS, host.ACTION_AWAIT}
            and not has_worker_id
            and not has_worker_ids
        ):
            return False, "worker_id or worker_ids is required for status/await actions"

        if action == host.ACTION_LAUNCH:
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
        host = cast(_WorkerActionHostProtocol, self)
        action = str(parameters.get("action", host.ACTION_LAUNCH))
        if action == host.ACTION_STATUS:
            worker_ids = parameters.get("worker_ids")
            if isinstance(worker_ids, list) and worker_ids:
                return await host._get_workers_status(
                    [str(item) for item in worker_ids if str(item).strip()]
                )
            return await host._get_worker_status(str(parameters.get("worker_id", "")))
        if action == host.ACTION_AWAIT:
            worker_ids = parameters.get("worker_ids")
            if isinstance(worker_ids, list) and worker_ids:
                return await host._await_workers(
                    worker_ids=[str(item) for item in worker_ids if str(item).strip()],
                    timeout_seconds=int(parameters.get("timeout_seconds", 300)),
                )
            return await host._await_worker(
                worker_id=str(parameters.get("worker_id", "")),
                timeout_seconds=int(parameters.get("timeout_seconds", 300)),
            )
        workers = parameters.get("workers")
        if isinstance(workers, list) and workers:
            return await host._launch_workers_batch(parameters, context)
        return await host._launch_worker(parameters, context)
