"""LLM trace persistence helpers for chat post-processing.

Phase 4 cleanup: provider_bridge now publishes SpanCompleted(node_type="llm_call")
on every LLM call (see llm/provider_bridge/responses.py:_emit_usage_event), so
the chat post-process llm_call publishes here are redundant. The mixin methods
remain as no-op stubs to keep the call sites compiling; they are scheduled for
removal in phase 5.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ChatPostprocessLlmTraceMixin:
    """Persist LLM call trace records produced during chat execution."""

    _runtime_trace_store: Any
    _build_trace_id: Callable[[str], str]
    _build_root_span_id: Callable[[str], str]
    _build_span_id: Callable[[str, str], str]

    async def _ensure_turn_trace_started(
        self,
        *,
        trace_id: str,
        turn_id: str,
        user_id: str,
        session_id: str,
        started_at_ms: int,
        user_message: str,
        mode: str,
    ) -> None: ...

    async def _emit_loop_llm_trace(
        self,
        *,
        event_emitter: Any,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        stage: str,
        iteration: Any,
        execution_agent_id: Any,
        llm_trace: Any,
        response_preview: Any,
        tool_count: Any,
        tool_names: Any,
    ) -> None:
        # llm_call SpanCompleted is now published by provider_bridge.
        _ = (
            event_emitter,
            user_id,
            session_id,
            turn_id,
            stage,
            iteration,
            execution_agent_id,
            llm_trace,
            response_preview,
            tool_count,
            tool_names,
        )

    async def _emit_result_llm_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        llm_trace: Any,
        started_at_ms: int,
        user_message: str,
    ) -> None:
        # llm_call SpanCompleted is now published by provider_bridge. We still
        # ensure the turn trace exists so subsequent spans have a parent.
        normalized_turn_id = str(turn_id or "").strip()
        if (
            self._runtime_trace_store is None
            or not normalized_turn_id
            or not isinstance(llm_trace, dict)
            or not llm_trace
        ):
            return
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=normalized_turn_id,
            user_id=user_id,
            session_id=session_id,
            started_at_ms=started_at_ms,
            user_message=user_message,
            mode="direct_llm",
        )


__all__ = ["ChatPostprocessLlmTraceMixin"]
