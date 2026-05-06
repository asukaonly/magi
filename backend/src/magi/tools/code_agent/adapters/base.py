"""Adapter base contract used by Claude Code and Codex implementations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, Protocol, runtime_checkable

from ..contracts import (
    AdapterName,
    CostInfo,
    DelegateRequest,
    ProbeResult,
    RunEvent,
)


class CancelToken:
    """Cooperative cancellation token (sync; checked between subprocess phases)."""

    __slots__ = ("_cancelled",)

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


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
]
