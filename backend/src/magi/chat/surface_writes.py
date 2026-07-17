"""Chat-owned transcript writes for external API surfaces."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from ..core.logger import get_logger
from ..core.runtime_bindings import get_chat_message_notifier
from ..runtime_trace.notification_payloads import (
    AGENT_RESPONSE,
    agent_response_payload,
    build_notification_record,
)
from ..runtime_trace.provider import resolve_runtime_trace_store
from .contracts import ChatMessageRecord, ChatTurnRecord
from .provider import get_chat_store

logger = get_logger(__name__)


class ChatSurfaceWriteService:
    """Owns chat transcript writes initiated by external API surfaces."""

    async def append_command_invocation(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation_text: str,
    ) -> str:
        payload = {
            "command": {
                "tool_name": tool_name,
                "arguments": arguments,
            }
        }
        record = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="user",
            message_kind="command_invocation",
            content_text=invocation_text or f"/{tool_name}",
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=True,
            is_visible=True,
            created_at_ms=int(time.time() * 1000),
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        await get_chat_store().append_message(record)
        await self._broadcast_upsert(
            user_id=user_id, session_id=session_id, message_id=record.message_id
        )
        return record.message_id

    async def append_command_result(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        invocation_message_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        output_text: str,
        success: bool,
        error: str | None,
        error_code: str | None,
        execution_time_ms: int,
        invocation_text: str | None = None,
    ) -> str:
        result_payload: dict[str, Any] = {
            "tool_name": tool_name,
            "arguments": arguments,
            "success": success,
            "error": error,
            "error_code": error_code,
            "execution_time_ms": execution_time_ms,
        }
        if invocation_message_id:
            result_payload["invocation_message_id"] = invocation_message_id
        if invocation_text is not None:
            result_payload["invocation_text"] = invocation_text
        payload = {"command_result": result_payload}
        record = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="tool",
            message_kind="command_result",
            content_text=output_text,
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=True,
            is_visible=True,
            created_at_ms=int(time.time() * 1000),
            sequence_no=2 if invocation_message_id else 1,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        await get_chat_store().append_message(record)
        await self._broadcast_upsert(
            user_id=user_id, session_id=session_id, message_id=record.message_id
        )
        return record.message_id

    async def create_background_task_pending_message(
        self,
        *,
        user_id: str,
        session_id: str,
        title: str,
        trigger_source: str,
        skill_name: str,
        invocation_text: str,
    ) -> str:
        chat_store = get_chat_store()
        message_id = f"msg_{uuid.uuid4().hex[:16]}"
        payload = {
            "background_task_id": "",
            "background_task_status": "pending",
            "background_task_title": title,
            "trigger_source": trigger_source,
            "skill_name": skill_name,
            "invocation_text": invocation_text,
        }
        record = ChatMessageRecord(
            message_id=message_id,
            session_id=session_id,
            turn_id=None,
            user_id=user_id,
            role="system",
            message_kind="background_task_pending",
            content_text=f"[Background task] {title}\n(running…)",
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=False,
            is_visible=True,
            created_at_ms=int(time.time() * 1000),
            sequence_no=await chat_store.next_sequence_no(session_id=session_id),
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        await chat_store.append_message(record)
        await chat_store.bump_history_version(session_id)
        await self._broadcast_upsert(user_id=user_id, session_id=session_id, message_id=message_id)
        return message_id

    async def attach_background_task_id(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        task_id: str,
    ) -> None:
        chat_store = get_chat_store()
        record = await chat_store.get_message(message_id)
        if record is None:
            return
        payload = _decode_payload(record.payload_json)
        payload["background_task_id"] = task_id
        record.payload_json = json.dumps(payload, ensure_ascii=False)
        await chat_store.append_message(record)
        await self._broadcast_upsert(user_id=user_id, session_id=session_id, message_id=message_id)

    async def persist_bootstrap_assistant_message(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        content: str,
    ) -> str:
        now_ms = int(time.time() * 1000)
        message_id = f"msg_{uuid.uuid4().hex[:16]}"
        chat_store = get_chat_store()

        await chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=turn_id,
                session_id=session_id,
                user_id=user_id,
                trace_id=None,
                orchestration_id=None,
                status="completed",
                response_mode="final_only",
                execution_mode=None,
                ux_plan_json="{}",
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
                completed_at_ms=now_ms,
                error_text=None,
            )
        )

        await chat_store.append_message(
            ChatMessageRecord(
                message_id=message_id,
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
                role="assistant",
                message_kind="assistant_final",
                content_text=content,
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=now_ms,
                sequence_no=await chat_store.next_sequence_no(session_id=session_id),
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )

        await chat_store.bump_history_version(session_id)
        await self._broadcast_upsert(user_id=user_id, session_id=session_id, message_id=message_id)
        await self._emit_bootstrap_notification(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            content=content,
            created_at_ms=now_ms,
        )
        return message_id

    async def set_message_label(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        label: dict[str, object],
    ) -> bool:
        message = await get_chat_store().update_message_label(
            session_id=session_id,
            message_id=message_id,
            label=label,
        )
        if message is None:
            return False
        await self._broadcast_upsert(user_id=user_id, session_id=session_id, message_id=message_id)
        return True

    async def hide_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        chat_store = get_chat_store()
        message = await chat_store.hide_message(
            session_id=session_id,
            message_id=message_id,
        )
        if message is None:
            existing = await chat_store.get_message(message_id)
            if (
                existing is None
                or existing.session_id != session_id
                or existing.user_id != user_id
                or existing.is_visible
            ):
                return False
        await get_chat_message_notifier().broadcast_chat_message_hidden(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )
        return True

    async def _broadcast_upsert(self, *, user_id: str, session_id: str, message_id: str) -> None:
        await get_chat_message_notifier().broadcast_chat_message_upsert(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )

    async def _emit_bootstrap_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
        content: str,
        created_at_ms: int,
    ) -> None:
        try:
            trace_store = resolve_runtime_trace_store()
            await trace_store.append_notification(
                build_notification_record(
                    channel=AGENT_RESPONSE,
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    payload=agent_response_payload(
                        user_id=user_id,
                        session_id=session_id,
                        content=content,
                        extra_fields={
                            "message_id": message_id,
                            "message_kind": "assistant_final",
                            "author_type": "assistant",
                            "content_type": "text",
                            "turn_id": turn_id,
                            "orchestration_id": None,
                            "trace_summary": None,
                            "trace_available": False,
                            "ux_plan": {},
                        },
                        include_none_extra_fields=True,
                    ),
                    created_at_ms=created_at_ms,
                )
            )
        except Exception as exc:
            logger.warning("Failed to emit bootstrap notification: %s", exc)


def _decode_payload(payload_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = ["ChatSurfaceWriteService"]
