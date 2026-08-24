"""Fallback final-response flow for function-calling execution."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from ....config.models import ThinkingDepth
from ...cancel import CancelToken, null_cancel_token
from magi.control.run_control import RunControl
from ..contracts import AgentRunEventType
from ..context_fingerprint import effective_context_fingerprint
from .step_executor import FunctionCallingStepState
from .types import ExecutionOutcome

logger = logging.getLogger(__name__)
_FallbackStepResult = TypeVar("_FallbackStepResult")


class FallbackHostProtocol(Protocol):
    async def _emit_loop_event(self, payload: dict[str, Any]) -> None: ...

    def _build_final_response_system_prompt(
        self,
        system_prompt: str,
        *,
        strict_plain_text: bool = False,
    ) -> str: ...

    def _build_final_response_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        force_plain_text: bool = False,
    ) -> list[dict[str, Any]]: ...

    async def _call_llm_without_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        execution_preset: str = "unknown",
        execution_agent_id: str = "chat_agent",
        iteration: int | None = None,
        control: RunControl | None = None,
    ) -> dict[str, Any]: ...

    def _format_exception_trace_text(self, exc: Exception, *, max_length: int = 600) -> str: ...

    async def _complete_iteration_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        execution_agent_id: str,
        started_at_ms: int | None,
        status: str,
        result_preview: str | None = None,
        error_text: str | None = None,
    ) -> None: ...

    def _classify_exception_failure(self, exc: Exception) -> str: ...

    async def _persist_llm_trace(self, **kwargs: Any) -> None: ...

    def _classify_final_failure(
        self,
        tool_failures: list[dict[str, Any]],
        all_tools_failed: bool,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class FallbackExecutionContext:
    user_id: str
    session_id: str | None
    run_id: str
    run_revision: int
    turn_id: str | None
    execution_preset: str
    execution_agent_id: str
    execution_workspace: str | None
    llm_timeout_seconds: float | None
    final_response_json_mode: bool
    final_response_reason: str
    thinking_depth: ThinkingDepth
    control: RunControl | None


def _fallback_event_payload(
    context: FallbackExecutionContext,
    *,
    stage: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "stage": stage,
        **extra,
        "user_id": context.user_id,
        "session_id": context.session_id,
        "turn_id": context.turn_id,
        "execution_preset": context.execution_preset,
        "execution_agent_id": context.execution_agent_id,
    }


async def _record_fallback_call_failure(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    exc: Exception,
    *,
    complete_iteration_trace: bool,
) -> ExecutionOutcome:
    error_text = host._format_exception_trace_text(exc)
    if complete_iteration_trace:
        await host._complete_iteration_trace(
            turn_id=context.turn_id,
            iteration=state.iteration,
            execution_agent_id=context.execution_agent_id,
            started_at_ms=None,
            status="failed",
            error_text=error_text,
        )
    return ExecutionOutcome(
        status="failed",
        content="",
        failure_reason=host._classify_exception_failure(exc),
        error_text=error_text,
        tool_failures=list(state.tool_failures),
        iterations=state.iteration,
    )


async def _run_fallback_step(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    step: Callable[[], Awaitable[_FallbackStepResult]],
    *,
    complete_iteration_trace: bool,
) -> tuple[_FallbackStepResult | None, ExecutionOutcome | None]:
    try:
        return await step(), None
    except Exception as exc:
        failure = await _record_fallback_call_failure(
            host,
            state,
            context,
            exc,
            complete_iteration_trace=complete_iteration_trace,
        )
        return None, failure


async def _call_fallback_llm(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    thinking_depth: ThinkingDepth,
) -> dict[str, Any]:
    if state.journal is not None:
        await state.journal.append(
            AgentRunEventType.CONTEXT_PREPARED,
            step_index=state.iteration,
            payload=effective_context_fingerprint(
                mode="fallback_finalization",
                system_prompt=system_prompt,
                messages=messages,
                tools=[],
                reasoning_state={
                    "requested_depth": (
                        state.reasoning_state.requested_depth.value
                        if state.reasoning_state is not None
                        else thinking_depth.value
                    ),
                    "effective_depth": thinking_depth.value,
                },
            ),
        )
    response = await host._call_llm_without_tools(
        system_prompt=system_prompt,
        messages=messages,
        thinking_depth=thinking_depth,
        json_mode=context.final_response_json_mode,
        timeout_seconds=context.llm_timeout_seconds,
        session_id=context.session_id,
        turn_id=context.turn_id,
        execution_preset=context.execution_preset,
        execution_agent_id=context.execution_agent_id,
        iteration=state.iteration,
        control=context.control,
    )
    if state.journal is not None:
        assistant_message = response.get("assistant_message")
        await state.journal.append(
            AgentRunEventType.MODEL_OUTPUT,
            step_index=state.iteration,
            payload={
                "mode": "fallback_finalization",
                "assistant_message": (
                    dict(assistant_message) if isinstance(assistant_message, dict) else None
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
    return response


async def _force_plain_text_retry_if_needed(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    final_response: dict[str, Any],
) -> dict[str, Any]:
    if not final_response.get("tool_calls"):
        return final_response

    logger.warning(
        "[FunctionCalling] Final no-tools response still returned tool calls; forcing plain-text retry"
    )
    await host._emit_loop_event(
        _fallback_event_payload(context, stage="fallback_forced_plain_text_retry")
    )
    return await _call_fallback_llm(
        host,
        state,
        context,
        system_prompt=host._build_final_response_system_prompt(
            state.effective_system_prompt,
            strict_plain_text=True,
        ),
        messages=host._build_final_response_messages(
            state.messages,
            force_plain_text=True,
        ),
        thinking_depth=ThinkingDepth.NONE,
    )


async def _request_initial_fallback_response(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
) -> tuple[str, dict[str, Any]]:
    final_system_prompt = host._build_final_response_system_prompt(state.effective_system_prompt)
    final_response = await _call_fallback_llm(
        host,
        state,
        context,
        system_prompt=final_system_prompt,
        messages=host._build_final_response_messages(state.messages),
        thinking_depth=context.thinking_depth,
    )
    return final_system_prompt, final_response


async def _completed_fallback_outcome(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    *,
    final_content: str,
) -> ExecutionOutcome:
    await host._complete_iteration_trace(
        turn_id=context.turn_id,
        iteration=state.iteration,
        execution_agent_id=context.execution_agent_id,
        started_at_ms=None,
        status="completed",
        result_preview=final_content[:240],
    )
    return ExecutionOutcome(
        status="completed",
        content=final_content,
        tool_failures=list(state.tool_failures),
        attachments=list(state.chat_attachments),
        message_payload=dict(state.message_payload),
        context_usage=(
            dict(state.latest_context_usage)
            if isinstance(state.latest_context_usage, dict)
            else None
        ),
        iterations=state.iteration,
    )


async def _empty_fallback_failure_outcome(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
) -> ExecutionOutcome:
    failure_reason = host._classify_final_failure(
        state.tool_failures,
        state.all_tools_failed,
    )
    await host._complete_iteration_trace(
        turn_id=context.turn_id,
        iteration=state.iteration,
        execution_agent_id=context.execution_agent_id,
        started_at_ms=None,
        status="failed",
        error_text=failure_reason,
    )
    return ExecutionOutcome(
        status="failed",
        content="",
        failure_reason=failure_reason,
        tool_failures=list(state.tool_failures),
        iterations=state.iteration,
    )


async def _initial_fallback_or_failure(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
) -> tuple[tuple[str, dict[str, Any]] | None, ExecutionOutcome | None]:
    return await _run_fallback_step(
        host,
        state,
        context,
        lambda: _request_initial_fallback_response(host, state, context),
        complete_iteration_trace=True,
    )


async def _plain_text_retry_or_failure(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    final_response: dict[str, Any],
) -> tuple[dict[str, Any] | None, ExecutionOutcome | None]:
    return await _run_fallback_step(
        host,
        state,
        context,
        lambda: _force_plain_text_retry_if_needed(host, state, context, final_response),
        complete_iteration_trace=False,
    )


async def _complete_fallback_response(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    final_response: dict[str, Any],
) -> ExecutionOutcome:
    if isinstance(final_response.get("context_usage"), dict):
        state.latest_context_usage = dict(final_response["context_usage"])
    await host._emit_loop_event(
        _fallback_event_payload(
            context,
            stage="fallback_final_response",
            response_preview=str(final_response.get("content", ""))[:500],
            llm_trace=final_response.get("llm_trace"),
        )
    )
    await host._persist_llm_trace(
        turn_id=context.turn_id,
        iteration=state.iteration,
        stage="fallback_final_response",
        execution_agent_id=context.execution_agent_id,
        llm_trace=final_response.get("llm_trace"),
        response_preview=str(final_response.get("content", "")),
    )

    final_content = str(final_response.get("content", ""))
    if final_content.strip():
        return await _completed_fallback_outcome(
            host,
            state,
            context,
            final_content=final_content,
        )

    return await _empty_fallback_failure_outcome(host, state, context)


async def execute_fallback_response_flow(
    host: FallbackHostProtocol,
    state: FunctionCallingStepState,
    context: FallbackExecutionContext,
    *,
    cancel_token: CancelToken | None,
) -> ExecutionOutcome:
    logger.info(
        "[FunctionCalling] Final response required | reason=%s",
        context.final_response_reason,
    )
    token = cancel_token if cancel_token is not None else null_cancel_token()
    if await token.is_cancelled():
        return ExecutionOutcome(
            status="cancelled",
            content="",
            iterations=state.iteration,
        )

    await host._emit_loop_event(
        _fallback_event_payload(
            context,
            stage=context.final_response_reason,
            iteration=state.iteration,
        )
    )
    initial_response, failure = await _initial_fallback_or_failure(host, state, context)
    if failure is not None:
        return failure
    assert initial_response is not None
    _, final_response = initial_response

    retry_response, failure = await _plain_text_retry_or_failure(
        host, state, context, final_response
    )
    if failure is not None:
        return failure
    assert retry_response is not None
    final_response = retry_response

    return await _complete_fallback_response(host, state, context, final_response)


__all__ = [
    "FallbackExecutionContext",
    "FallbackHostProtocol",
    "execute_fallback_response_flow",
]
