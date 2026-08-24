"""Runtime notification helpers for chat post-processing."""

from __future__ import annotations

from typing import Any

from .message_payloads import resolve_reaction_text


class ChatPostprocessTraceNotificationMixin:
    """Emit runtime notifications for chat outcomes and trace updates."""

    _runtime_notifier: Any
    _trace_read_service: Any

    async def _emit_turn_ux_plan_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
        timestamp_ms: int | None,
    ) -> None:
        await self._runtime_notifier.emit_turn_ux_plan(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            ux_plan=ux_plan,
            message_id=message_id,
            message_kind=message_kind,
            timestamp_ms=timestamp_ms,
        )

    async def _emit_trace_update_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> None:
        trace_summary: dict[str, Any] | None = None
        if self._trace_read_service and turn_id:
            try:
                trace_summary = await self._trace_read_service.aget_trace_summary(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            except Exception:
                pass
        await self._runtime_notifier.emit_trace_update(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            trace_summary=trace_summary,
        )

    async def _emit_context_usage_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        context_usage: dict[str, Any],
    ) -> None:
        await self._runtime_notifier.emit_context_usage(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            context_usage=context_usage,
        )

    async def emit_execution_control_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        state: str,
        can_cancel: bool,
        label: str | None = None,
    ) -> None:
        await self._runtime_notifier.emit_execution_control(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            state=state,
            can_cancel=can_cancel,
            label=label,
        )

    @staticmethod
    def _resolve_reaction_notification_text(
        ux_plan: dict[str, Any] | None,
        *,
        fallback: str,
    ) -> str:
        reaction_text = resolve_reaction_text(ux_plan)
        return reaction_text or fallback


__all__ = ["ChatPostprocessTraceNotificationMixin"]
