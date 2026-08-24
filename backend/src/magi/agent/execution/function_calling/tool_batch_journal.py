"""Trace and journal projection for one executed tool batch."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ....llm.streaming_events import LLMStreamEvent, emit_stream_event
from ..contracts import AgentRunEventType
from ..evidence import ToolExecutionEvidence
from ..tool_metadata import resolve_tool_capability_metadata
from .step_models import FunctionCallingStepState, StepExecutionContext
from .types import ToolCallResult

MAX_RUNTIME_STATUS_CHARS = 2_000
_ADMISSION_REJECTION_CODES = frozenset(
    {
        "ACCESS_DENIED",
        "AUTH_REQUIRED",
        "PERMISSION_DENIED",
        "POLICY_BLOCKED",
        "READ_ONLY",
        "ROLE_NOT_ALLOWED",
        "TOOL_EFFECT_ALREADY_COMPLETED",
        "TOOL_EFFECT_IDENTITY_REQUIRED",
        "TOOL_EFFECT_LEDGER_UNAVAILABLE",
        "TOOL_EFFECT_UNCERTAIN",
    }
)


@dataclass(slots=True)
class ToolExecutionRecord:
    """One requested tool call and its normalized execution result."""

    tool_call: Any
    result: ToolCallResult
    fingerprint: str


class FunctionCallingToolBatchJournal:
    """Project model tool requests and tool results to runtime observability."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    async def record_request(
        self,
        *,
        state: FunctionCallingStepState,
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
        if state.journal is not None:
            await state.journal.append(
                AgentRunEventType.TOOL_CALL_REQUESTED,
                step_index=iteration,
                payload={
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        }
                        for tool_call in tool_calls
                    ]
                },
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
                "execution_preset": ctx.execution_preset,
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

    async def record_execution(
        self,
        *,
        state: FunctionCallingStepState,
        record: ToolExecutionRecord,
        ctx: StepExecutionContext,
        iteration: int,
    ) -> None:
        result = record.result
        metadata = resolve_tool_capability_metadata(
            self._driver.tool_registry,
            record.tool_call.name,
        )
        evidence = ToolExecutionEvidence(
            tool_name=record.tool_call.name,
            success=result.success,
            effect_class=metadata.effect_class.value,
            replay_policy=metadata.replay_policy.value,
            error_code=result.error_code,
            result=result.data if result.success else result.error,
            tool_call_id=record.tool_call.id,
        )
        state.tool_evidence.append(evidence)
        self._append_tool_message(state, record, evidence=evidence)
        if state.journal is not None:
            if _tool_execution_was_admitted(result):
                await state.journal.append(
                    AgentRunEventType.TOOL_EFFECT_ADMITTED,
                    step_index=iteration,
                    payload={
                        "tool_name": record.tool_call.name,
                        "tool_call_id": record.tool_call.id,
                        "effect_class": metadata.effect_class.value,
                        "replay_policy": metadata.replay_policy.value,
                    },
                )
            await state.journal.append(
                AgentRunEventType.TOOL_RESULT,
                step_index=iteration,
                payload={
                    **evidence.to_ref().to_dict(),
                    "model_observation": dict(state.messages[-1]),
                },
            )
            if (
                record.tool_call.name == "todo_write"
                and result.success
                and isinstance(result.data, dict)
            ):
                await state.journal.append(
                    AgentRunEventType.PLAN_UPDATED,
                    step_index=iteration,
                    payload={
                        "plan_id": result.data.get("plan_id"),
                        "version": result.data.get("version"),
                    },
                )
            await self._append_child_run_events(
                state=state,
                record=record,
                iteration=iteration,
            )
            if record.tool_call.name == "verify":
                await state.journal.append(
                    AgentRunEventType.VALIDATION_COMPLETED,
                    step_index=iteration,
                    payload={
                        "success": result.success,
                        "evidence": evidence.to_ref().to_dict(),
                    },
                )
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
                "execution_preset": ctx.execution_preset,
                "execution_agent_id": ctx.execution_agent_id,
            }
        )
        await self._driver._emit_tool_result(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            user_message=ctx.user_message,
            execution_preset=ctx.execution_preset,
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

    def _append_tool_message(
        self,
        state: FunctionCallingStepState,
        record: ToolExecutionRecord,
        *,
        evidence: ToolExecutionEvidence,
    ) -> None:
        payload = self._driver.postprocessor.build_tool_message_payload(
            tool_name=record.tool_call.name,
            result=record.result,
        )
        if isinstance(payload, dict):
            payload["_runtime_evidence_ref"] = evidence.evidence_id
        self._driver._append_message(
            state.messages,
            {
                "role": "tool",
                "tool_call_id": record.tool_call.id,
                "content": json.dumps(payload, ensure_ascii=False),
            },
        )

    @staticmethod
    async def _append_child_run_events(
        *,
        state: FunctionCallingStepState,
        record: ToolExecutionRecord,
        iteration: int,
    ) -> None:
        if state.journal is None or record.tool_call.name != "agent":
            return
        result = record.result
        if not result.success:
            return
        action = str((record.tool_call.arguments or {}).get("action") or "launch")
        for payload in _child_payloads(result.data):
            child_run_id = str(payload.get("child_run_id") or "").strip()
            if not child_run_id:
                continue
            status = str(payload.get("status") or "").strip()
            event_payload = {
                "child_run_id": child_run_id,
                "worker_id": payload.get("worker_id"),
                "preset": payload.get("preset"),
                "status": status,
                "ownership": payload.get("ownership"),
                "evidence": payload.get("evidence"),
            }
            if action == "launch":
                await state.journal.append(
                    AgentRunEventType.CHILD_STARTED,
                    step_index=iteration,
                    payload=event_payload,
                )
            if status in {"completed", "failed"}:
                await state.journal.append(
                    AgentRunEventType.CHILD_COMPLETED,
                    step_index=iteration,
                    payload=event_payload,
                )
            elif status == "cancelled":
                await state.journal.append(
                    AgentRunEventType.CHILD_CANCELLED,
                    step_index=iteration,
                    payload=event_payload,
                )


def build_tool_failure_summary(result: ToolCallResult) -> dict[str, Any]:
    """Build the bounded failure payload retained in run state and events."""

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


def _normalize_runtime_status_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= MAX_RUNTIME_STATUS_CHARS:
        return text
    return f"{text[:MAX_RUNTIME_STATUS_CHARS].rstrip()}..."


def _tool_execution_was_admitted(result: ToolCallResult) -> bool:
    return str(result.error_code or "").strip().upper() not in _ADMISSION_REJECTION_CODES


def _child_payloads(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    for key in ("children", "workers"):
        children = value.get(key)
        if isinstance(children, list):
            return [item for item in children if isinstance(item, dict)]
    return [value]


__all__ = [
    "FunctionCallingToolBatchJournal",
    "ToolExecutionRecord",
    "build_tool_failure_summary",
]
