"""Background task completion helpers for chat post-processing."""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol, cast

from magi.agent.trace import now_wall_ms
from magi.chat import ChatMessageRecord
from magi.agent.background.contracts import BackgroundTask, BackgroundTaskStatus


class _BackgroundPostprocessHostProtocol(Protocol):
    _chat_store: Any


async def persist_completion_message(
    chat_store: Any,
    *,
    session_id: str,
    user_id: str,
    role: str,
    message_kind: str,
    body: str,
    payload: dict[str, Any],
    pending_message_id: str | None,
    created_at_ms: int,
) -> "ChatMessageRecord | None":
    """Append a completion transcript row with a caller-supplied body.

    Mirrors the exact record fields / pending-replacement / history-bump
    semantics that ``deliver_background_task_completion`` produced inline,
    so callers (legacy wrapper + outreach DesktopTranscriptExecutor) share
    one persistence path.
    """
    if chat_store is None:
        return None
    record = ChatMessageRecord(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        turn_id=None,
        user_id=user_id,
        role=role,
        message_kind=message_kind,
        content_text=body,
        payload_json=json.dumps(payload, ensure_ascii=False),
        is_final=True,
        is_visible=True,
        created_at_ms=created_at_ms,
        sequence_no=await chat_store.next_sequence_no(session_id=session_id),
        replaces_message_id=pending_message_id,
        replaced_by_message_id=None,
    )
    await chat_store.append_message(record)
    if pending_message_id is not None:
        await chat_store.mark_message_replaced(
            message_id=pending_message_id,
            replaced_by_message_id=record.message_id,
        )
    await chat_store.bump_history_version(session_id)
    return record


class ChatPostprocessBackgroundMixin:
    """Persist chat-visible completion messages for background tasks."""

    @staticmethod
    def _truncate_body(body: str, summary_max_chars: int | None) -> str:
        if summary_max_chars is None or len(body) <= summary_max_chars:
            return body
        return body[:summary_max_chars].rstrip() + "..."

    async def deliver_background_task_completion(
        self,
        task: BackgroundTask,
        *,
        summary_max_chars: int | None = None,
    ) -> ChatMessageRecord | None:
        """Persist the chat-visible outcome of a background task."""
        host = cast(_BackgroundPostprocessHostProtocol, self)
        if host._chat_store is None:
            return None
        spec = task.spec
        session_id = str(spec.session_id or "").strip()
        user_id = str(spec.user_id or "").strip()
        if not session_id or not user_id:
            return None

        pending_message_id = (spec.pending_message_id or "").strip() or None

        summary_body = (task.summary or "").strip()
        if task.status is BackgroundTaskStatus.SUCCEEDED and summary_body:
            return await self._deliver_assistant_output_message(
                task,
                session_id=session_id,
                user_id=user_id,
                body=summary_body,
                summary_max_chars=summary_max_chars,
                pending_message_id=pending_message_id,
            )

        title = (spec.title or "").strip() or "Background task"
        if task.status is BackgroundTaskStatus.FAILED:
            reason = (task.error or "").strip() or "unknown error"
            body = f"Background task failed: {reason}"
        elif task.status is BackgroundTaskStatus.CANCELLED:
            reason = (task.cancel_reason or "").strip() or "cancelled"
            body = f"Background task cancelled: {reason}"
        else:
            body = (task.summary or "").strip() or "(no summary)"
        body = self._truncate_body(body, summary_max_chars)
        content_text = f"[Background task] {title}\n{body}"

        payload = {
            "background_task_id": task.task_id,
            "background_task_status": task.status.value,
            "background_task_title": title,
            "background_task_attempt": int(task.attempt_index),
            "trigger_source": task.spec.trigger_source.value,
        }
        finished_at = task.finished_at if task.finished_at is not None else task.updated_at
        completed_at_ms = int(finished_at * 1000) if finished_at else now_wall_ms()

        return await persist_completion_message(
            host._chat_store,
            session_id=session_id,
            user_id=user_id,
            role="system",
            message_kind="background_task_completion",
            body=content_text,
            payload=payload,
            pending_message_id=pending_message_id,
            created_at_ms=completed_at_ms,
        )

    async def _deliver_assistant_output_message(
        self,
        task: BackgroundTask,
        *,
        session_id: str,
        user_id: str,
        body: str,
        summary_max_chars: int | None,
        pending_message_id: str | None = None,
    ) -> ChatMessageRecord | None:
        host = cast(_BackgroundPostprocessHostProtocol, self)
        title = (task.spec.title or "").strip() or "Background task"
        body = self._truncate_body(body, summary_max_chars)
        payload = {
            "background_task_id": task.task_id,
            "background_task_status": task.status.value,
            "background_task_title": title,
            "background_task_attempt": int(task.attempt_index),
            "trigger_source": task.spec.trigger_source.value,
        }
        finished_at = task.finished_at if task.finished_at is not None else task.updated_at
        completed_at_ms = int(finished_at * 1000) if finished_at else now_wall_ms()

        return await persist_completion_message(
            host._chat_store,
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            message_kind="assistant_final",
            body=body,
            payload=payload,
            pending_message_id=pending_message_id,
            created_at_ms=completed_at_ms,
        )
