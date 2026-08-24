"""Streaming event helpers for the chat task agent."""

from __future__ import annotations

from typing import Any

from magi.agent.execution.task_budget import TaskBudgetExceeded
from magi.llm.error_classifier import LLMErrorKind, classify_exception
from magi.llm.streaming_events import LLMStreamEvent


def format_llm_error(exc: Exception) -> str:
    """Return a concise user-facing error string for an LLM call failure."""
    if isinstance(exc, TaskBudgetExceeded):
        return (
            "⚠️ This task reached its execution limit and was stopped to avoid "
            "an unbounded loop. Please narrow the request or continue in a new task."
        )
    classified = classify_exception(exc)
    if classified.kind == LLMErrorKind.RATE_LIMIT:
        return "⚠️ The AI service is rate-limited. Please wait a moment and try again."
    if classified.kind == LLMErrorKind.AUTH:
        return "⚠️ Authentication failed. Please check your API key configuration."
    if classified.kind == LLMErrorKind.SERVICE_UNAVAILABLE:
        return "⚠️ The AI service is temporarily unavailable. Please try again later."
    return f"⚠️ The AI service returned an error. Please try again. ({exc.__class__.__name__})"


class ChatStreamingMixin:
    """Canonical chunk write path for streaming chat responses.

    Every model stream event is routed onto
    ``coordinator.dispatch_stream_chunk`` -> ``ChatSseChannel.deliver_chunk``,
    carrying the full event so all kinds (text_delta / reasoning / status /
    text_flush / tool_call) are delivered. The channel is the sole writer of
    ``agent_response_chunk`` rows; there is no legacy notifier path.
    """

    _postprocess_service: Any
    _coordinator: Any

    async def _emit_stream_event(
        self,
        *,
        event: LLMStreamEvent,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        persona_id: str | None = None,
        seq: int = 0,
    ) -> None:
        """Route one LLM stream event onto the canonical chunk path.

        ``text`` mirrors the event's text so text-only/legacy channels keep
        working; ``event`` carries the full wire payload so streaming channels
        render every event kind. ``is_final`` stays ``False`` — the stream's
        boundary chunk is dispatched separately by the handler.
        """
        await self._coordinator.dispatch_stream_chunk(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            text=event.text or "",
            is_final=False,
            seq=seq,
            event=event,
            persona_id=persona_id,
        )

    def _build_stream_sink(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        persona_id: str | None = None,
    ):
        agent = self
        seq = 0

        async def sink(event: LLMStreamEvent) -> None:
            nonlocal seq
            await agent._emit_stream_event(
                event=event,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                persona_id=persona_id,
                seq=seq,
            )
            seq += 1

        return sink

    async def _emit_llm_error(self, context: Any, exc: Exception) -> None:
        """Emit a user-visible error message when LLM call fails."""
        turn_id = str(getattr(context.latest_payload, "turn_id", "") or "").strip()
        if not (context.user_id and context.session_id and turn_id):
            return
        error_text = format_llm_error(exc)
        await self._emit_stream_event(
            event=LLMStreamEvent(kind="text_delta", text=error_text),
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            persona_id=getattr(context, "active_persona_id", None),
            seq=0,
        )
        await self._emit_stream_event(
            event=LLMStreamEvent(kind="text_flush"),
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            persona_id=getattr(context, "active_persona_id", None),
            seq=1,
        )
