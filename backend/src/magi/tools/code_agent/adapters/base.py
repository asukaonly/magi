"""Adapter base contract used by Claude Code and Codex implementations."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol, TypeVar, runtime_checkable

from ..contracts import (
    AdapterName,
    CostInfo,
    DelegateRequest,
    ProbeResult,
    RunEvent,
)


class CancelToken:
    """Thread-safe cooperative cancellation observed by adapter event loops."""

    __slots__ = ("_cancelled", "_reason")

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str | None:
        return self._reason

    def cancel(self, reason: str = "cancelled") -> None:
        if self._cancelled:
            return
        self._reason = str(reason or "cancelled")
        self._cancelled = True

    async def wait(self) -> None:
        """Wait without relying on cross-thread asyncio.Event mutation."""

        while not self._cancelled:
            await asyncio.sleep(0.02)


@dataclass(frozen=True)
class AdapterRunOutcome:
    """Adapter-internal outcome handed back to the service.

    The service merges this with diff collection + result file writing to
    produce the public ``DelegateResult``.
    """

    exit_code: int
    summary: Optional[str]
    cost: Optional[CostInfo]
    error: Optional[str]
    cancelled: bool = False


_T = TypeVar("_T")


async def wait_for_run_or_cancel(
    run: Awaitable[_T],
    *,
    cancel_token: CancelToken,
    terminate: Callable[[], Awaitable[None]],
) -> tuple[_T | None, bool]:
    """Race one adapter run against cancellation and always reap on abort."""

    run_task = asyncio.ensure_future(run)
    cancel_task = asyncio.create_task(
        cancel_token.wait(),
        name="code-agent-cancel-wait",
    )

    async def terminate_and_drain() -> None:
        try:
            await terminate()
        finally:
            if not run_task.done():
                run_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await run_task

    try:
        done, _ = await asyncio.wait(
            {run_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if run_task in done:
            return await run_task, False

        await terminate_and_drain()
        return None, True
    except BaseException:
        await terminate_and_drain()
        raise
    finally:
        if not cancel_task.done():
            cancel_task.cancel()
        with suppress(asyncio.CancelledError):
            await cancel_task


def render_constraints(req: DelegateRequest) -> str:
    parts: list[str] = []
    if req.constraints.forbid_git_commit:
        parts.append("Do not run git commit.")
    if req.constraints.forbid_git_push:
        parts.append("Do not run git push.")
    if req.constraints.forbid_paths:
        parts.append(
            "Do not read or modify these paths: "
            + ", ".join(req.constraints.forbid_paths)
            + "."
        )
    return " ".join(parts)


async def terminate_process(
    process: asyncio.subprocess.Process,
    *,
    managed: Any = None,
) -> None:
    """Reap a managed or direct child, escalating termination when needed."""
    if process.returncode is not None:
        if managed is not None:
            await managed.wait()
        return
    if managed is not None:
        try:
            await managed.shutdown(
                sigterm_grace_seconds=1.0,
                sigkill_grace_seconds=1.0,
            )
        except Exception:
            pass
        if process.returncode is not None:
            await managed.wait()
            return
    try:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=2)
    except ProcessLookupError:
        await process.wait()


def persist_log(path: Path, chunks: list[bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        for chunk in chunks:
            f.write(chunk)


def format_stderr_tail(chunks: list[bytes], max_chars: int = 200) -> str:
    if not chunks:
        return ""
    text = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    last = text.splitlines()[-1].strip()
    if len(last) > max_chars:
        last = last[:max_chars] + "…"
    return last


OnEvent = Callable[[RunEvent], Awaitable[None]]


@runtime_checkable
class CodeAgentAdapter(Protocol):
    """Run an external coding CLI for one ``DelegateRequest``."""

    name: AdapterName
    display_name: str

    @classmethod
    async def detect(cls) -> ProbeResult: ...

    async def run(
        self,
        req: DelegateRequest,
        *,
        cwd: Path,
        bundle_dir: Path,
        stdout_path: Path,
        stderr_path: Path,
        on_event: OnEvent,
        cancel_token: CancelToken,
        binary_path: str,
    ) -> AdapterRunOutcome: ...


__all__ = [
    "AdapterRunOutcome",
    "CancelToken",
    "CodeAgentAdapter",
    "OnEvent",
    "wait_for_run_or_cancel",
    "render_constraints",
    "terminate_process",
    "persist_log",
    "format_stderr_tail",
]
