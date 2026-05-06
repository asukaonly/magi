"""Fallback final-response pass for function-calling execution."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, cast

from ....config.models import ThinkingDepth
from ...cancel import CancelToken, null_cancel_token
from .step_executor import FunctionCallingStepState
from .types import ExecutionOutcome, ToolCall, ToolCallResult

logger = logging.getLogger(__name__)


class _FallbackPostprocessorProtocol(Protocol):
    def build_tool_message_payload(
        self,
        *,
        tool_name: str,
        result: ToolCallResult,
    ) -> dict[str, Any]: ...


class _FallbackHostProtocol(Protocol):
    postprocessor: _FallbackPostprocessorProtocol

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
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
        iteration: int | None = None,
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

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        user_id: str,
        session_id: str | None,
        turn_id: str | None,
        intent: str,
        execution_agent_id: str,
        execution_workspace: str | None,
        orchestration_strategy: dict[str, Any] | None,
        session_run_id: str | None = None,
        session_run_revision: int = 0,
        user_message: str | None = None,
        iteration: int | None = None,
    ) -> ToolCallResult: ...

    def _append_message(self, messages: list[dict[str, Any]], message: dict[str, Any]) -> None: ...

    async def _persist_tool_trace(self, **kwargs: Any) -> None: ...

    async def _persist_llm_trace(self, **kwargs: Any) -> None: ...

    def _classify_final_failure(
        self,
        tool_failures: list[dict[str, Any]],
        all_tools_failed: bool,
    ) -> str: ...


class FunctionCallingFallbackMixin:
    """Run the bounded no-tools fallback once the normal tool loop stops."""

    async def _execute_fallback_final_response(
        self,
        *,
        state: FunctionCallingStepState,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        user_id: str,
        session_id: str | None,
        session_run_id: str | None,
        session_run_revision: int,
        turn_id: str | None,
        intent: str,
        execution_agent_id: str,
        execution_workspace: str | None,
        orchestration_strategy: dict[str, Any] | None,
        llm_timeout_seconds: float | None,
        final_response_json_mode: bool,
        cancel_token: CancelToken | None = None,
    ) -> ExecutionOutcome:
        """Run the legacy no-tools fallback once the bounded step loop stops."""
        host = cast(_FallbackHostProtocol, self)
        logger.info("[FunctionCalling] Reached max iterations, getting final response")
        token = cancel_token if cancel_token is not None else null_cancel_token()
        if await token.is_cancelled():
            return ExecutionOutcome(
                status="cancelled",
                content="",
                iterations=state.iteration,
            )
        await host._emit_loop_event(
            {
                "stage": "max_iterations_reached",
                "iteration": state.iteration,
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "intent": intent,
                "execution_agent_id": execution_agent_id,
            }
        )
        try:
            final_system_prompt = host._build_final_response_system_prompt(
                state.effective_system_prompt
            )
            final_response = await host._call_llm_without_tools(
                system_prompt=final_system_prompt,
                messages=host._build_final_response_messages(state.messages),
                thinking_depth=thinking_depth,
                json_mode=final_response_json_mode,
                timeout_seconds=llm_timeout_seconds,
                session_id=session_id,
                turn_id=turn_id,
                intent=intent,
                execution_agent_id=execution_agent_id,
                iteration=state.iteration,
            )
        except Exception as exc:
            error_text = host._format_exception_trace_text(exc)
            await host._complete_iteration_trace(
                turn_id=turn_id,
                iteration=state.iteration,
                execution_agent_id=execution_agent_id,
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

        fallback_content = final_response.get("content", "")
        fallback_tool_calls = final_response.get("tool_calls") or []
        if fallback_tool_calls:
            logger.info(
                "[FunctionCalling] Fallback response returned %s tool call(s), executing rescue pass",
                len(fallback_tool_calls),
            )
            if fallback_content:
                host._append_message(
                    state.messages, {"role": "assistant", "content": fallback_content}
                )
            for tool_call in fallback_tool_calls:
                result = await host._execute_tool_call(
                    tool_call=tool_call,
                    user_id=user_id,
                    session_id=session_id,
                    session_run_id=session_run_id,
                    session_run_revision=session_run_revision,
                    turn_id=turn_id,
                    intent=intent,
                    execution_agent_id=execution_agent_id,
                    execution_workspace=execution_workspace,
                    orchestration_strategy=orchestration_strategy,
                    user_message=None,
                    iteration=state.iteration,
                )
                if not result.success:
                    state.tool_failures.append(
                        {
                            "tool_call_id": result.tool_call_id,
                            "tool_name": result.tool_name,
                            "error": result.error or "unknown error",
                            "error_code": result.error_code,
                            "execution_time": round(result.execution_time, 3),
                        }
                    )
                host._append_message(
                    state.messages,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            host.postprocessor.build_tool_message_payload(
                                tool_name=tool_call.name,
                                result=result,
                            ),
                            ensure_ascii=False,
                        ),
                    },
                )
                await host._persist_tool_trace(
                    turn_id=turn_id,
                    iteration=state.iteration,
                    execution_agent_id=execution_agent_id,
                    tool_call=tool_call,
                    result=result,
                )
            try:
                final_response = await host._call_llm_without_tools(
                    system_prompt=final_system_prompt,
                    messages=host._build_final_response_messages(
                        state.messages,
                        force_plain_text=True,
                    ),
                    thinking_depth=thinking_depth,
                    json_mode=final_response_json_mode,
                    timeout_seconds=llm_timeout_seconds,
                    session_id=session_id,
                    turn_id=turn_id,
                    intent=intent,
                    execution_agent_id=execution_agent_id,
                    iteration=state.iteration,
                )
            except Exception as exc:
                error_text = host._format_exception_trace_text(exc)
                await host._complete_iteration_trace(
                    turn_id=turn_id,
                    iteration=state.iteration,
                    execution_agent_id=execution_agent_id,
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

        if final_response.get("tool_calls") and not str(final_response.get("content", "")).strip():
            logger.warning(
                "[FunctionCalling] Final no-tools response still returned tool calls; forcing plain-text retry"
            )
            await host._emit_loop_event(
                {
                    "stage": "fallback_forced_plain_text_retry",
                    "user_id": user_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "intent": intent,
                    "execution_agent_id": execution_agent_id,
                }
            )
            try:
                final_response = await host._call_llm_without_tools(
                    system_prompt=host._build_final_response_system_prompt(
                        state.effective_system_prompt,
                        strict_plain_text=True,
                    ),
                    messages=host._build_final_response_messages(
                        state.messages,
                        force_plain_text=True,
                    ),
                    thinking_depth=ThinkingDepth.NONE,
                    json_mode=final_response_json_mode,
                    timeout_seconds=llm_timeout_seconds,
                    session_id=session_id,
                    turn_id=turn_id,
                    intent=intent,
                    execution_agent_id=execution_agent_id,
                    iteration=state.iteration,
                )
            except Exception as exc:
                return ExecutionOutcome(
                    status="failed",
                    content="",
                    failure_reason=host._classify_exception_failure(exc),
                    error_text=host._format_exception_trace_text(exc),
                    tool_failures=list(state.tool_failures),
                    iterations=state.iteration,
                )

        await host._emit_loop_event(
            {
                "stage": "fallback_final_response",
                "response_preview": str(final_response.get("content", ""))[:500],
                "llm_trace": final_response.get("llm_trace"),
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "intent": intent,
                "execution_agent_id": execution_agent_id,
            }
        )
        await host._persist_llm_trace(
            turn_id=turn_id,
            iteration=state.iteration,
            stage="fallback_final_response",
            execution_agent_id=execution_agent_id,
            llm_trace=final_response.get("llm_trace"),
            response_preview=str(final_response.get("content", "")),
        )
        final_content = str(final_response.get("content", ""))
        if final_content.strip():
            await host._complete_iteration_trace(
                turn_id=turn_id,
                iteration=state.iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=None,
                status="completed",
                result_preview=final_content[:240],
            )
            return ExecutionOutcome(
                status="completed",
                content=final_content,
                tool_failures=list(state.tool_failures),
                iterations=state.iteration,
            )

        failure_reason = host._classify_final_failure(
            state.tool_failures,
            state.all_tools_failed,
        )
        await host._complete_iteration_trace(
            turn_id=turn_id,
            iteration=state.iteration,
            execution_agent_id=execution_agent_id,
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


__all__ = ["FunctionCallingFallbackMixin"]
