"""Shared user-message dispatch helpers for API and websocket transports."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from ...chat.provider import get_chat_projector, get_chat_store
from ...core.logger import get_logger
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import UserMessageCommand
from ...runtime_defaults import DEFAULT_RUNTIME_NAMESPACE

logger = get_logger(__name__)

_CHAT_PROJECTION_METADATA_KEYS = {
    "l2_batch_owner",
    "l2_batch_catch_up_owner",
    "l2_batch_max_events",
    "l2_batch_min_ready_events",
    "l2_batch_max_wait_seconds",
}


CHAT_STORE_NOT_INITIALIZED = "CHAT_STORE_NOT_INITIALIZED"
CHAT_STORE_PERSIST_FAILED = "CHAT_STORE_PERSIST_FAILED"
RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED = "RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED"
RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED = "RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED"
SESSION_ID_REQUIRED = "SESSION_ID_REQUIRED"
EMPTY_TURN = "EMPTY_TURN"
MALFORMED_ATTACHMENTS = "MALFORMED_ATTACHMENTS"


@dataclass(slots=True)
class MessageDispatchOutcome:
    success: bool
    user_id: str
    session_id: str | None = None
    turn_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    queue_size: int | None = None


def get_chat_read_service():
    """Resolve the chat read service lazily to avoid import cycles at startup."""

    from ...chat.read_service import get_chat_read_service as _get_chat_read_service

    return _get_chat_read_service()


def _extract_chat_projection_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in _CHAT_PROJECTION_METADATA_KEYS and value is not None
    }


async def dispatch_user_message(
    *,
    source: str,
    user_id: str,
    message: str,
    session_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    reply_to_message_id: str | None = None,
    workspace_path: str | None = None,
    client_turn_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    runtime_namespace: str | None = None,
) -> MessageDispatchOutcome:
    """Resolve session metadata and enqueue a user-message runtime command."""

    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED,
            error_message="Runtime command queue is not initialized. Please complete onboarding or check the saved configuration.",
        )
    try:
        chat_store = get_chat_store()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=CHAT_STORE_NOT_INITIALIZED,
            error_message="Chat store is not initialized.",
        )

    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=SESSION_ID_REQUIRED,
            error_message="Session ID is required.",
        )
    try:
        normalized_attachments = _normalize_attachments(attachments)
    except ValueError as exc:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            error_code=MALFORMED_ATTACHMENTS,
            error_message=str(exc),
        )
    normalized_message = str(message or "")
    if not normalized_message.strip() and not normalized_attachments:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            error_code=EMPTY_TURN,
            error_message="Message text or attachments are required.",
        )
    normalized_workspace_path = str(workspace_path or "").strip() or None
    if normalized_workspace_path is None:
        try:
            read_service = get_chat_read_service()
            session_summary = await read_service.aget_session_summary(user_id, resolved_session_id)
        except Exception:
            session_summary = None
        if session_summary is not None:
            normalized_workspace_path = str(session_summary.workspace_path or "").strip() or None
    normalized_reply_to_message_id = str(reply_to_message_id or "").strip() or None
    normalized_metadata = dict(metadata or {})
    if normalized_reply_to_message_id is not None:
        normalized_metadata["reply_to_message_id"] = normalized_reply_to_message_id
    created_at = time.time()
    created_at_ms = int(created_at * 1000)
    turn_id = str(client_turn_id or "").strip() or f"turn_{uuid.uuid4().hex[:12]}"
    active_persona_id = await _resolve_active_persona_id()
    try:
        created_turn = await chat_store.create_user_turn(
            session_id=resolved_session_id,
            user_id=user_id,
            turn_id=turn_id,
            message_text=normalized_message,
            attachment_payloads=normalized_attachments,
            created_at_ms=created_at_ms,
            reply_to_message_id=normalized_reply_to_message_id,
            persona_id=active_persona_id,
        )
    except Exception:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            turn_id=turn_id,
            error_code=CHAT_STORE_PERSIST_FAILED,
            error_message="Chat turn persistence failed",
        )
    try:
        chat_projector = get_chat_projector()
    except RuntimeError:
        chat_projector = None
    if chat_projector is not None:
        try:
            await chat_projector.project_user_message(
                message_id=created_turn.message_id,
                user_id=user_id,
                session_id=resolved_session_id,
                turn_id=turn_id,
                content=normalized_message,
                created_at_ms=created_at_ms,
                metadata=_extract_chat_projection_metadata(normalized_metadata),
            )
        except Exception as exc:
            logger.warning("Failed to project chat user message into L1: %s", exc)
    try:
        await runtime_command_queue.enqueue_user_message(
            UserMessageCommand(
                source=source,
                user_id=user_id,
                session_id=resolved_session_id,
                turn_id=turn_id,
                message=normalized_message,
                attachments=normalized_attachments,
                workspace_path=normalized_workspace_path,
                runtime_namespace=str(runtime_namespace or "").strip() or DEFAULT_RUNTIME_NAMESPACE,
                metadata=normalized_metadata,
                created_at=created_at,
            )
        )
    except Exception:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            turn_id=turn_id,
            error_code=RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
            error_message="Runtime command enqueue failed",
        )

    stats = await runtime_command_queue.get_stats()
    queue_size = stats.get("pending_count") if isinstance(stats, dict) else None
    from ...transport.chat_events import broadcast_chat_message_upsert

    await broadcast_chat_message_upsert(
        user_id=user_id,
        session_id=resolved_session_id,
        message_id=created_turn.message_id,
    )
    return MessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=resolved_session_id,
        turn_id=turn_id,
        queue_size=int(queue_size) if isinstance(queue_size, int) else None,
    )


async def _resolve_active_persona_id() -> str | None:
    try:
        from ...personality.persona_repository import PersonaRepository
        from ...utils.runtime import get_runtime_paths

        repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
        await repo.init()
        active_id = await repo.get_active_id()
    except Exception:
        return None
    return str(active_id or "").strip() or None


def _normalize_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise ValueError("Attachments must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError("Each attachment must be an object.")
        normalized_item = dict(item)
        attachment_kind = str(normalized_item.get("kind") or "").strip()
        if not attachment_kind:
            raise ValueError("Each attachment must include a kind.")
        normalized_item["kind"] = attachment_kind
        normalized.append(normalized_item)
    return normalized
