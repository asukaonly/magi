"""Conversation-owned shell jobs using the shared process-tree runner."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import uuid4

from magi_plugin_sdk.subprocess import DEFAULT_OUTPUT_TAIL_BYTES, BoundedSubprocessResult

from ..schema import ToolExecutionContext, ToolResult


def _owner(context: ToolExecutionContext) -> tuple[str, str, str]:
    user = context.env_vars.get("user_id", "")
    session = context.env_vars.get("session_id", "")
    if session:
        return user, "session", session
    if context.task_id:
        return user, "task", context.task_id
    return user, "agent", context.agent_id


@dataclass
class _ShellJob:
    job_id: str
    owner: tuple[str, str, str]
    shell_tool: str
    command: str
    background_requested: bool
    risk_data: dict[str, str]
    task: asyncio.Task[None] | None = None
    pid: int | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = "starting"
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_total_bytes: int = 0
    stderr_total_bytes: int = 0
    result: ToolResult | None = None
    finished_at: float | None = None

    def output(self, stream: str, chunk: bytes) -> None:
        setattr(self, stream, (getattr(self, stream) + chunk)[-DEFAULT_OUTPUT_TAIL_BYTES:])
        setattr(self, f"{stream}_total_bytes", getattr(self, f"{stream}_total_bytes") + len(chunk))

    def spawned(self, pid: int) -> None:
        self.pid = pid
        self.status = "running"
        self.ready.set()

    def observation(self) -> ToolResult:
        data: dict[str, Any] = {
            "job_id": self.job_id,
            "shell_tool": self.shell_tool,
            "command": self.command,
            "pid": self.pid,
            "status": self.status,
            "background_requested": self.background_requested,
            "return_code": None,
            "command_succeeded": False,
            "timed_out": False,
            **self.risk_data,
        }
        for stream in ("stdout", "stderr"):
            tail = getattr(self, stream)
            total = getattr(self, f"{stream}_total_bytes")
            data.update({
                stream: tail.decode("utf-8", errors="replace"),
                f"{stream}_total_bytes": total,
                f"{stream}_truncated": total > len(tail),
            })
        if self.result is not None:
            return self.result.model_copy(update={"data": {**data, **(self.result.data or {})}})
        data["tool_expansion"] = {"append_tools": ["shell_job"]}
        data["next_action"] = "Use shell_job to inspect, wait for, or stop this job. Do not rerun the command."
        return ToolResult(success=True, data=data)


class ShellJobs:
    """Own live processes and bounded result tails for one native shell tool."""

    def __init__(self, shell_tool: str) -> None:
        self.shell_tool = shell_tool
        self._jobs: dict[str, _ShellJob] = {}

    async def start(
        self,
        *,
        command: str,
        context: ToolExecutionContext,
        background: bool,
        risk_data: dict[str, str],
        wait_seconds: float,
        run: Callable[..., Awaitable[BoundedSubprocessResult]],
        render: Callable[[BoundedSubprocessResult], ToolResult],
    ) -> ToolResult:
        owner = _owner(context)
        # Evict only old terminal receipts; live work is never evicted.
        completed = sorted(
            (job for job in self._jobs.values() if job.owner == owner and job.finished_at is not None),
            key=lambda job: job.finished_at or 0,
        )
        for old in completed[:-63]:
            self._jobs.pop(old.job_id, None)
        job = _ShellJob(uuid4().hex, owner, self.shell_tool, command, background, risk_data)
        self._jobs[job.job_id] = job
        job.task = asyncio.create_task(
            self._run(job, context, run, render), name=f"shell-job:{job.job_id}",
        )
        try:
            if background:
                ready = asyncio.create_task(job.ready.wait())
                try:
                    await asyncio.wait({job.task, ready}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    ready.cancel()
                    await asyncio.gather(ready, return_exceptions=True)
            else:
                await asyncio.wait({job.task}, timeout=min(wait_seconds, 30))
            return job.observation()
        except asyncio.CancelledError:
            await self._stop(job)
            raise

    async def _run(self, job: _ShellJob, context: ToolExecutionContext, run, render) -> None:
        process = asyncio.create_task(run(on_output=job.output, on_spawn=job.spawned))
        cancelled = (
            asyncio.create_task(context.cancellation.wait())
            if context.cancellation is not None else None
        )
        try:
            if cancelled is not None:
                done, _ = await asyncio.wait({process, cancelled}, return_when=asyncio.FIRST_COMPLETED)
                if process not in done:
                    raise asyncio.CancelledError
            result = await process
            job.result = render(result)
            job.status = "completed" if job.result.success else "failed"
        except asyncio.CancelledError:
            process.cancel()
            await asyncio.gather(process, return_exceptions=True)
            job.status = "cancelled"
            job.result = ToolResult(success=True, data={"stopped": True})
        except FileNotFoundError as exc:
            job.status = "failed"
            job.result = ToolResult(
                success=False, error=str(exc), error_code="DIRECTORY_NOT_FOUND",
                metadata={"effect_state": "none"} if job.pid is None else {},
            )
        except Exception as exc:
            job.status = "failed"
            job.result = ToolResult(success=False, error=str(exc), error_code="EXECUTION_ERROR")
        finally:
            if cancelled is not None:
                cancelled.cancel()
                await asyncio.gather(cancelled, return_exceptions=True)
            job.finished_at = time.monotonic()
            job.ready.set()

    async def _stop(self, job: _ShellJob) -> None:
        if job.task is not None and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        if job.finished_at is None:
            job.status = "cancelled"
            job.result = ToolResult(success=True, data={"stopped": True})
            job.finished_at = time.monotonic()
            job.ready.set()

    async def control(self, parameters: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        action = parameters.get("action", "poll")
        if action == "list":
            return ToolResult(success=True, data={"jobs": [
                {key: job.observation().data[key] for key in ("job_id", "shell_tool", "command", "status")}
                for job in self._jobs.values() if job.owner == _owner(context)
            ]})
        job = self._jobs.get(parameters.get("job_id", ""))
        if job is None or job.owner != _owner(context):
            return ToolResult(success=False, error="Shell job not found in this conversation.", error_code="NOT_FOUND")
        try:
            if action == "stop":
                await self._stop(job)
            elif action == "wait" and job.task is not None:
                await asyncio.wait({job.task}, timeout=min(parameters.get("wait_seconds", 30), 30))
            result = job.observation()
            result.data["action"] = action
            return result
        except asyncio.CancelledError:
            await self._stop(job)
            raise

    async def close(self) -> None:
        """Stop live processes before shutdown or user-content deletion."""
        await asyncio.gather(*(self._stop(job) for job in self._jobs.values()))
        self._jobs.clear()

    async def close_scope(self, *, user_id: str | None = None, session_id: str | None = None) -> None:
        """Stop and forget jobs belonging to a deleted user or conversation."""
        jobs = [job for job in self._jobs.values()
                if (user_id is None or job.owner[0] == user_id)
                and (session_id is None or job.owner[1:] == ("session", session_id))]
        await asyncio.gather(*(self._stop(job) for job in jobs))
        for job in jobs:
            self._jobs.pop(job.job_id, None)
