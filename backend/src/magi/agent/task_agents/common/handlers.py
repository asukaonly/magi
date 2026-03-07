"""Common execution handlers shared by task agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol

from ....core.runtime.contracts import FactRecord
from ...task_orchestrator import TaskOrchestrator
from .contracts import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    OrchestrationLaunchRequest,
    OrchestrationUpdateRequest,
)

SpecializedLaunchCallback = Callable[[OrchestrationLaunchRequest], Awaitable[Optional[ExecutionResult]]]


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

    task_orchestrator: TaskOrchestrator
    start_specialized_orchestration: Optional[SpecializedLaunchCallback] = None


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
        return ExecutionResult(mode=request.mode, skip_emit=True)


class OrchestrationLaunchHandler(BaseExecutionHandler):
    """Common handler for parent-task orchestration launch."""

    mode = ExecutionMode.ORCHESTRATION_LAUNCH

    async def build_request(self, request: ExecutionRequest) -> OrchestrationLaunchRequest:
        request.metadata = {
            **request.metadata,
            "correlation_id": request.context.latest_fact.correlation_id
            if isinstance(request.context.latest_fact, FactRecord)
            else None,
        }
        return OrchestrationLaunchRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_payload=dict(request.prompt_payload),
            tool_payload=dict(request.tool_payload),
            metadata=dict(request.metadata),
        )

    async def execute(self, request: OrchestrationLaunchRequest) -> ExecutionResult:
        orchestration_plan = request.intent.orchestration_plan
        if orchestration_plan is None:
            return ExecutionResult(
                mode=request.mode,
                response_text="Failed to generate orchestration strategy for this request.",
            )
        if self._deps.start_specialized_orchestration is not None:
            specialized = await self._deps.start_specialized_orchestration(request)
            if specialized is not None:
                return specialized
        raw_result = await self._deps.task_orchestrator.start_orchestration(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            history=request.context.history,
            history_key=request.context.history_key,
            correlation_id=request.metadata.get("correlation_id"),
            orchestration_strategy=orchestration_plan.to_strategy_dict(),
        )
        return ExecutionResult(
            mode=request.mode,
            response_text=str(raw_result.get("response", "")),
            skip_emit=bool(raw_result.get("skip_emit", False)),
            root_user_message=str(raw_result.get("root_user_message") or request.context.latest_user_message),
            correlation_id=raw_result.get("correlation_id"),
            orchestration_id=raw_result.get("orchestration_id"),
            message_started_at=raw_result.get("message_started_at"),
        )


class OrchestrationUpdateHandler(BaseExecutionHandler):
    """Common handler for processing worker updates."""

    mode = ExecutionMode.ORCHESTRATION_UPDATE

    async def build_request(self, request: ExecutionRequest) -> OrchestrationUpdateRequest:
        return OrchestrationUpdateRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_payload=dict(request.prompt_payload),
            tool_payload=dict(request.tool_payload),
            metadata=dict(request.metadata),
        )

    async def execute(self, request: OrchestrationUpdateRequest) -> ExecutionResult:
        raw_result = await self._deps.task_orchestrator.process_worker_updates(request.context.batch_facts)
        return ExecutionResult(
            mode=request.mode,
            response_text=str(raw_result.get("response", "")),
            skip_emit=bool(raw_result.get("skip_emit", False)),
            root_user_message=str(raw_result.get("root_user_message") or request.context.latest_user_message),
            correlation_id=raw_result.get("correlation_id"),
            orchestration_id=raw_result.get("orchestration_id"),
            message_started_at=raw_result.get("message_started_at"),
        )
