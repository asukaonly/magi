"""Runtime notification side effects for chat post-processing."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from .....agent.trace import now_wall_ms
from .....llm.streaming_events import LLMStreamEvent
from .....runtime_trace import RuntimeNotificationRecord, RuntimeTraceStore


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

    async def emit_agent_response(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        response_text: str,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        orchestration_id: str | None,
        trace_summary: dict[str, Any] | None,
        trace_available: bool,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
    ) -> None:
        if self._runtime_trace_store is None:
            return
        payload = {
            "message_id": message_id,
            "message_kind": message_kind,
            "content": response_text,
            "attachments": list(attachments or []),
            "message_payload": dict(message_payload or {}),
            "author_type": "assistant",
            "content_type": "text",
            "timestamp": time.time(),
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "orchestration_id": orchestration_id,
            "trace_summary": trace_summary,
            "trace_available": trace_available,
            "ux_plan": ux_plan,
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="agent_response",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )

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
        payload = {
            "user_id": normalized_user_id,
            "session_id": normalized_session_id,
            "message_id": normalized_message_id,
            "message": message.to_dict(),
            "session_summary": session_summary.to_dict() if session_summary is not None else None,
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="chat_message_upserted",
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                payload_json=json.dumps(payload, default=str),
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
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "message_id": message_id,
            "message_kind": message_kind,
            "ux_plan": ux_plan,
            "timestamp": (timestamp_ms / 1000.0) if timestamp_ms is not None else time.time(),
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="turn_ux_plan",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
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
        payload: dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
        }
        if trace_summary is not None:
            payload["trace_summary"] = trace_summary
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="trace_update",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
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
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": normalized_turn_id,
            "run_id": run_id,
            "orchestration_id": orchestration_id,
            "state": state,
            "can_cancel": can_cancel,
            "label": label,
            "timestamp": time.time(),
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="execution_control",
                user_id=user_id,
                session_id=session_id,
                turn_id=normalized_turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )

    async def emit_context_usage(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        context_usage: dict[str, int],
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id:
            return
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": normalized_turn_id,
            "used_tokens": context_usage.get("used_tokens", 0),
            "window_size": context_usage.get("window_size", 0),
            "threshold": context_usage.get("threshold", 0),
            "timestamp": time.time(),
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="context_usage",
                user_id=user_id,
                session_id=session_id,
                turn_id=normalized_turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )

    async def emit_stream_event(
        self,
        *,
        event: LLMStreamEvent,
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id:
            return
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": normalized_turn_id,
            "event": event.to_wire_dict(),
            "timestamp": time.time(),
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="agent_response_chunk",
                user_id=user_id,
                session_id=session_id,
                turn_id=normalized_turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )


__all__ = ["ChatRuntimeNotifier"]