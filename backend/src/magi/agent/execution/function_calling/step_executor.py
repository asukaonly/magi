"""Single-step execution for function-calling loops."""

from __future__ import annotations

from typing import Any, cast

from ....config.models import ThinkingDepth
from ....llm.cancellable_client import CancellationRaised, RetractRaised
from ...cancel import CancelToken, null_cancel_token
from magi.control.run_control import RunControl
from .step_models import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
    StepExecutionContext,
)
from .step_tool_batch import FunctionCallingToolBatchExecutor

class FunctionCallingStepExecutor:
    """Execute one LLM decision and at most one tool batch."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver
        self._tool_batch_executor = FunctionCallingToolBatchExecutor(driver)

    async def execute_step(
        self,
        *,
        state: FunctionCallingStepState,
        user_message: str,
        requested_thinking_depth: ThinkingDepth | None = None,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        user_id: str,
        session_id: str | None,
        session_run_id: str | None = None,
        session_run_revision: int = 0,
        turn_id: str | None,
        execution_preset: str,
        execution_agent_id: str,
        execution_workspace: str | None = None,
        llm_timeout_seconds: float | None = None,
        cancel_token: CancelToken | None = None,
        control: RunControl | None = None,
    ) -> FunctionCallingStepOutcome:
        """Run one bounded loop iteration and return control to the caller."""
        token = cancel_token if cancel_token is not None else null_cancel_token()
        ctx = StepExecutionContext(
            user_message=user_message,
            user_id=user_id,
            session_id=session_id,
            session_run_id=session_run_id,
            session_run_revision=session_run_revision,
            turn_id=turn_id,
            execution_preset=execution_preset,
            execution_agent_id=execution_agent_id,
            execution_workspace=execution_workspace,
        )
        return await self._execute_step_with_context(
            state=state,
            ctx=ctx,
            requested_thinking_depth=requested_thinking_depth or thinking_depth,
            thinking_depth=thinking_depth,
            llm_timeout_seconds=llm_timeout_seconds,
            cancel_token=token,
            control=control,
        )

    async def _execute_step_with_context(
        self,
        *,
        state: FunctionCallingStepState,
        ctx: StepExecutionContext,
        requested_thinking_depth: ThinkingDepth,
        thinking_depth: ThinkingDepth,
        llm_timeout_seconds: float | None,
        cancel_token: CancelToken,
        control: RunControl | None,
    ) -> FunctionCallingStepOutcome:
        state.iteration += 1
        iteration = state.iteration
        if state.journal is not None:
            from ..contracts import AgentRunEventType

            if state.repair_iterations:
                await state.journal.append(
                    AgentRunEventType.REPAIR_STEP_STARTED,
                    step_index=iteration,
                    payload={"repair_iteration": state.repair_iterations},
                )
            await state.journal.append(
                AgentRunEventType.STEP_STARTED,
                step_index=iteration,
                payload={
                    "requested_reasoning_depth": requested_thinking_depth.value,
                    "effective_reasoning_depth": thinking_depth.value,
                },
            )
        iteration_started_at_ms = await self._start_iteration(ctx, iteration)
        response, terminal_outcome = await self._call_llm_for_step(
            state=state,
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
            thinking_depth=thinking_depth,
            llm_timeout_seconds=llm_timeout_seconds,
            control=control,
        )
        if terminal_outcome is not None:
            return terminal_outcome
        if response is None:  # pragma: no cover - helper contract guard
            return FunctionCallingStepOutcome(status="aborted", iteration=iteration)
        if isinstance(response.get("context_usage"), dict):
            state.latest_context_usage = dict(response["context_usage"])

        assistant_message = response.get("assistant_message")
        if state.journal is not None:
            from ..contracts import AgentRunEventType

            await state.journal.append(
                AgentRunEventType.MODEL_OUTPUT,
                step_index=iteration,
                payload={
                    "assistant_message": (
                        dict(assistant_message)
                        if isinstance(assistant_message, dict)
                        else None
                    ),
                    "content": response.get("content"),
                    "tool_calls": [
                        {
                            "id": getattr(tool_call, "id", None),
                            "name": getattr(tool_call, "name", None),
                            "arguments": getattr(tool_call, "arguments", None),
                        }
                        for tool_call in (response.get("tool_calls") or [])
                    ],
                    "llm_trace": dict(response.get("llm_trace") or {}),
                },
            )
        if assistant_message:
            self._driver._append_message(state.messages, assistant_message)

        if response.get("tool_calls"):
            return await self._tool_batch_executor.handle_tool_call_response(
                state=state,
                response=response,
                ctx=ctx,
                iteration=iteration,
                iteration_started_at_ms=iteration_started_at_ms,
                cancel_token=cancel_token,
            )

        return await self._handle_non_tool_response(
            response=response,
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
        )

    async def _start_iteration(self, ctx: StepExecutionContext, iteration: int) -> int | None:
        started_at_ms = await self._driver._start_iteration_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            execution_agent_id=ctx.execution_agent_id,
        )
        await self._driver._emit_loop_event(
            {
                "stage": "iteration_started",
                "iteration": iteration,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
                "execution_preset": ctx.execution_preset,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )
        return cast(int | None, started_at_ms)

    async def _call_llm_for_step(
        self,
        *,
        state: FunctionCallingStepState,
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
        thinking_depth: ThinkingDepth,
        llm_timeout_seconds: float | None,
        control: RunControl | None,
    ) -> tuple[dict[str, Any] | None, FunctionCallingStepOutcome | None]:
        try:
            response = await self._driver._call_llm_with_tools(
                system_prompt=state.effective_system_prompt,
                messages=state.messages,
                tools=state.tools,
                thinking_depth=thinking_depth,
                timeout_seconds=llm_timeout_seconds,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
                execution_preset=ctx.execution_preset,
                execution_agent_id=ctx.execution_agent_id,
                iteration=iteration,
                control=control,
            )
        except (CancellationRaised, RetractRaised):
            return None, FunctionCallingStepOutcome(status="aborted", iteration=iteration)
        except Exception as exc:
            failure_reason = self._driver._classify_exception_failure(exc)
            error_text = self._driver._format_exception_trace_text(exc)
            await self._driver._complete_iteration_trace(
                turn_id=ctx.turn_id,
                iteration=iteration,
                execution_agent_id=ctx.execution_agent_id,
                started_at_ms=iteration_started_at_ms,
                status="failed",
                error_text=error_text,
            )
            return None, FunctionCallingStepOutcome(
                status="failed",
                iteration=iteration,
                failure_reason=failure_reason,
                error_text=error_text,
            )

        if control is not None:
            if control.retract_signal.is_requested() or await control.cancel_token.is_cancelled():
                return None, FunctionCallingStepOutcome(status="aborted", iteration=iteration)
        return response, None

    async def _handle_non_tool_response(
        self,
        *,
        response: dict[str, Any],
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
    ) -> FunctionCallingStepOutcome:
        if response.get("content"):
            return await self._handle_final_response(
                response=response,
                ctx=ctx,
                iteration=iteration,
                iteration_started_at_ms=iteration_started_at_ms,
            )
        return await self._handle_unexpected_response(
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
        )

    async def _handle_final_response(
        self,
        *,
        response: dict[str, Any],
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
    ) -> FunctionCallingStepOutcome:
        final_content = str(response["content"])
        if not final_content.strip():
            return FunctionCallingStepOutcome(
                status="failed",
                iteration=iteration,
                failure_reason="Empty final response",
            )
        await self._record_final_response(
            response=response,
            final_content=final_content,
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
        )
        return FunctionCallingStepOutcome(
            status="completed",
            iteration=iteration,
            content=final_content,
        )

    async def _record_final_response(
        self,
        *,
        response: dict[str, Any],
        final_content: str,
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
    ) -> None:
        await self._driver._persist_llm_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            stage="final_response",
            execution_agent_id=ctx.execution_agent_id,
            llm_trace=response.get("llm_trace"),
            response_preview=final_content,
        )
        await self._driver._emit_loop_event(
            {
                "stage": "final_response",
                "iteration": iteration,
                "response_preview": final_content[:500],
                "llm_trace": response.get("llm_trace"),
                "context_usage": response.get("context_usage"),
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
                "execution_preset": ctx.execution_preset,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )
        await self._driver._complete_iteration_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            execution_agent_id=ctx.execution_agent_id,
            started_at_ms=iteration_started_at_ms,
            status="completed",
            result_preview=final_content[:240],
        )

    async def _handle_unexpected_response(
        self,
        *,
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
    ) -> FunctionCallingStepOutcome:
        await self._driver._complete_iteration_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            execution_agent_id=ctx.execution_agent_id,
            started_at_ms=iteration_started_at_ms,
            status="failed",
            error_text="Unexpected function-calling response",
        )
        return FunctionCallingStepOutcome(
            status="failed",
            iteration=iteration,
            failure_reason="Unexpected function-calling response",
        )
