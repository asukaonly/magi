"""Worker execution lifecycle for launched worker agents."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Protocol, cast

from ...agent.execution.function_calling import FunctionCallingOrchestrator
from ...agent.execution.function_calling.run_input import AgentRunRequest
from ...agent.turn_input import UserTurnInput
from ...control.run_control import null_run_control
from ...core.logger import get_logger
from ...llm.streaming_events import stream_source
from .worker_state import WorkerRunState
from .child_result import ChildRunResult

logger = get_logger(__name__)


class _WorkerExecutionHostProtocol(Protocol):
    _llm_adapter: Any
    _tool_registry: Any
    _runtime_trace_store: Any
    _scenario_llm_pool: Any
    _active_model_provider: Any
    _permission_gateway_provider: Any

    async def _handle_tool_result(
        self,
        run_state: WorkerRunState,
        payload: Dict[str, Any],
    ) -> None: ...

    async def _handle_worker_loop_event(
        self,
        run_state: WorkerRunState,
        payload: Dict[str, Any],
    ) -> None: ...

    def _validate_worker_result(self, preset: Any, content: str) -> ChildRunResult: ...

    def _preview_worker_result(self, worker_result: ChildRunResult, limit: int = 400) -> str: ...

    async def _emit_worker_failed_trace(self, run_state: WorkerRunState) -> None: ...

    async def _emit_worker_completed_trace(self, run_state: WorkerRunState) -> None: ...

    async def _emit_worker_cancelled_trace(self, run_state: WorkerRunState) -> None: ...


class WorkerExecutionMixin:
    """Run bounded child agents and persist their terminal trace state."""

    async def _run_worker(
        self,
        run_state: WorkerRunState,
        worker_system_prompt: str,
        selected_tools: List[str],
        max_iterations: int,
        execution_workspace: str,
    ) -> None:
        try:
            outcome = await self._execute_worker(
                run_state,
                worker_system_prompt=worker_system_prompt,
                selected_tools=selected_tools,
                max_iterations=max_iterations,
                execution_workspace=execution_workspace,
            )
            await self._handle_worker_outcome(run_state, outcome)
        except asyncio.CancelledError:
            await self._handle_cancelled_error(run_state)
        except Exception as exc:
            await self._handle_unexpected_error(run_state, exc)

    async def _execute_worker(
        self,
        run_state: WorkerRunState,
        *,
        worker_system_prompt: str,
        selected_tools: List[str],
        max_iterations: int,
        execution_workspace: str,
    ) -> Any:
        executor = self._build_worker_executor(run_state)
        async with stream_source("worker"):
            return await executor.run(
                _build_agent_run_request(
                    run_state,
                    worker_system_prompt=worker_system_prompt,
                    selected_tools=selected_tools,
                    max_iterations=max_iterations,
                    execution_workspace=execution_workspace,
                )
            )

    def _build_worker_executor(self, run_state: WorkerRunState) -> FunctionCallingOrchestrator:
        host = cast(_WorkerExecutionHostProtocol, self)
        return FunctionCallingOrchestrator(
            llm_adapter=host._llm_adapter,
            active_model_provider=host._active_model_provider,
            tool_registry=host._tool_registry,
            skill_runner=None,
            tool_result_callback=lambda payload: host._handle_tool_result(run_state, payload),
            loop_event_callback=lambda payload: host._handle_worker_loop_event(run_state, payload),
            runtime_trace_store=host._runtime_trace_store,
            scenario_llm_pool=host._scenario_llm_pool,
            permission_gateway_provider=host._permission_gateway_provider,
        )

    async def _handle_worker_outcome(self, run_state: WorkerRunState, outcome: Any) -> None:
        _mark_worker_finished(run_state)
        run_state.failure_reason = outcome.failure_reason
        if outcome.status == "cancelled":
            await self._handle_cancelled_outcome(run_state)
            return

        validated_result = self._validated_worker_result_or_none(run_state, outcome)
        if outcome.succeeded and validated_result:
            await self._handle_validated_worker_result(
                run_state,
                outcome=outcome,
                validated_result=validated_result,
            )
            return

        await self._handle_failed_outcome(run_state, outcome)

    def _validated_worker_result_or_none(
        self,
        run_state: WorkerRunState,
        outcome: Any,
    ) -> ChildRunResult | None:
        if not outcome.succeeded:
            return None
        host = cast(_WorkerExecutionHostProtocol, self)
        try:
            return host._validate_worker_result(
                preset=run_state.preset,
                content=outcome.content,
            )
        except ValueError as exc:
            run_state.failure_reason = "INVALID_WORKER_RESULT"
            run_state.error = str(exc)
            return None

    async def _handle_validated_worker_result(
        self,
        run_state: WorkerRunState,
        *,
        outcome: Any,
        validated_result: ChildRunResult,
    ) -> None:
        host = cast(_WorkerExecutionHostProtocol, self)
        run_state.result = validated_result.to_dict()
        run_state.result_preview = host._preview_worker_result(validated_result)
        if validated_result.result_status == "failed":
            await self._handle_reported_worker_failure(
                run_state,
                outcome=outcome,
                validated_result=validated_result,
            )
            return
        await self._handle_worker_completed(run_state, validated_result)

    async def _handle_reported_worker_failure(
        self,
        run_state: WorkerRunState,
        *,
        outcome: Any,
        validated_result: ChildRunResult,
    ) -> None:
        run_state.status = "failed"
        run_state.failure_reason = str(
            validated_result.failure_reason or outcome.failure_reason or "WORKER_REPORTED_FAILURE"
        ).strip()
        run_state.error = run_state.failure_reason
        host = cast(_WorkerExecutionHostProtocol, self)
        await host._emit_worker_failed_trace(run_state)

    async def _handle_worker_completed(
        self,
        run_state: WorkerRunState,
        validated_result: ChildRunResult,
    ) -> None:
        run_state.status = "completed"
        host = cast(_WorkerExecutionHostProtocol, self)
        await host._emit_worker_completed_trace(run_state)

    async def _handle_failed_outcome(self, run_state: WorkerRunState, outcome: Any) -> None:
        run_state.status = "failed"
        run_state.error = (
            run_state.error
            or getattr(outcome, "error_text", None)
            or outcome.failure_reason
            or "Worker execution failed"
        )
        host = cast(_WorkerExecutionHostProtocol, self)
        await host._emit_worker_failed_trace(run_state)

    async def _handle_cancelled_outcome(self, run_state: WorkerRunState) -> None:
        run_state.status = "cancelled"
        run_state.failure_reason = "CANCELLED"
        run_state.error = "Worker cancelled"
        host = cast(_WorkerExecutionHostProtocol, self)
        await host._emit_worker_cancelled_trace(run_state)

    async def _handle_cancelled_error(self, run_state: WorkerRunState) -> None:
        run_state.status = "cancelled"
        run_state.error = "Worker cancelled"
        run_state.failure_reason = "CANCELLED"
        _mark_worker_finished(run_state)
        host = cast(_WorkerExecutionHostProtocol, self)
        await host._emit_worker_cancelled_trace(run_state)

    async def _handle_unexpected_error(
        self,
        run_state: WorkerRunState,
        exc: Exception,
    ) -> None:
        run_state.status = "failed"
        run_state.error = str(exc)
        _mark_worker_finished(run_state)
        logger.error(
            "Worker agent execution failed | worker_id=%s error=%s",
            run_state.worker_id,
            exc,
            exc_info=True,
        )
        host = cast(_WorkerExecutionHostProtocol, self)
        await host._emit_worker_failed_trace(run_state)


def _build_agent_run_request(
    run_state: WorkerRunState,
    *,
    worker_system_prompt: str,
    selected_tools: List[str],
    max_iterations: int,
    execution_workspace: str,
) -> AgentRunRequest:
    return AgentRunRequest.headless(
        turn=UserTurnInput(
            text=run_state.prompt,
            attachments=[],
            user_id=run_state.user_id,
            session_id=run_state.session_id or run_state.worker_id,
        ),
        system_prompt=worker_system_prompt,
        selected_tools=selected_tools,
        user_id=run_state.user_id,
        session_id=run_state.session_id or run_state.worker_id,
        session_run_id=run_state.child_run_id,
        session_run_revision=run_state.run_revision,
        run_id=run_state.child_run_id,
        parent_run_id=run_state.parent_run_id,
        turn_id=run_state.turn_id,
        conversation_history=[],
        max_iterations=max_iterations,
        reasoning_policy=run_state.reasoning_policy,
        execution_preset=f"child_{run_state.preset.value}",
        execution_agent_id=run_state.worker_id,
        execution_workspace=execution_workspace,
        final_response_json_mode=True,
        control=_worker_run_control(run_state),
        ephemeral_context=run_state.parent_context_summary,
    )


def _worker_run_control(run_state: WorkerRunState):
    control = null_run_control()
    control.cancel_token = run_state.cancel_token
    return control


def _mark_worker_finished(run_state: WorkerRunState) -> None:
    run_state.completed_at = time.time()
    run_state.updated_at = run_state.completed_at


__all__ = ["WorkerExecutionMixin"]
