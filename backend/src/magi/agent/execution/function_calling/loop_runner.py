"""Bounded function-calling loop runner."""

from __future__ import annotations

from typing import Any, cast

from ....config.models import ThinkingDepth
from ....llm.provider_bridge import _coerce_thinking_depth
from ....llm.streaming_events import LLMStreamEvent, emit_stream_event, get_stream_sink
from magi.control.run_control import RunControl
from ..task_budget import TaskBudgetExceeded, prepay_task_llm_calls
from .run_input import EngineRunInput
from .step_models import FunctionCallingStepOutcome, FunctionCallingStepState
from .types import ExecutionOutcome


class FunctionCallingLoopRunner:
    """Run the LLM/tool loop after the host has resolved public call inputs."""

    def __init__(self, host: Any) -> None:
        self._host = host

    async def run(
        self,
        run_input: EngineRunInput,
        *,
        control: RunControl,
    ) -> ExecutionOutcome:
        state = self._build_initial_state(run_input)
        depth = _coerce_thinking_depth(
            run_input.thinking_depth,
            run_input.disable_thinking,
        )
        while state.iteration < run_input.max_iterations:
            boundary_outcome = await self._poll_control_boundary(state, control)
            if boundary_outcome is not None:
                return boundary_outcome
            context_failure = await self._host._prepare_context_for_model(state)
            if context_failure is not None:
                return cast(ExecutionOutcome, context_failure)
            try:
                await prepay_task_llm_calls(2)
            except TaskBudgetExceeded:
                return await self._run_fallback_final_response(
                    state=state,
                    run_input=run_input,
                    thinking_depth=depth,
                    control=control,
                    final_response_reason="task_budget_finalization",
                )
            step_outcome = await self._execute_step(
                state=state,
                run_input=run_input,
                thinking_depth=depth,
                control=control,
            )
            loop_outcome = await self._handle_step_outcome(
                state=state,
                step_outcome=step_outcome,
            )
            if loop_outcome is not None:
                return loop_outcome

        return await self._run_fallback_final_response(
            state=state,
            run_input=run_input,
            thinking_depth=depth,
            control=control,
        )

    def _build_initial_state(self, run_input: EngineRunInput) -> FunctionCallingStepState:
        state = cast(
            FunctionCallingStepState,
            self._host.build_step_state(
                turn=run_input.turn,
                system_prompt=run_input.system_prompt,
                selected_tools=run_input.selected_tools,
                conversation_history=run_input.conversation_history,
                session_summary=run_input.session_summary,
                session_origin=run_input.session_origin,
                reply_context=run_input.reply_context,
                ephemeral_context=run_input.ephemeral_context,
            ),
        )
        self._host._current_messages = state.messages
        return state

    async def _poll_control_boundary(
        self,
        state: FunctionCallingStepState,
        control: RunControl,
    ) -> ExecutionOutcome | None:
        if await control.cancel_token.is_cancelled():
            return ExecutionOutcome(
                status="cancelled",
                content="",
                iterations=state.iteration,
            )
        if control.retract_signal.is_requested():
            return cast(
                ExecutionOutcome,
                self._host._build_retracted_outcome(state, control.retract_signal),
            )
        if control.suspend_signal.is_requested():
            return cast(
                ExecutionOutcome,
                self._host._build_suspended_outcome(state, control.suspend_signal),
            )
        await self._host.apply_steer_messages(state, control.steer_inbox)
        if control.detach_signal.is_requested():
            return cast(
                ExecutionOutcome,
                self._host._build_detached_outcome(state, control.detach_signal),
            )
        return None

    async def _execute_step(
        self,
        *,
        state: FunctionCallingStepState,
        run_input: EngineRunInput,
        thinking_depth: ThinkingDepth,
        control: RunControl,
    ) -> FunctionCallingStepOutcome:
        return cast(
            FunctionCallingStepOutcome,
            await self._host.step_executor.execute_step(
                state=state,
                user_message=run_input.turn.text,
                thinking_depth=thinking_depth,
                user_id=run_input.user_id,
                session_id=run_input.session_id,
                session_run_id=run_input.session_run_id,
                session_run_revision=run_input.session_run_revision,
                turn_id=run_input.turn_id,
                intent=run_input.intent,
                execution_agent_id=run_input.execution_agent_id,
                execution_workspace=run_input.execution_workspace,
                llm_timeout_seconds=run_input.llm_timeout_seconds,
                cancel_token=control.cancel_token,
                control=control,
                route_decision=run_input.route_decision,
            ),
        )

    async def _handle_step_outcome(
        self,
        *,
        state: FunctionCallingStepState,
        step_outcome: FunctionCallingStepOutcome,
    ) -> ExecutionOutcome | None:
        if step_outcome.status == "aborted":
            return None
        if step_outcome.status == "continue":
            if get_stream_sink() is not None:
                await emit_stream_event(LLMStreamEvent(kind="text_flush"))
            await self._host._drop_ephemeral_context(state)
            return None
        if step_outcome.status == "completed":
            return _build_completed_outcome(state, step_outcome)
        if step_outcome.status == "cancelled":
            return _build_cancelled_outcome(state, step_outcome)
        return _build_failed_outcome(state, step_outcome)

    async def _run_fallback_final_response(
        self,
        *,
        state: FunctionCallingStepState,
        run_input: EngineRunInput,
        thinking_depth: ThinkingDepth,
        control: RunControl,
        final_response_reason: str = "max_iterations_reached",
    ) -> ExecutionOutcome:
        context_failure = await self._host._prepare_context_for_model(
            state,
            include_tools=False,
        )
        if context_failure is not None:
            return cast(ExecutionOutcome, context_failure)
        return cast(
            ExecutionOutcome,
            await self._host._execute_fallback_final_response(
                state=state,
                thinking_depth=thinking_depth,
                user_id=run_input.user_id,
                session_id=run_input.session_id,
                session_run_id=run_input.session_run_id,
                session_run_revision=run_input.session_run_revision,
                turn_id=run_input.turn_id,
                intent=run_input.intent,
                execution_agent_id=run_input.execution_agent_id,
                execution_workspace=run_input.execution_workspace,
                llm_timeout_seconds=run_input.llm_timeout_seconds,
                final_response_json_mode=run_input.final_response_json_mode,
                final_response_reason=final_response_reason,
                cancel_token=control.cancel_token,
                control=control,
                route_decision=run_input.route_decision,
            ),
        )


