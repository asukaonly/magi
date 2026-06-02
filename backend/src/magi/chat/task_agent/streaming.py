"""Streaming event helpers for the chat task agent."""

from __future__ import annotations

from typing import Any

from magi.llm.error_classifier import LLMErrorKind, classify_exception
from magi.llm.streaming_events import LLMStreamEvent


def format_llm_error(exc: Exception) -> str:
    """Return a concise user-facing error string for an LLM call failure."""
    classified = classify_exception(exc)
    if classified.kind == LLMErrorKind.RATE_LIMIT:
        return "⚠️ The AI service is rate-limited. Please wait a moment and try again."
    if classified.kind == LLMErrorKind.AUTH:
        return "⚠️ Authentication failed. Please check your API key configuration."
    if classified.kind == LLMErrorKind.SERVICE_UNAVAILABLE:
        return "⚠️ The AI service is temporarily unavailable. Please try again later."
    return f"⚠️ The AI service returned an error. Please try again. ({exc.__class__.__name__})"


class ChatStreamingMixin:
    """Runtime notifier integration for streaming chat responses."""

    _postprocess_service: Any

    async def _emit_stream_event(
        self,
        *,
        event: LLMStreamEvent,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        persona_id: str | None = None,
    ) -> None:
        """Forward an LLM stream event to the runtime notifier wire."""
        await self._postprocess_service._runtime_notifier.emit_stream_event(
            event=event,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
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

        async def sink(event: LLMStreamEvent) -> None:
            await agent._emit_stream_event(
                event=event,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                persona_id=persona_id,
            )

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
        )
        await self._emit_stream_event(
            event=LLMStreamEvent(kind="text_flush"),
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            persona_id=getattr(context, "active_persona_id", None),
        )
