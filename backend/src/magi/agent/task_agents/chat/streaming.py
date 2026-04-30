"""Streaming event helpers for the chat task agent."""

from __future__ import annotations

from typing import Any

from ....llm.streaming_events import LLMStreamEvent

_RATE_LIMIT_CODES = {"429", "1302", "rate_limit_exceeded"}


def format_llm_error(exc: Exception) -> str:
    """Return a concise user-facing error string for an LLM call failure."""
    exc_str = str(exc)
    status_code = str(getattr(exc, "status_code", "") or "")
    if status_code == "429" or any(code in exc_str for code in _RATE_LIMIT_CODES):
        return "⚠️ The AI service is rate-limited. Please wait a moment and try again."
    if status_code in ("401", "403"):
        return "⚠️ Authentication failed. Please check your API key configuration."
    if status_code in ("500", "502", "503"):
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
    ) -> None:
        """Forward an LLM stream event to the runtime notifier wire."""
        await self._postprocess_service._runtime_notifier.emit_stream_event(
            event=event,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

    def _build_stream_sink(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ):
        agent = self

        async def sink(event: LLMStreamEvent) -> None:
            await agent._emit_stream_event(
                event=event,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
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
        )
        await self._emit_stream_event(
            event=LLMStreamEvent(kind="text_flush"),
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
        )