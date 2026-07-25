"""Runtime notification side effects for chat post-processing."""

from __future__ import annotations

from typing import Any, Callable

from magi.agent.trace import now_wall_ms
from magi.runtime_trace import RuntimeTraceStore
from magi.runtime_trace.notification_payloads import (
    CHAT_MESSAGE_UPSERTED,
    CONTEXT_USAGE,
    EXECUTION_CONTROL,
    TRACE_UPDATE,
    TURN_UX_PLAN,
    build_notification_record,
    chat_message_upsert_payload,
    context_usage_payload,
    execution_control_payload,
    trace_update_payload,
    turn_ux_plan_payload,
)


class ChatRuntimeNotifier:
    """Appends live runtime notifications for chat consumers."""

    def __init__(
        self,
        *,
        runtime_trace_store: RuntimeTraceStore | None,
        chat_read_service_factory: Callable[[], Any],
    ) -> None:
        self._runtime_trace_store = runtime_trace_store
        self._chat_read_service_factory = chat_read_service_factory

    async def emit_chat_message_upsert(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        if self._runtime_trace_store is None:
            return
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if not normalized_user_id or not normalized_session_id or not normalized_message_id:
            return
        read_service = self._chat_read_service_factory()
        message = await read_service.aget_display_message(
            normalized_user_id,
            normalized_session_id,
            normalized_message_id,
        )
        if message is None:
            return
        session_summary = await read_service.aget_session_summary(
            normalized_user_id,
            normalized_session_id,
        )
        await self._runtime_trace_store.append_notification(
            build_notification_record(
                channel=CHAT_MESSAGE_UPSERTED,
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                payload=chat_message_upsert_payload(
                    user_id=normalized_user_id,
                    session_id=normalized_session_id,
                    message_id=normalized_message_id,
                    message=message,
                    session_summary=session_summary,
                ),
                created_at_ms=now_wall_ms(),
            )
        )

    async def emit_turn_ux_plan(
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
        if self._runtime_trace_store is None or not turn_id or not ux_plan:
            return
        await self._runtime_trace_store.append_notification(
            build_notification_record(
                channel=TURN_UX_PLAN,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload=turn_ux_plan_payload(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    ux_plan=ux_plan,
                    message_id=message_id,
                    message_kind=message_kind,
                    timestamp_ms=timestamp_ms,
                ),
                created_at_ms=now_wall_ms(),
            )
        )

    async def emit_trace_update(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        trace_summary: dict[str, Any] | None = None,
    ) -> None:
        if self._runtime_trace_store is None or not turn_id:
            return
        await self._runtime_trace_store.append_notification(
            build_notification_record(
                channel=TRACE_UPDATE,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload=trace_update_payload(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_summary=trace_summary,
                ),
                created_at_ms=now_wall_ms(),
            )
        )

    async def emit_execution_control(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        orchestration_id: str | None,
        state: str,
        can_cancel: bool,
        label: str | None = None,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id:
            return
        await self._runtime_trace_store.append_notification(
            build_notification_record(
                channel=EXECUTION_CONTROL,
                user_id=user_id,
                session_id=session_id,
                turn_id=normalized_turn_id,
                payload=execution_control_payload(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=normalized_turn_id,
                    run_id=run_id,
                    orchestration_id=orchestration_id,
                    state=state,
                    can_cancel=can_cancel,
                    label=label,
                ),
                created_at_ms=now_wall_ms(),
            )
        )

    async def emit_context_usage(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        context_usage: dict[str, Any],
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id:
            return
        await self._runtime_trace_store.append_notification(
            build_notification_record(
                channel=CONTEXT_USAGE,
                user_id=user_id,
                session_id=session_id,
                turn_id=normalized_turn_id,
                payload=context_usage_payload(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=normalized_turn_id,
                    context_usage=context_usage,
                ),
                created_at_ms=now_wall_ms(),
            )
        )


__all__ = ["ChatRuntimeNotifier"]