def _build_completed_outcome(
    state: FunctionCallingStepState,
    step_outcome: FunctionCallingStepOutcome,
) -> ExecutionOutcome:
    return ExecutionOutcome(
        status="completed",
        content=step_outcome.content,
        tool_failures=list(state.tool_failures),
        attachments=list(state.chat_attachments),
        message_payload=dict(state.message_payload or {}),
        context_usage=(
            dict(state.latest_context_usage)
            if isinstance(state.latest_context_usage, dict)
            else None
        ),
        iterations=step_outcome.iteration,
    )


def _build_cancelled_outcome(
    state: FunctionCallingStepState,
    step_outcome: FunctionCallingStepOutcome,
) -> ExecutionOutcome:
    return ExecutionOutcome(
        status="cancelled",
        content="",
        tool_failures=list(state.tool_failures),
        iterations=step_outcome.iteration,
    )


def _build_failed_outcome(
    state: FunctionCallingStepState,
    step_outcome: FunctionCallingStepOutcome,
) -> ExecutionOutcome:
    return ExecutionOutcome(
        status="failed",
        content="",
        failure_reason=step_outcome.failure_reason,
        error_text=step_outcome.error_text,
        tool_failures=list(state.tool_failures),
        iterations=step_outcome.iteration,
    )


__all__ = ["FunctionCallingLoopRunner"]
