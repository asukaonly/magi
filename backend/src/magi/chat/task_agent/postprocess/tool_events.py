"""Tool event recording helpers for chat post-processing."""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Protocol, cast

from .constants import (
    CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
    TOOL_INTERACTION_EVENT_TYPE,
)


class _ToolEventPostprocessHostProtocol(Protocol):
    _agent_id: str
    _context_assembler: Any
    # Per-session recent-tool-call view. Sourced from
    # ``ChatContextAssembler.tool_state_view`` and aliased onto the chat
    # agent so postprocess can record tool events without going through
    # ChatContextAssembler as a middleman.
    _tool_state_view: Any
    _get_event_emitter: Callable[[], Any]

    async def _emit_trace_update_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> None:
        ...

class ChatPostprocessToolEventMixin:
    """Record tool interaction and tool-loop runtime events."""

    async def record_tool_interaction(self, payload: dict[str, Any]) -> None:
        host = cast(_ToolEventPostprocessHostProtocol, self)
        user_id = str(payload.get("user_id") or host._agent_id)
        session_id = host._context_assembler.require_session_id(user_id, payload.get("session_id"))
        history_key = host._context_assembler.history_key(user_id, session_id)
        turn_id = str(payload.get("turn_id") or "").strip() or None
        raw_result_data = payload.get("data")
        result_data = cast(dict[str, Any], raw_result_data) if isinstance(raw_result_data, dict) else {}
        host._tool_state_view.record(
            history_key,
            {
                "timestamp": time.time(),
                "intent": payload.get("intent") or "unknown",
                "tool_name": str(payload.get("tool_name") or "unknown"),
                "status": "success" if bool(payload.get("success")) else "error",
                "error_code": str(payload.get("error_code") or ""),
                "error_message": str(payload.get("error") or ""),
                "result_summary": self._summarize_tool_result(result_data),
                "result_data": result_data,
                "turn_id": turn_id,
            },
        )

        event_emitter = host._get_event_emitter()
        if event_emitter is None:
            return
        tool_name = str(payload.get("tool_name") or "unknown")
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        execution_time = float(payload.get("execution_time") or 0.0)
        success = bool(payload.get("success"))
        error_text = str(payload.get("error") or "") or None
        await event_emitter.emit_runtime_event(
            event_type=TOOL_INTERACTION_EVENT_TYPE,
            payload={
                "tool_name": tool_name,
                "tool_call_id": payload.get("tool_call_id"),
                "arguments": arguments,
                "success": success,
                "error": error_text,
                "error_code": payload.get("error_code"),
                "execution_time": execution_time,
                "data": payload.get("data"),
                "intent": payload.get("intent"),
                "iteration": payload.get("iteration"),
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "timestamp": time.time(),
            },
            correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
            success=success,
        )
        await host._emit_trace_update_notification(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

    @staticmethod
    def _summarize_tool_result(result_data: dict[str, Any]) -> str:
        if not isinstance(result_data, dict) or not result_data:
            return ""

        summary = str(result_data.get("summary") or "").strip()
        if summary:
            return summary

        historical_recall = result_data.get("historical_recall")
        if isinstance(historical_recall, dict):
            recall_summary = str(historical_recall.get("summary") or "").strip()
            if recall_summary:
                return recall_summary
            status = str(historical_recall.get("status") or "").strip()
            if status:
                return f"historical_recall status={status}"

        resolved_count = result_data.get("resolved_count")
        if isinstance(resolved_count, int):
            return f"Resolved {resolved_count} asset(s)."

        chat_attachments = result_data.get("chat_attachments")
        if isinstance(chat_attachments, list):
            return f"Prepared {len(chat_attachments)} chat attachment(s)."

        asset_refs = result_data.get("asset_refs")
        if isinstance(asset_refs, list):
            return f"Returned {len(asset_refs)} asset ref(s)."

        return ""

    async def record_tool_loop_fact(self, payload: dict[str, Any]) -> None:
        host = cast(_ToolEventPostprocessHostProtocol, self)
        user_id = str(payload.get("user_id") or host._agent_id)
        session_id = host._context_assembler.require_session_id(user_id, payload.get("session_id"))
        stage = str(payload.get("stage") or "unknown")
        turn_id = str(payload.get("turn_id") or "").strip() or None
        runtime_payload = {
            "stage": stage,
            "iteration": payload.get("iteration"),
            "max_iterations": payload.get("max_iterations"),
            "tool_name": payload.get("tool_name"),
            "tool_names": payload.get("tool_names"),
            "tool_count": payload.get("tool_count"),
            "tool_call_id": payload.get("tool_call_id"),
            "success": payload.get("success"),
            "error": payload.get("error"),
            "execution_time": payload.get("execution_time"),
            "replan_allowed": payload.get("replan_allowed"),
            "consecutive_failed_iterations": payload.get("consecutive_failed_iterations"),
            "llm_trace": payload.get("llm_trace") if isinstance(payload.get("llm_trace"), dict) else None,
            "response_preview": payload.get("response_preview"),
            "intent": payload.get("intent"),
            "execution_agent_id": payload.get("execution_agent_id"),
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "timestamp": time.time(),
        }
        correlation_id = str(payload.get("tool_call_id") or str(uuid.uuid4()))
        event_emitter = host._get_event_emitter()
        if event_emitter is not None:
            await event_emitter.emit_runtime_event(
                event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
                payload=runtime_payload,
                correlation_id=correlation_id,
                success=bool(payload.get("success", True)),
            )
        await host._emit_trace_update_notification(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
