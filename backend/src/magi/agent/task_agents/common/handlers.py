"""Common execution handlers shared by task agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ....agent.cancel import CancelToken
from .contracts import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
)


def _serialize_ux_plan(intent: ExecutionRequest | object) -> dict | None:
    plan = getattr(getattr(intent, "intent", intent), "ux_plan", None)
    if plan is None:
        return None
    to_dict = getattr(plan, "to_dict", None)
    return to_dict() if callable(to_dict) else plan


class ExecutionHandler(Protocol):
    """Protocol for typed execution handlers."""

    mode: ExecutionMode

    def supports(self, mode: ExecutionMode) -> bool:
        """Return whether this handler supports the execution mode."""

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        """Prepare request payload for execution."""

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute a prepared request."""


class ExecutionHandlerRegistry:
    """Registry for execution handlers keyed by execution mode."""

    def __init__(self) -> None:
        self._handlers: dict[ExecutionMode, ExecutionHandler] = {}

    def register(self, handler: ExecutionHandler) -> None:
        self._handlers[handler.mode] = handler

    def get(self, mode: ExecutionMode) -> ExecutionHandler:
        handler = self._handlers.get(mode)
        if handler is None:
            raise KeyError(f"No execution handler registered for mode={mode}")
        return handler


@dataclass(slots=True)
class CommonHandlerDependencies:
    """Shared dependencies passed to common execution handlers."""

    build_cancel_token: Optional[Callable[[ExecutionRequest], CancelToken]] = None


class BaseExecutionHandler:
    """Common execution-handler utilities."""

    mode: ExecutionMode

    def __init__(self, deps: CommonHandlerDependencies) -> None:
        self._deps = deps

    def supports(self, mode: ExecutionMode) -> bool:
        return mode == self.mode

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        return request


class FactOnlyHandler(BaseExecutionHandler):
    """No-op handler for fact-only turns."""

    mode = ExecutionMode.FACT_ONLY

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(mode=request.mode, skip_emit=True, ux_plan=_serialize_ux_plan(request))
