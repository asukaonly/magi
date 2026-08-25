"""Bounded function-calling loop runner."""

from __future__ import annotations

from typing import Any, cast

from ....config.models import ThinkingDepth
from ....core.logger import get_logger
from ....llm.streaming_events import (
    LLMStreamEvent,
    emit_stream_event,
    get_stream_sink,
)
from ...turn_input import UserTurnInput
from magi.control.run_control import RunControl
from ..completion_gate import CompletionGate
from ..context_fingerprint import stable_hash
from ..contracts import (
    AgentRunEventType,
    CompletionDecision,
    CompletionOutcome,
)
from ..reasoning import ReasoningState
from ..task_budget import TaskBudgetExceeded, prepay_task_llm_calls
from .model_capability_flow import FunctionCallingModelCapabilityFlow
from .run_input import AgentRunRequest
from .run_journal import FunctionCallingRunJournal
from .step_models import FunctionCallingStepOutcome, FunctionCallingStepState
from .types import ExecutionOutcome

logger = get_logger(__name__)


class FunctionCallingLoopRunner:
    """Run the LLM/tool loop after the host has resolved public call inputs."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._journal = FunctionCallingRunJournal(host)
        self._model_capability_flow = FunctionCallingModelCapabilityFlow(
            host,
            self._journal,
        )

    async def run(
        self,
        run_input: AgentRunRequest,
        *,
        control: RunControl,
    ) -> ExecutionOutcome:
        state = self._build_initial_state(run_input)
        state.reasoning_state = run_input.reasoning_state or ReasoningState.start(
            run_input.reasoning_policy
        )
        self._resolve_effective_reasoning_depth(state)
        await self._sync_model_context(state)
        await self._journal.start(state, run_input)
        capability_outcome = await self._model_capability_flow.prepare(
            state=state,
            run_input=run_input,
            control=control,
            thinking_depth=self._resolve_effective_reasoning_depth(state),
        )
        if capability_outcome is not None:
            return await self._record_terminal_outcome(state, capability_outcome)
        while state.iteration < run_input.max_iterations:
            boundary_outcome = await self._poll_control_boundary(state, control)
            if boundary_outcome is not None:
                return await self._record_terminal_outcome(state, boundary_outcome)
            context_failure = await self._host._prepare_context_for_model(state)
            if context_failure is not None:
                return await self._record_terminal_outcome(
                    state,
                    cast(ExecutionOutcome, context_failure),
                )
            await self._sync_model_context(state)
            await self._journal.record_effective_context(
                state,
                mode="tool_loop",
                step_index=state.iteration + 1,
                system_prompt=state.effective_system_prompt,
                messages=state.messages,
                tools=state.tools,
            )
            try:
                await prepay_task_llm_calls(2)
            except TaskBudgetExceeded:
                outcome = await self._run_fallback_final_response(
                    state=state,
                    run_input=run_input,
                    thinking_depth=self._resolve_effective_reasoning_depth(state),
                    control=control,
                    final_response_reason="task_budget_finalization",
                )
                return await self._gate_fallback_outcome(state, run_input, outcome)
            requested_depth = state.reasoning_state.requested_depth
            effective_depth = self._resolve_effective_reasoning_depth(state)
            logger.info(
                "agent_run.step_started",
                run_id=run_input.run_id,
                step_index=state.iteration + 1,
                repair_iterations=state.repair_iterations,
                tool_count=len(state.selected_tool_names),
                requested_reasoning_depth=requested_depth.value,
                effective_reasoning_depth=effective_depth.value,
            )
            step_outcome = await self._execute_step(
                state=state,
                run_input=run_input,
                requested_thinking_depth=requested_depth,
                thinking_depth=effective_depth,
                control=control,
            )
            loop_outcome = await self._handle_step_outcome(
                state=state,
                step_outcome=step_outcome,
                run_input=run_input,
            )
            if loop_outcome is not None:
                return await self._record_terminal_outcome(state, loop_outcome)

        outcome = await self._run_fallback_final_response(
            state=state,
            run_input=run_input,
            thinking_depth=self._resolve_effective_reasoning_depth(state),
            control=control,
        )
        return await self._gate_fallback_outcome(state, run_input, outcome)

    def _build_initial_state(self, run_input: AgentRunRequest) -> FunctionCallingStepState:
        checkpoint = run_input.checkpoint
        state = cast(
            FunctionCallingStepState,
            self._host.build_step_state(
                turn=(
                    run_input.turn
                    if checkpoint is None
                    else UserTurnInput(
                        text="",
                        attachments=[],
                        user_id=run_input.turn.user_id,
                        session_id=run_input.turn.session_id,
                    )
                ),
                system_prompt=run_input.system_prompt,
                selected_tools=(
                    run_input.selected_tools
                    if checkpoint is None
                    else checkpoint.selected_tool_names
                ),
                conversation_history=(
                    run_input.conversation_history if checkpoint is None else None
                ),
                session_summary=run_input.session_summary,
                session_origin=run_input.session_origin,
                reply_context=run_input.reply_context,
                ephemeral_context=run_input.ephemeral_context,
            ),
        )
        state.run_id = run_input.run_id
        state.reasoning_policy = run_input.reasoning_policy
        if checkpoint is not None:
            state.messages = [dict(message) for message in checkpoint.messages]
            state.effective_system_prompt = checkpoint.effective_system_prompt
            state.tools = [dict(tool) for tool in checkpoint.tools]
            state.selected_tool_names = list(checkpoint.selected_tool_names)
            state.iteration = checkpoint.iteration
            state.repair_iterations = checkpoint.repair_iterations
            state.tool_evidence = list(checkpoint.tool_evidence)
            state.tool_failures = [dict(item) for item in checkpoint.tool_failures]
            state.chat_attachments = [dict(item) for item in checkpoint.chat_attachments]
            state.message_payload = dict(checkpoint.message_payload)
            state.tool_expansion_count = checkpoint.tool_expansion_count
            state.consecutive_failed_tool_iterations = checkpoint.consecutive_failed_tool_iterations
            state.all_tools_failed = checkpoint.all_tools_failed
            state.failed_tool_call_fingerprints = set(checkpoint.failed_tool_call_fingerprints)
            state.failure_signature_counts = dict(checkpoint.failure_signature_counts)
            state.repeated_blocker_tool_names = set(checkpoint.repeated_blocker_tool_names)
            state.suppressed_tool_names = set(checkpoint.suppressed_tool_names)
        state.run_plan_reader = run_input.run_plan_reader
        state.model_context_port = run_input.model_context_port
        state.model_context_turn_id = run_input.turn_id
        self._host._current_messages = state.messages
        return state

    async def _sync_model_context(self, state: FunctionCallingStepState) -> None:
        port = state.model_context_port
        if port is None:
            return
        await port.commit(
            messages=state.messages,
            turn_id=state.model_context_turn_id,
            run_id=state.run_id,
            step_index=state.iteration,
        )

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
        injected_inputs = await self._host.apply_run_inputs(
            state,
            control.input_queue,
        )
        if injected_inputs and state.journal is not None:
            await state.journal.append(
                AgentRunEventType.CONTROL_RECEIVED,
                step_index=state.iteration,
                payload={"inputs": injected_inputs},
            )
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
        run_input: AgentRunRequest,
        requested_thinking_depth: ThinkingDepth,
        thinking_depth: ThinkingDepth,
        control: RunControl,
    ) -> FunctionCallingStepOutcome:
        return cast(
            FunctionCallingStepOutcome,
            await self._host.step_executor.execute_step(
                state=state,
                user_message=run_input.turn.text,
                requested_thinking_depth=requested_thinking_depth,
                thinking_depth=thinking_depth,
                user_id=run_input.user_id,
                session_id=run_input.session_id,
                run_id=run_input.run_id,
                run_revision=run_input.run_revision,
                turn_id=run_input.turn_id,
                execution_preset=run_input.execution_preset,
                execution_agent_id=run_input.execution_agent_id,
                execution_workspace=run_input.execution_workspace,
                llm_timeout_seconds=run_input.llm_timeout_seconds,
                cancel_token=control.cancel_token,
                control=control,
                skill_preapproval_rules=run_input.skill_preapproval_rules,
            ),
        )

    def _resolve_effective_reasoning_depth(
        self,
        state: FunctionCallingStepState,
    ) -> ThinkingDepth:
        requested = state.reasoning_state.requested_depth
        resolver = getattr(
            getattr(self._host, "provider_bridge", None),
            "resolve_effective_reasoning_depth",
            None,
        )
        effective = resolver(requested) if callable(resolver) else requested
        state.reasoning_state.effective_depth = effective
        return effective

    async def _handle_step_outcome(
        self,
        *,
        state: FunctionCallingStepState,
        step_outcome: FunctionCallingStepOutcome,
        run_input: AgentRunRequest,
    ) -> ExecutionOutcome | None:
        logger.info(
            "agent_run.step_finished",
            run_id=run_input.run_id,
            step_index=step_outcome.iteration,
            status=step_outcome.status,
            failure_reason=step_outcome.failure_reason,
            evidence_count=len(state.tool_evidence),
            tool_failure_count=len(state.tool_failures),
        )
        if step_outcome.status == "aborted":
            return None
        if step_outcome.status == "continue":
            if get_stream_sink() is not None:
                await emit_stream_event(LLMStreamEvent(kind="text_flush"))
            await self._host._drop_ephemeral_context(state)
            return None
        if step_outcome.status == "completed":
            return await self._evaluate_proposed_final(
                state=state,
                step_outcome=step_outcome,
                run_input=run_input,
            )
        if step_outcome.status == "cancelled":
            return _build_cancelled_outcome(state, step_outcome)
        return _build_failed_outcome(state, step_outcome)

    async def _evaluate_proposed_final(
        self,
        *,
        state: FunctionCallingStepState,
        step_outcome: FunctionCallingStepOutcome,
        run_input: AgentRunRequest,
    ) -> ExecutionOutcome | None:
        if state.journal is not None:
            await state.journal.append(
                AgentRunEventType.COMPLETION_REQUESTED,
                step_index=step_outcome.iteration,
                payload={"response_hash": stable_hash(step_outcome.content)},
            )
        run_plan = None
        try:
            run_plan = run_input.run_plan_reader.current()
        except Exception:
            logger.exception("agent_run.plan_governance_unavailable", run_id=run_input.run_id)
            decision = CompletionDecision(
                outcome=CompletionOutcome.BLOCKED,
                reason_code="plan_governance_unavailable",
                observations=(
                    "The runtime could not verify the canonical run plan, so completion was blocked.",
                ),
            )
        else:
            decision = CompletionGate().evaluate(
                policy=run_input.completion_policy,
                evidence=state.tool_evidence,
                repair_iterations=state.repair_iterations,
                run_plan=run_plan,
            )
        logger.info(
            "agent_run.completion_decision",
            run_id=run_input.run_id,
            step_index=step_outcome.iteration,
            outcome=decision.outcome.value,
            reason_code=decision.reason_code,
            reasoning_helpful=decision.reasoning_helpful,
            repair_iterations=state.repair_iterations,
            max_repair_iterations=run_input.completion_policy.max_repair_iterations,
            evidence_count=len(state.tool_evidence),
            successful_evidence_count=sum(1 for item in state.tool_evidence if item.success),
            plan_id=getattr(run_plan, "plan_id", None),
            plan_version=getattr(run_plan, "version", None),
            plan_status=(
                getattr(getattr(run_plan, "status", None), "value", None)
                if run_plan is not None
                else None
            ),
        )
        if decision.outcome is CompletionOutcome.COMPLETE:
            return _build_completed_outcome(state, step_outcome)
        await emit_stream_event(
            LLMStreamEvent(
                kind="text_reset",
                source="chat",
                step_label="completion_repair",
            )
        )
        if state.journal is not None:
            await state.journal.append(
                AgentRunEventType.COMPLETION_REJECTED,
                step_index=step_outcome.iteration,
                payload=decision.to_dict(),
            )
        if decision.outcome is CompletionOutcome.CONTINUE:
            state.repair_iterations += 1
            if decision.reasoning_helpful and state.reasoning_state is not None:
                previous = state.reasoning_state.effective_depth
                escalated = state.reasoning_state.escalate(
                    run_input.reasoning_policy,
                    reason=decision.reason_code,
                )
                logger.info(
                    "agent_run.reasoning_escalation",
                    run_id=run_input.run_id,
                    step_index=step_outcome.iteration,
                    source="completion_gate",
                    reason=decision.reason_code,
                    approved=escalated,
                    previous_depth=previous.value,
                    requested_depth=state.reasoning_state.requested_depth.value,
                    maximum_depth=run_input.reasoning_policy.maximum_depth.value,
                    escalation_step=run_input.reasoning_policy.escalation_step,
                    escalation_count=state.reasoning_state.escalation_count,
                )
                if escalated and state.journal is not None:
                    await state.journal.append(
                        AgentRunEventType.REASONING_DEPTH_CHANGED,
                        step_index=step_outcome.iteration,
                        payload={
                            "previous_depth": previous.value,
                            **state.reasoning_state.to_dict(),
                        },
                    )
            observation = "\n".join(decision.observations)
            state.messages.append(
                {
                    "role": "user",
                    "content": (
                        "[Runtime completion requirement]\n"
                        f"Reason: {decision.reason_code}\n{observation}\n"
                        "Continue the task. Do not present a final answer until this requirement is satisfied."
                    ),
                }
            )
            if state.journal is not None:
                await state.journal.append(
                    AgentRunEventType.REPAIR_STARTED,
                    step_index=step_outcome.iteration,
                    payload={
                        "repair_iteration": state.repair_iterations,
                        "reason_code": decision.reason_code,
                    },
                )
            await emit_stream_event(
                LLMStreamEvent(
                    kind="status_update",
                    text=(
                        "Validation failed; repairing and verifying again."
                        if decision.reason_code == "validation_failed"
                        else "Verifying the completed changes before finishing."
                    ),
                    source="chat",
                    step_label="completion_repair",
                )
            )
            return None
        if self._repair_budget_exhausted(
            decision=decision,
            state=state,
            run_input=run_input,
        ):
            await self._record_repair_exhausted(
                state=state,
                step_index=step_outcome.iteration,
                reason_code=decision.reason_code,
                observations=decision.observations,
                max_repair_iterations=run_input.completion_policy.max_repair_iterations,
            )
        return ExecutionOutcome(
            status="blocked",
            content=_blocked_outcome_message(decision),
            failure_reason=decision.reason_code,
            error_text=" ".join(decision.observations),
            tool_failures=list(state.tool_failures),
            iterations=step_outcome.iteration,
        )

    async def _gate_fallback_outcome(
        self,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcome:
        if outcome.status != "completed":
            return await self._record_terminal_outcome(state, outcome)
        gated = await self._evaluate_proposed_final(
            state=state,
            step_outcome=FunctionCallingStepOutcome(
                status="completed",
                iteration=outcome.iterations,
                content=outcome.content,
            ),
            run_input=run_input,
        )
        if gated is None:
            await self._record_repair_exhausted(
                state=state,
                step_index=outcome.iterations,
                reason_code="task_budget_finalization",
                observations=(
                    "The task budget ended before the required completion repair could run.",
                ),
                max_repair_iterations=run_input.completion_policy.max_repair_iterations,
            )
            return await self._record_terminal_outcome(
                state,
                ExecutionOutcome(
                    status="failed",
                    content="",
                    failure_reason="repair_budget_unavailable",
                    error_text="The task budget ended before required completion repair.",
                    tool_failures=list(state.tool_failures),
                    iterations=outcome.iterations,
                ),
            )
        return await self._record_terminal_outcome(state, gated)

    @staticmethod
    def _repair_budget_exhausted(
        *,
        decision: CompletionDecision,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
    ) -> bool:
        if decision.reason_code == "repair_exhausted":
            return True
        return bool(
            decision.reason_code == "required_plan_incomplete"
            and state.repair_iterations >= run_input.completion_policy.max_repair_iterations
        )

    @staticmethod
    async def _record_repair_exhausted(
        *,
        state: FunctionCallingStepState,
        step_index: int,
        reason_code: str,
        observations: tuple[str, ...],
        max_repair_iterations: int,
    ) -> None:
        if state.journal is not None:
            await state.journal.append(
                AgentRunEventType.REPAIR_EXHAUSTED,
                step_index=step_index,
                payload={
                    "reason_code": reason_code,
                    "repair_iterations": state.repair_iterations,
                    "max_repair_iterations": max_repair_iterations,
                    "observations": list(observations),
                },
            )
        await emit_stream_event(
            LLMStreamEvent(
                kind="status_update",
                text="Repair budget exhausted; the run is blocked.",
                source="chat",
                step_label="completion_repair_exhausted",
            )
        )

    async def _record_terminal_outcome(
        self,
        state: FunctionCallingStepState,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcome:
        await self._sync_model_context(state)
        return await self._journal.record_terminal(state, outcome)

    async def _run_fallback_final_response(
        self,
        *,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
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
        await self._sync_model_context(state)
        return cast(
            ExecutionOutcome,
            await self._host._execute_fallback_final_response(
                state=state,
                thinking_depth=thinking_depth,
                user_id=run_input.user_id,
                session_id=run_input.session_id,
                run_id=run_input.run_id,
                run_revision=run_input.run_revision,
                turn_id=run_input.turn_id,
                execution_preset=run_input.execution_preset,
                execution_agent_id=run_input.execution_agent_id,
                execution_workspace=run_input.execution_workspace,
                llm_timeout_seconds=run_input.llm_timeout_seconds,
                final_response_json_mode=run_input.final_response_json_mode,
                final_response_reason=final_response_reason,
                cancel_token=control.cancel_token,
                control=control,
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


def _blocked_outcome_message(decision: CompletionDecision) -> str:
    detail = " ".join(item.strip() for item in decision.observations if item.strip())
    return detail or f"The runtime blocked completion: {decision.reason_code}."


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
