"""Common execution handlers shared by task agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol

from ....agent.cancel import CancelToken, null_cancel_token
from magi.control.run_control import null_run_control
from ....agent.runtime.contracts import FactRecord
from ...task_orchestrator import TaskOrchestrator
from .contracts import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    OrchestrationLaunchRequest,
    OrchestrationUpdateRequest,
)

SpecializedLaunchCallback = Callable[[OrchestrationLaunchRequest], Awaitable[Optional[ExecutionResult]]]


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

    task_orchestrator: TaskOrchestrator
    start_specialized_orchestration: Optional[SpecializedLaunchCallback] = None
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


class OrchestrationLaunchHandler(BaseExecutionHandler):
    """Common handler for parent-task orchestration launch."""

    mode = ExecutionMode.ORCHESTRATION_LAUNCH

    async def build_request(self, request: ExecutionRequest) -> OrchestrationLaunchRequest:
        return OrchestrationLaunchRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            correlation_id=(
                request.context.latest_fact.correlation_id
                if isinstance(request.context.latest_fact, FactRecord)
                else None
            ),
        )

    async def execute(self, request: OrchestrationLaunchRequest) -> ExecutionResult:
        orchestration_plan = getattr(request.intent, "orchestration_plan", None)
        if orchestration_plan is None:
            return ExecutionResult(
                mode=request.mode,
                response_text="Failed to generate orchestration plan for this request.",
                ux_plan=_serialize_ux_plan(request),
            )
        if self._deps.start_specialized_orchestration is not None:
            specialized = await self._deps.start_specialized_orchestration(request)
            if specialized is not None:
                return specialized
        cancel_token = (
            self._deps.build_cancel_token(request)
            if self._deps.build_cancel_token is not None
            else null_cancel_token()
        )
        # Read the RunControl bundle from the chat runtime context (Task 8
        # ensures it's always present on ChatRuntimeContext). Overlay the
        # cancel_token built above so legacy cancel-button paths continue
        # to function alongside the bundle's other signals.
        #
        # We use getattr with a fallback to null_run_control() so this handler
        # stays safe against non-chat contexts that may not carry a .control
        # field, while still reading request.context.control when present.
        _ctx_control = request.context.control if hasattr(request.context, "control") else None
        control = _ctx_control if _ctx_control is not None else null_run_control()
        control.cancel_token = cancel_token
        raw_result = await self._deps.task_orchestrator.start_orchestration(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            run_id=getattr(request.context, "session_run_id", None),
            run_revision=int(getattr(request.context, "session_run_revision", 0) or 0),
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
            user_message_generation=request.context.user_message_generation,
            history=request.context.history,
            history_key=request.context.history_key,
            correlation_id=request.correlation_id,
            orchestration_plan=orchestration_plan,
            persona_id=getattr(request.context, "active_persona_id", None),
            # cancel_token= kept for call-site backward compat; ignored by
            # start_orchestration when control= is supplied (the handler has
            # already overlaid the cancel token onto control.cancel_token above).
            cancel_token=cancel_token,
            control=control,
        )
        return ExecutionResult(
            mode=request.mode,
            response_text=raw_result.response,
            skip_emit=raw_result.skip_emit,
            root_user_message=raw_result.root_user_message or request.context.latest_user_message,
            correlation_id=raw_result.correlation_id,
            orchestration_id=raw_result.orchestration_id,
            message_started_at=raw_result.message_started_at,
            turn_id=raw_result.turn_id,
            streamed=raw_result.streamed,
            llm_trace={"retracted": True} if raw_result.retracted else {},
            ux_plan=_serialize_ux_plan(request),
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
        )

    async def execute(self, request: OrchestrationUpdateRequest) -> ExecutionResult:
        raw_result = await self._deps.task_orchestrator.process_worker_updates(request.context.batch_facts)
        return ExecutionResult(
            mode=request.mode,
            response_text=raw_result.response,
            skip_emit=raw_result.skip_emit,
            root_user_message=raw_result.root_user_message or request.context.latest_user_message,
            correlation_id=raw_result.correlation_id,
            orchestration_id=raw_result.orchestration_id,
            message_started_at=raw_result.message_started_at,
            turn_id=raw_result.turn_id,
            streamed=raw_result.streamed,
            ux_plan=_serialize_ux_plan(request),
        )
