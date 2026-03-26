"""Single-step execution for function-calling loops."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ...config.models import ThinkingDepth


@dataclass(slots=True)
class FunctionCallingStepState:
    """Mutable loop state shared across bounded function-calling steps."""

    messages: list[dict[str, Any]]
    effective_system_prompt: str
    tools: list[dict[str, Any]]
    iteration: int = 0
    tool_failures: list[dict[str, Any]] = field(default_factory=list)
    consecutive_failed_tool_iterations: int = 0
    all_tools_failed: bool = False


@dataclass(slots=True)
class FunctionCallingStepOutcome:
    """Result of executing one bounded function-calling step."""

    status: str
    iteration: int
    content: str = ""
    failure_reason: str | None = None


class FunctionCallingStepExecutor:
    """Execute one LLM decision and at most one tool batch."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    async def execute_step(
        self,
        *,
        state: FunctionCallingStepState,
        user_message: str,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        user_id: str,
        session_id: str | None,
        session_run_id: str | None = None,
        session_run_revision: int = 0,
        turn_id: str | None,
        intent: str,
        execution_agent_id: str,
        execution_workspace: str | None = None,
        orchestration_strategy: dict[str, Any] | None = None,
        llm_timeout_seconds: float | None = None,
    ) -> FunctionCallingStepOutcome:
        """Run one bounded loop iteration and return control to the caller."""
        state.iteration += 1
        iteration = state.iteration
        iteration_started_at_ms = await self._driver._start_iteration_trace(
            turn_id=turn_id,
            iteration=iteration,
            execution_agent_id=execution_agent_id,
        )
        await self._driver._emit_loop_event(
            {
                "stage": "iteration_started",
                "iteration": iteration,
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "intent": intent,
                "execution_agent_id": execution_agent_id,
            }
        )

        try:
            response = await self._driver._call_llm_with_tools(
                system_prompt=state.effective_system_prompt,
                messages=state.messages,
                tools=state.tools,
                thinking_depth=thinking_depth,
                timeout_seconds=llm_timeout_seconds,
                session_id=session_id,
                turn_id=turn_id,
                intent=intent,
                execution_agent_id=execution_agent_id,
            )
        except Exception as exc:
            failure_reason = self._driver._classify_exception_failure(exc)
            await self._driver._complete_iteration_trace(
                turn_id=turn_id,
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=iteration_started_at_ms,
                status="failed",
                error_text=failure_reason,
            )
            return FunctionCallingStepOutcome(
                status="failed",
                iteration=iteration,
                failure_reason=failure_reason,
            )

        assistant_message = response.get("assistant_message")
        if assistant_message:
            self._driver._append_message(state.messages, assistant_message)

        if response.get("tool_calls"):
            tool_calls = response["tool_calls"]
            await self._driver._emit_loop_event(
                {
                    "stage": "llm_requested_tools",
                    "iteration": iteration,
                    "tool_names": [tool_call.name for tool_call in tool_calls],
                    "tool_count": len(tool_calls),
                    "llm_trace": response.get("llm_trace"),
                    "user_id": user_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "intent": intent,
                    "execution_agent_id": execution_agent_id,
                }
            )
            await self._driver._persist_llm_trace(
                turn_id=turn_id,
                iteration=iteration,
                stage="llm_requested_tools",
                execution_agent_id=execution_agent_id,
                llm_trace=response.get("llm_trace"),
            )

            tool_results = []
            for tool_call in tool_calls:
                result = await self._driver._execute_tool_call(
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
                )
                tool_results.append(result)
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
                await self._driver._emit_loop_event(
                    {
                        "stage": "tool_executed",
                        "iteration": iteration,
                        "tool_name": tool_call.name,
                        "tool_call_id": tool_call.id,
                        "success": result.success,
                        "error": result.error,
                        "execution_time": result.execution_time,
                        "user_id": user_id,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "intent": intent,
                        "execution_agent_id": execution_agent_id,
                    }
                )
                await self._driver._emit_tool_result(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    user_message=user_message,
                    intent=intent,
                    iteration=iteration,
                    tool_call=tool_call,
                    result=result,
                )
                await self._driver._persist_tool_trace(
                    turn_id=turn_id,
                    iteration=iteration,
                    execution_agent_id=execution_agent_id,
                    tool_call=tool_call,
                    result=result,
                )
                self._driver._append_message(
                    state.messages,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            self._driver.postprocessor.build_tool_message_payload(
                                tool_name=tool_call.name,
                                result=result,
                            ),
                            ensure_ascii=False,
                        ),
                    },
                )

            if all(not result.success for result in tool_results):
                state.consecutive_failed_tool_iterations += 1
                replan_allowed = self._driver._should_allow_replan_after_failed_iteration(
                    tool_results,
                    consecutive_failed_tool_iterations=state.consecutive_failed_tool_iterations,
                )
                failed_details = [
                    {
                        "tool_call_id": result.tool_call_id,
                        "tool_name": result.tool_name,
                        "error": result.error or "unknown error",
                        "error_code": result.error_code,
                        "execution_time": round(result.execution_time, 3),
                    }
                    for result in tool_results
                ]
                await self._driver._emit_loop_event(
                    {
                        "stage": "iteration_all_tools_failed",
                        "iteration": iteration,
                        "replan_allowed": replan_allowed,
                        "consecutive_failed_iterations": state.consecutive_failed_tool_iterations,
                        "details": failed_details,
                        "user_id": user_id,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "intent": intent,
                        "execution_agent_id": execution_agent_id,
                    }
                )
                if replan_allowed:
                    await self._driver._complete_iteration_trace(
                        turn_id=turn_id,
                        iteration=iteration,
                        execution_agent_id=execution_agent_id,
                        started_at_ms=iteration_started_at_ms,
                        status="completed",
                        result_preview="All requested tools failed",
                    )
                    return FunctionCallingStepOutcome(status="continue", iteration=iteration)
                state.all_tools_failed = True
                await self._driver._complete_iteration_trace(
                    turn_id=turn_id,
                    iteration=iteration,
                    execution_agent_id=execution_agent_id,
                    started_at_ms=iteration_started_at_ms,
                    status="failed",
                    error_text="All requested tools failed",
                )
                return FunctionCallingStepOutcome(
                    status="failed",
                    iteration=iteration,
                    failure_reason=self._driver._classify_final_failure(
                        state.tool_failures,
                        state.all_tools_failed,
                    ),
                )

            state.consecutive_failed_tool_iterations = 0
            await self._driver._complete_iteration_trace(
                turn_id=turn_id,
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=iteration_started_at_ms,
                status="completed",
                result_preview=f"Executed {len(tool_results)} tool call(s)",
            )
            return FunctionCallingStepOutcome(status="continue", iteration=iteration)

        if response.get("content"):
            final_content = str(response["content"])
            if not final_content.strip():
                return FunctionCallingStepOutcome(status="failed", iteration=iteration, failure_reason="Empty final response")
            await self._driver._persist_llm_trace(
                turn_id=turn_id,
                iteration=iteration,
                stage="final_response",
                execution_agent_id=execution_agent_id,
                llm_trace=response.get("llm_trace"),
                response_preview=final_content,
            )
            await self._driver._emit_loop_event(
                {
                    "stage": "final_response",
                    "iteration": iteration,
                    "response_preview": final_content[:500],
                    "llm_trace": response.get("llm_trace"),
                    "user_id": user_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "intent": intent,
                    "execution_agent_id": execution_agent_id,
                }
            )
            await self._driver._complete_iteration_trace(
                turn_id=turn_id,
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=iteration_started_at_ms,
                status="completed",
                result_preview=final_content[:240],
            )
            return FunctionCallingStepOutcome(
                status="completed",
                iteration=iteration,
                content=final_content,
            )

        await self._driver._complete_iteration_trace(
            turn_id=turn_id,
            iteration=iteration,
            execution_agent_id=execution_agent_id,
            started_at_ms=iteration_started_at_ms,
            status="failed",
            error_text="Unexpected function-calling response",
        )
        return FunctionCallingStepOutcome(
            status="failed",
            iteration=iteration,
            failure_reason="Unexpected function-calling response",
        )
