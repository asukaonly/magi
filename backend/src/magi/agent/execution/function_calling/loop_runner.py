"""Bounded function-calling loop runner."""

from __future__ import annotations

import json
import time
from typing import Any, cast

from ....config.models import ThinkingDepth
from ....core.logger import get_logger
from ....llm.streaming_events import (
    LLMStreamEvent,
    emit_stream_event,
    get_stream_sink,
    stream_scope,
)
from ...turn_input import UserTurnInput
from magi.control.run_control import RunControl
from ..completion_gate import CompletionGate
from ..context_fingerprint import (
    context_source_refs,
    effective_context_fingerprint,
    message_fingerprints,
    stable_hash,
)
from ..contracts import (
    AgentRunEventType,
    CompletionDecision,
    CompletionOutcome,
    RunContextManifest,
)
from ..journal import AgentRunJournal
from ..model_capabilities import ModelCapabilityProfile
from ..reasoning import ReasoningState
from ..task_budget import TaskBudgetExceeded, prepay_task_llm_calls
from .run_input import AgentRunRequest
from .step_models import FunctionCallingStepOutcome, FunctionCallingStepState
from .types import ExecutionOutcome

logger = get_logger(__name__)


class FunctionCallingLoopRunner:
    """Run the LLM/tool loop after the host has resolved public call inputs."""

    def __init__(self, host: Any) -> None:
        self._host = host

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
        await self._start_journal(state, run_input)
        capability_outcome = await self._prepare_model_capabilities(
            state=state,
            run_input=run_input,
            control=control,
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
            await self._record_effective_context(
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
            step_outcome = await self._execute_step(
                state=state,
                run_input=run_input,
                requested_thinking_depth=state.reasoning_state.requested_depth,
                thinking_depth=self._resolve_effective_reasoning_depth(state),
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

    async def _start_journal(
        self,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
    ) -> None:
        journal = AgentRunJournal(
            run_id=run_input.run_id,
            turn_id=run_input.turn_id,
            session_id=run_input.session_id,
            user_id=run_input.user_id,
            store=getattr(self._host, "runtime_trace_store", None),
        )
        state.journal = journal
        if run_input.checkpoint is not None:
            await journal.resume()
            await journal.append(
                AgentRunEventType.RUN_RESUMED,
                step_index=state.iteration,
                payload={
                    "checkpoint_reason": run_input.checkpoint.reason,
                    "checkpoint_note": run_input.checkpoint.note,
                    "reasoning_state": state.reasoning_state.to_dict(),
                    "repair_iterations": state.repair_iterations,
                    "evidence": [item.to_ref().to_dict() for item in state.tool_evidence],
                },
            )
            return
        tool_schema_hashes = {
            str(tool.get("function", {}).get("name") or ""): stable_hash(tool)
            for tool in state.tools
            if str(tool.get("function", {}).get("name") or "")
        }
        model_context = getattr(self._host, "_active_model_context", None)
        await journal.record_manifest(
            RunContextManifest(
                run_id=run_input.run_id,
                turn_id=run_input.turn_id,
                session_id=run_input.session_id,
                user_id=run_input.user_id,
                prompt_assembly_version="unified-agent-v1",
                system_prompt_hash=stable_hash(state.effective_system_prompt),
                system_prompt_size_bytes=len(state.effective_system_prompt.encode("utf-8")),
                message_fingerprints=message_fingerprints(state.messages),
                tool_catalog=tuple(state.selected_tool_names),
                tool_schema_hashes=tool_schema_hashes,
                context_source_refs=context_source_refs(run_input.context_sources),
                provider=str(getattr(model_context, "provider_id", "unknown")),
                model=str(getattr(model_context, "model_id", "unknown")),
                reasoning_policy=run_input.reasoning_policy.to_dict(),
                created_at_ms=int(time.time() * 1000),
            )
        )
        await journal.append(
            AgentRunEventType.RUN_STARTED,
            payload={
                "execution_preset": run_input.execution_preset,
                "parent_run_id": run_input.parent_run_id,
            },
        )
        await journal.append(
            AgentRunEventType.CONTEXT_PREPARED,
            payload={
                "message_count": len(state.messages),
                "tool_count": len(state.selected_tool_names),
            },
        )
        await journal.append(
            AgentRunEventType.CAPABILITIES_RESOLVED,
            payload=dict(run_input.capability_resolution),
        )
        await journal.append(
            AgentRunEventType.REASONING_POLICY_RESOLVED,
            payload={
                **run_input.reasoning_policy.to_dict(),
                **state.reasoning_state.to_dict(),
            },
        )

    async def _prepare_model_capabilities(
        self,
        *,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
        control: RunControl,
    ) -> ExecutionOutcome | None:
        profile = run_input.model_capabilities or ModelCapabilityProfile.from_model_context(
            getattr(self._host, "_active_model_context", None)
        )
        required_tools = tuple(
            str(name).strip()
            for name in run_input.capability_resolution.get("required_tools", [])
            if str(name).strip()
        )
        if required_tools and not profile.supports_tool_calls:
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason="tool_calls_unsupported",
                error_text=_model_capability_error("tool_calls_unsupported"),
                iterations=state.iteration,
            )
        has_images = _messages_contain_images(state.messages)
        issue = profile.validate_run(
            has_images=has_images,
            tool_count=len(state.selected_tool_names),
        )
        if issue is None:
            return None
        if issue != "attachment_observation_required":
            return ExecutionOutcome(
                status="suspended" if issue == "attachments_unsupported" else "failed",
                content="",
                failure_reason=issue,
                error_text=_model_capability_error(issue),
                iterations=state.iteration,
            )
        return await self._ground_attachments_without_tools(
            state=state,
            run_input=run_input,
            control=control,
        )

    async def _ground_attachments_without_tools(
        self,
        *,
        state: FunctionCallingStepState,
        run_input: AgentRunRequest,
        control: RunControl,
    ) -> ExecutionOutcome | None:
        grounding_prompt = (
            f"{state.effective_system_prompt}\n\n"
            "Attachment grounding step: inspect only the attached images. Return a compact "
            "JSON object with keys summary, visible_facts, uncertainty, and attachment_refs. "
            "Do not solve the broader task and do not expose hidden reasoning."
        )
        await self._record_effective_context(
            state,
            mode="attachment_grounding",
            step_index=state.iteration,
            system_prompt=grounding_prompt,
            messages=state.messages,
            tools=[],
        )
        try:
            async with stream_scope(None):
                response = await self._host._call_llm_without_tools(
                    system_prompt=grounding_prompt,
                    messages=state.messages,
                    thinking_depth=self._resolve_effective_reasoning_depth(state),
                    json_mode=True,
                    timeout_seconds=run_input.llm_timeout_seconds,
                    session_id=run_input.session_id,
                    turn_id=run_input.turn_id,
                    execution_preset=run_input.execution_preset,
                    execution_agent_id=run_input.execution_agent_id,
                    iteration=0,
                    control=control,
                )
        except Exception as exc:
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason="attachment_observation_failed",
                error_text=self._host._format_exception_trace_text(exc),
                iterations=state.iteration,
            )
        observation = _normalize_attachment_observation(response.get("content"))
        observation_message = {
            "role": "user",
            "content": (
                "[Runtime attachment observation]\n"
                f"{json.dumps(observation, ensure_ascii=False, sort_keys=True)}\n"
                "Use this sourced observation in place of the raw images for subsequent tool steps."
            ),
        }
        state.messages = _strip_image_blocks(state.messages)
        state.messages.append(observation_message)
        self._host._current_messages = state.messages
        if state.journal is not None:
            await state.journal.append(
                AgentRunEventType.ATTACHMENT_OBSERVED,
                step_index=0,
                payload={
                    "observation_hash": stable_hash(observation),
                    "observation_size_bytes": len(
                        json.dumps(observation, ensure_ascii=False, default=str).encode("utf-8")
                    ),
                },
            )
        return None

    async def _record_effective_context(
        self,
        state: FunctionCallingStepState,
        *,
        mode: str,
        step_index: int,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> None:
        if state.journal is None:
            return
        await state.journal.append(
            AgentRunEventType.CONTEXT_PREPARED,
            step_index=step_index,
            payload=effective_context_fingerprint(
                mode=mode,
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                reasoning_state=(
                    state.reasoning_state.to_dict() if state.reasoning_state is not None else {}
                ),
            ),
        )

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
            state.persona_task_clamp_applied = checkpoint.persona_task_clamp_applied
        state.run_plan_reader = run_input.run_plan_reader
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

    async def _record_terminal_outcome(
        self,
        state: FunctionCallingStepState,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcome:
        if state.journal is None:
            return outcome
        event_type = {
            "completed": AgentRunEventType.RUN_COMPLETED,
            "cancelled": AgentRunEventType.RUN_CANCELLED,
            "suspended": AgentRunEventType.RUN_SUSPENDED,
            "detached": AgentRunEventType.RUN_SUSPENDED,
            "blocked": AgentRunEventType.RUN_BLOCKED,
        }.get(outcome.status, AgentRunEventType.RUN_FAILED)
        await state.journal.append(
            event_type,
            step_index=state.iteration,
            payload={
                "status": outcome.status,
                "failure_reason": outcome.failure_reason,
                "evidence": [item.to_ref().to_dict() for item in state.tool_evidence],
                "reasoning_state": (
                    state.reasoning_state.to_dict() if state.reasoning_state is not None else {}
                ),
            },
        )
        return outcome

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


def _messages_contain_images(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        if any(
            isinstance(block, dict)
            and str(block.get("type") or "") in {"image", "image_url", "input_image"}
            for block in content
        ):
            return True
    return False


def _strip_image_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for message in messages:
        cloned = dict(message)
        content = cloned.get("content")
        if isinstance(content, list):
            blocks = [
                dict(block) if isinstance(block, dict) else block
                for block in content
                if not (
                    isinstance(block, dict)
                    and str(block.get("type") or "") in {"image", "image_url", "input_image"}
                )
            ]
            cloned["content"] = blocks
        stripped.append(cloned)
    return stripped


def _normalize_attachment_observation(content: Any) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {
            "summary": "The model returned no attachment observation.",
            "visible_facts": [],
            "uncertainty": ["empty_model_observation"],
            "attachment_refs": [],
        }
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = {"summary": text}
    if not isinstance(decoded, dict):
        decoded = {"summary": text}
    return {
        "summary": str(decoded.get("summary") or "").strip(),
        "visible_facts": list(decoded.get("visible_facts") or []),
        "uncertainty": list(decoded.get("uncertainty") or []),
        "attachment_refs": list(decoded.get("attachment_refs") or []),
    }


def _model_capability_error(reason_code: str) -> str:
    return {
        "attachments_unsupported": (
            "The selected model cannot inspect the attached images. Choose a vision-capable "
            "model or remove the attachments."
        ),
        "tool_calls_unsupported": (
            "The selected model cannot execute the capabilities required by this run."
        ),
        "tool_schema_limit_exceeded": (
            "The initial capability set exceeds the selected model's tool-schema limit."
        ),
    }.get(reason_code, "The selected model does not support this run shape.")


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
