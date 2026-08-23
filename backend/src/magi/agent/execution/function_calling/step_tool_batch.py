"""Tool-batch execution for one function-calling step."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ....llm.streaming_events import LLMStreamEvent, emit_stream_event
from ...cancel import CancelToken
from .step_models import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
    StepExecutionContext,
)
from .types import ToolCallResult

MAX_RUNTIME_STATUS_CHARS = 2_000


def _normalize_runtime_status_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= MAX_RUNTIME_STATUS_CHARS:
        return text
    return f"{text[:MAX_RUNTIME_STATUS_CHARS].rstrip()}..."


@dataclass(slots=True)
class _ToolExecutionRecord:
    """One requested tool call and its normalized execution result."""

    tool_call: Any
    result: ToolCallResult
    fingerprint: str


class FunctionCallingToolBatchExecutor:
    """Execute and record tool calls requested by one LLM step."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    async def handle_tool_call_response(
        self,
        *,
        state: FunctionCallingStepState,
        response: dict[str, Any],
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
        cancel_token: CancelToken,
    ) -> FunctionCallingStepOutcome:
        tool_calls = response["tool_calls"]
        await self._record_tool_request(
            tool_calls=tool_calls,
            response=response,
            ctx=ctx,
            iteration=iteration,
        )
        records, terminal_outcome = await self._execute_tool_batch(
            state=state,
            tool_calls=tool_calls,
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
            cancel_token=cancel_token,
        )
        if terminal_outcome is not None:
            return terminal_outcome

        tool_results = [record.result for record in records]
        await self._apply_tool_batch_side_effects(
            state=state,
            tool_results=tool_results,
            ctx=ctx,
            iteration=iteration,
        )
        return await self._finish_tool_batch(
            state=state,
            tool_results=tool_results,
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
        )

    async def _finish_tool_batch(
        self,
        *,
        state: FunctionCallingStepState,
        tool_results: list[ToolCallResult],
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
    ) -> FunctionCallingStepOutcome:
        if all(not result.success for result in tool_results):
            return await self._handle_all_tools_failed(
                state=state,
                tool_results=tool_results,
                ctx=ctx,
                iteration=iteration,
                iteration_started_at_ms=iteration_started_at_ms,
            )

        return await self._complete_successful_tool_batch(
            state=state,
            tool_count=len(tool_results),
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
        )

    async def _record_tool_request(
        self,
        *,
        tool_calls: list[Any],
        response: dict[str, Any],
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        status_text = _normalize_runtime_status_text(response.get("content"))
        if status_text:
            await emit_stream_event(
                LLMStreamEvent(
                    kind="status_update",
                    text=status_text,
                    source="assistant_tool_call",
                    step_label="tool_call_narration",
                )
            )
        await self._driver._emit_loop_event(
            {
                "stage": "llm_requested_tools",
                "iteration": iteration,
                "tool_names": [tool_call.name for tool_call in tool_calls],
                "tool_count": len(tool_calls),
                "llm_trace": response.get("llm_trace"),
                "context_usage": response.get("context_usage"),
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
                "intent": ctx.intent,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )
        await self._driver._persist_llm_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            stage="llm_requested_tools",
            execution_agent_id=ctx.execution_agent_id,
            llm_trace=response.get("llm_trace"),
            response_preview=f"Requested tools: {', '.join(tc.name for tc in tool_calls)}",
            request_preview=(ctx.user_message or "")[:240],
        )

    async def _complete_successful_tool_batch(
        self,
        *,
        state: FunctionCallingStepState,
        tool_count: int,
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
    ) -> FunctionCallingStepOutcome:
        state.consecutive_failed_tool_iterations = 0
        await self._driver._complete_iteration_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            execution_agent_id=ctx.execution_agent_id,
            started_at_ms=iteration_started_at_ms,
            status="completed",
            result_preview=f"Executed {tool_count} tool call(s)",
        )
        return FunctionCallingStepOutcome(status="continue", iteration=iteration)

    async def _execute_tool_batch(
        self,
        *,
        state: FunctionCallingStepState,
        tool_calls: list[Any],
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
        cancel_token: CancelToken,
    ) -> tuple[list[_ToolExecutionRecord], FunctionCallingStepOutcome | None]:
        records: list[_ToolExecutionRecord] = []
        for tool_call in tool_calls:
            if await cancel_token.is_cancelled():
                return records, await self._cancel_tool_batch(
                    ctx=ctx,
                    iteration=iteration,
                    iteration_started_at_ms=iteration_started_at_ms,
                    error_text="Run cancelled before tool execution",
                )
            record = await self._execute_one_tool_call(
                state=state,
                tool_call=tool_call,
                ctx=ctx,
                iteration=iteration,
                cancel_token=cancel_token,
            )
            records.append(record)
            terminal_outcome = await self._record_tool_execution(
                state=state,
                record=record,
                ctx=ctx,
                iteration=iteration,
                iteration_started_at_ms=iteration_started_at_ms,
                cancel_token=cancel_token,
            )
            if terminal_outcome is not None:
                return records, terminal_outcome
        return records, None

    async def _execute_one_tool_call(
        self,
        *,
        state: FunctionCallingStepState,
        tool_call: Any,
        ctx: StepExecutionContext,
        iteration: int,
        cancel_token: CancelToken,
    ) -> _ToolExecutionRecord:
        raw_arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        fingerprint = self._driver._tool_call_fingerprint(tool_call.name, raw_arguments)
        if tool_call.name in state.suppressed_tool_names:
            repeated_blocker = tool_call.name in state.repeated_blocker_tool_names
            return _ToolExecutionRecord(
                tool_call=tool_call,
                fingerprint=fingerprint,
                result=ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    success=False,
                    error=(
                        "Tool blocked after the same non-transient failure occurred "
                        "multiple times in this run. Choose a different tool or finish "
                        "with the evidence already gathered."
                        if repeated_blocker
                        else "Tool is unavailable for the rest of this run after a terminal error."
                    ),
                    error_code=(
                        "REPEATED_TOOL_BLOCKER" if repeated_blocker else "TOOL_SUPPRESSED"
                    ),
                ),
            )
        if fingerprint in state.failed_tool_call_fingerprints:
            return _ToolExecutionRecord(
                tool_call=tool_call,
                fingerprint=fingerprint,
                result=ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    success=False,
                    error=(
                        "Repeated failed tool call blocked: choose corrected arguments, "
                        "a narrower scope, or a different tool."
                    ),
                    error_code="REPEATED_FAILED_TOOL_CALL",
                ),
            )

        result = await self._driver._execute_tool_call(
            tool_call=tool_call,
            user_message=ctx.user_message,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            session_run_id=ctx.session_run_id,
            session_run_revision=ctx.session_run_revision,
            turn_id=ctx.turn_id,
            intent=ctx.intent,
            execution_agent_id=ctx.execution_agent_id,
            iteration=iteration,
            execution_workspace=ctx.execution_workspace,
            cancel_token=cancel_token,
            recent_messages=state.messages,
            route_decision=ctx.route_decision,
        )
        return _ToolExecutionRecord(
            tool_call=tool_call,
            fingerprint=fingerprint,
            result=result,
        )

    async def _record_tool_execution(
        self,
        *,
        state: FunctionCallingStepState,
        record: _ToolExecutionRecord,
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
        cancel_token: CancelToken,
    ) -> FunctionCallingStepOutcome | None:
        result = record.result
        if result.error_code == "CANCELLED" or await cancel_token.is_cancelled():
            return await self._cancel_tool_batch(
                ctx=ctx,
                iteration=iteration,
                iteration_started_at_ms=iteration_started_at_ms,
                error_text=result.error or "Run cancelled during tool execution",
            )
        if not result.success:
            self._record_tool_failure(state, record)
        await self._publish_tool_execution_record(
            state=state,
            record=record,
            ctx=ctx,
            iteration=iteration,
        )
        return None

    async def _publish_tool_execution_record(
        self,
        *,
        state: FunctionCallingStepState,
        record: _ToolExecutionRecord,
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        result = record.result
        await self._driver._emit_loop_event(
            {
                "stage": "tool_executed",
                "iteration": iteration,
                "tool_name": record.tool_call.name,
                "tool_call_id": record.tool_call.id,
                "success": result.success,
                "error": result.error,
                "execution_time": result.execution_time,
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
                "intent": ctx.intent,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )
        await self._driver._emit_tool_result(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            user_message=ctx.user_message,
            intent=ctx.intent,
            iteration=iteration,
            tool_call=record.tool_call,
            result=result,
        )
        await self._driver._persist_tool_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            execution_agent_id=ctx.execution_agent_id,
            tool_call=record.tool_call,
            result=result,
        )
        self._append_tool_message(state, record)

    async def _apply_tool_batch_side_effects(
        self,
        *,
        state: FunctionCallingStepState,
        tool_results: list[ToolCallResult],
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        new_chat_attachments = self._driver._extract_chat_attachments_from_tool_results(
            tool_results
        )
        state.chat_attachments.extend(new_chat_attachments)
        if new_chat_attachments and state.allow_attachment_grounding:
            state.messages = self._driver.inject_prepared_attachment_grounding_message(
                messages=state.messages,
                attachments=new_chat_attachments,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
            )
        state.message_payload = self._driver._merge_assistant_message_payload(
            state.message_payload,
            self._driver._extract_assistant_message_payload_from_tool_results(tool_results),
        )
        expanded_tools = self._driver._apply_tool_expansion_from_results(
            state=state,
            tool_results=tool_results,
        )
        await self._emit_suppression_and_expansion_events(
            state=state,
            tool_results=tool_results,
            expanded_tools=expanded_tools,
            ctx=ctx,
            iteration=iteration,
        )

    async def _emit_suppression_and_expansion_events(
        self,
        *,
        state: FunctionCallingStepState,
        tool_results: list[ToolCallResult],
        expanded_tools: list[str],
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        newly_suppressed = {
            result.tool_name
            for result in tool_results
            if result.tool_name in state.suppressed_tool_names
        }
        if newly_suppressed:
            await self._emit_tool_suppression_event(
                state=state,
                tool_results=tool_results,
                newly_suppressed=newly_suppressed,
                ctx=ctx,
                iteration=iteration,
            )
        if expanded_tools:
            await self._emit_tool_expansion_event(
                state=state,
                expanded_tools=expanded_tools,
                ctx=ctx,
                iteration=iteration,
            )

    async def _emit_tool_suppression_event(
        self,
        *,
        state: FunctionCallingStepState,
        tool_results: list[ToolCallResult],
        newly_suppressed: set[str],
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        state.tools = [
            tool
            for tool in state.tools
            if str(tool.get("function", {}).get("name", "")) not in state.suppressed_tool_names
        ]
        state.selected_tool_names = [
            name for name in state.selected_tool_names if name not in state.suppressed_tool_names
        ]
        await self._driver._emit_loop_event(
            {
                "stage": (
                    "tools_suppressed_after_repeated_blocker"
                    if newly_suppressed & state.repeated_blocker_tool_names
                    else "tools_suppressed_after_terminal_error"
                ),
                "iteration": iteration,
                "tool_names": sorted(newly_suppressed),
                "error_codes": self._suppressed_error_codes(tool_results, newly_suppressed),
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
                "intent": ctx.intent,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )

    async def _emit_tool_expansion_event(
        self,
        *,
        state: FunctionCallingStepState,
        expanded_tools: list[str],
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        await self._driver._emit_loop_event(
            {
                "stage": "toolset_expanded",
                "iteration": iteration,
                "append_tools": list(expanded_tools),
                "tool_count": len(state.selected_tool_names),
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
                "intent": ctx.intent,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )

    def _suppressed_error_codes(
        self,
        tool_results: list[ToolCallResult],
        newly_suppressed: set[str],
    ) -> list[str]:
        return sorted(
            {
                str(result.error_code or "").strip()
                for result in tool_results
                if result.tool_name in newly_suppressed
                and str(result.error_code or "").strip()
            }
        )

    async def _handle_all_tools_failed(
        self,
        *,
        state: FunctionCallingStepState,
        tool_results: list[ToolCallResult],
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
    ) -> FunctionCallingStepOutcome:
        state.consecutive_failed_tool_iterations += 1
        repeated_blocker_detected = any(
            result.tool_name in state.repeated_blocker_tool_names for result in tool_results
        )
        replan_allowed = self._driver._should_allow_replan_after_failed_iteration(
            tool_results,
            consecutive_failed_tool_iterations=state.consecutive_failed_tool_iterations,
            available_tools=state.tools,
        )
        if repeated_blocker_detected and not state.tools:
            replan_allowed = False
        await self._emit_all_tools_failed_event(
            state=state,
            tool_results=tool_results,
            replan_allowed=replan_allowed,
            repeated_blocker_detected=repeated_blocker_detected,
            ctx=ctx,
            iteration=iteration,
        )
        if replan_allowed:
            return await self._continue_after_all_tools_failed(
                ctx=ctx,
                iteration=iteration,
                iteration_started_at_ms=iteration_started_at_ms,
            )

        return await self._fail_after_all_tools_failed(
            state=state,
            ctx=ctx,
            iteration=iteration,
            iteration_started_at_ms=iteration_started_at_ms,
            repeated_blocker_detected=repeated_blocker_detected,
        )

    async def _emit_all_tools_failed_event(
        self,
        *,
        state: FunctionCallingStepState,
        tool_results: list[ToolCallResult],
        replan_allowed: bool,
        repeated_blocker_detected: bool,
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        await self._driver._emit_loop_event(
            {
                "stage": "iteration_all_tools_failed",
                "iteration": iteration,
                "replan_allowed": replan_allowed,
                "consecutive_failed_iterations": state.consecutive_failed_tool_iterations,
                "repeated_blocker_detected": repeated_blocker_detected,
                "details": [self._build_tool_failure_summary(result) for result in tool_results],
                "user_id": ctx.user_id,
                "session_id": ctx.session_id,
                "turn_id": ctx.turn_id,
                "intent": ctx.intent,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )

    async def _continue_after_all_tools_failed(
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
            status="completed",
            result_preview="All requested tools failed",
        )
        return FunctionCallingStepOutcome(status="continue", iteration=iteration)

    async def _fail_after_all_tools_failed(
        self,
        *,
        state: FunctionCallingStepState,
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
        repeated_blocker_detected: bool,
    ) -> FunctionCallingStepOutcome:
        state.all_tools_failed = True
        await self._driver._complete_iteration_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            execution_agent_id=ctx.execution_agent_id,
            started_at_ms=iteration_started_at_ms,
            status="failed",
            error_text=(
                "Repeated tool blocker detected"
                if repeated_blocker_detected
                else "All requested tools failed"
            ),
        )
        return FunctionCallingStepOutcome(
            status="failed",
            iteration=iteration,
            failure_reason=(
                "REPEATED_TOOL_BLOCKER"
                if repeated_blocker_detected
                else self._driver._classify_final_failure(
                    state.tool_failures,
                    state.all_tools_failed,
                )
            ),
        )

    async def _cancel_tool_batch(
        self,
        *,
        ctx: StepExecutionContext,
        iteration: int,
        iteration_started_at_ms: int | None,
        error_text: str,
    ) -> FunctionCallingStepOutcome:
        await self._driver._complete_iteration_trace(
            turn_id=ctx.turn_id,
            iteration=iteration,
            execution_agent_id=ctx.execution_agent_id,
            started_at_ms=iteration_started_at_ms,
            status="cancelled",
            error_text=error_text,
        )
        return FunctionCallingStepOutcome(status="cancelled", iteration=iteration)

    def _record_tool_failure(
        self,
        state: FunctionCallingStepState,
        record: _ToolExecutionRecord,
    ) -> None:
        state.failed_tool_call_fingerprints.add(record.fingerprint)
        state.tool_failures.append(self._build_tool_failure_summary(record.result))
        terminal_error_code = str(record.result.error_code or "").strip()
        if terminal_error_code in self._driver._SUPPRESS_TOOL_AFTER_ERROR_CODES:
            state.suppressed_tool_names.add(record.result.tool_name)
        self._record_repeated_blocker(state, record.result)

    def _record_repeated_blocker(
        self,
        state: FunctionCallingStepState,
        result: ToolCallResult,
    ) -> None:
        error_code = str(result.error_code or "").strip().upper()
        if error_code in self._driver._TRANSIENT_BLOCKER_ERROR_CODES or error_code in {
            "REPEATED_FAILED_TOOL_CALL",
            "REPEATED_TOOL_BLOCKER",
            "TOOL_SUPPRESSED",
        }:
            return
        signature = self._failure_signature(result)
        count = state.failure_signature_counts.get(signature, 0) + 1
        state.failure_signature_counts[signature] = count
        if count < self._driver._REPEATED_BLOCKER_LIMIT:
            return
        state.repeated_blocker_tool_names.add(result.tool_name)
        state.suppressed_tool_names.add(result.tool_name)

    @classmethod
    def _failure_signature(cls, result: ToolCallResult) -> str:
        error_code = str(result.error_code or "UNKNOWN").strip().upper() or "UNKNOWN"
        failure_reason = ""
        if isinstance(result.data, dict):
            failure_reason = str(result.data.get("failure_reason") or "").strip().upper()
        detail = failure_reason or cls._normalize_failure_text(result.error)
        return f"{result.tool_name.strip().lower()}|{error_code}|{detail}"

    @staticmethod
    def _normalize_failure_text(value: Any) -> str:
        text = " ".join(str(value or "unknown error").lower().split())
        text = re.sub(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            "<id>",
            text,
        )
        text = re.sub(r"\b[0-9a-f]{16,}\b", "<id>", text)
        return text[:240]

    def _append_tool_message(
        self,
        state: FunctionCallingStepState,
        record: _ToolExecutionRecord,
    ) -> None:
        self._driver._append_message(
            state.messages,
            {
                "role": "tool",
                "tool_call_id": record.tool_call.id,
                "content": json.dumps(
                    self._driver.postprocessor.build_tool_message_payload(
                        tool_name=record.tool_call.name,
                        result=record.result,
                    ),
                    ensure_ascii=False,
                ),
            },
        )

    def _build_tool_failure_summary(self, result: ToolCallResult) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "tool_call_id": result.tool_call_id,
            "tool_name": result.tool_name,
            "error": result.error or "unknown error",
            "error_code": result.error_code,
            "execution_time": round(result.execution_time, 3),
        }
        if isinstance(result.data, dict):
            diagnostic_keys = (
                "next_action",
                "retryable",
                "terminal",
                "requested_provider",
                "actual_provider",
                "available_providers",
                "supported_providers",
                "fallback_reason",
                "user_message_template",
                "config_tool",
            )
            diagnostics = {
                key: result.data[key]
                for key in diagnostic_keys
                if key in result.data and result.data[key] not in (None, "", [], {})
            }
            if diagnostics:
                summary["diagnostics"] = diagnostics
        return summary
