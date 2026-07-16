"""API-facing user-message dispatch facade."""

from __future__ import annotations

from typing import Any

from ...core.runtime_bindings import require_user_message_dispatcher
from ...events.user_message_dispatch import (
    ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED,
    ASK_RESPONSE_RESOLVE_FAILED,
    BOOTSTRAP_STATE_UPDATE_FAILED,
    CHAT_STORE_NOT_INITIALIZED,
    CHAT_STORE_PERSIST_FAILED,
    CHAT_TURN_CONFLICT,
    CHAT_PROJECTION_FAILED,
    EMPTY_TURN,
    MALFORMED_ATTACHMENTS,
    MESSAGE_DISPATCHER_NOT_INITIALIZED,
    MessageDispatchOutcome,
    RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
    RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED,
    SESSION_ID_REQUIRED,
)


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
    interaction_kind: str | None = None,
    first_context: dict[str, Any] | None = None,
) -> MessageDispatchOutcome:
    """Forward a user-message request to the active chat ingress service."""

    try:
        dispatcher = require_user_message_dispatcher()
    except RuntimeError as exc:
        return MessageDispatchOutcome(
            success=False,
            user_id=str(user_id),
            session_id=str(session_id or "").strip() or None,
            error_code=MESSAGE_DISPATCHER_NOT_INITIALIZED,
            error_message=str(exc),
        )

    return await dispatcher(
        source=source,
        user_id=user_id,
        message=message,
        session_id=session_id,
        attachments=attachments,
        reply_to_message_id=reply_to_message_id,
        workspace_path=workspace_path,
        client_turn_id=client_turn_id,
        metadata=metadata,
        runtime_namespace=runtime_namespace,
        interaction_kind=interaction_kind,
        first_context=first_context,
    )


__all__ = [
    "ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED",
    "ASK_RESPONSE_RESOLVE_FAILED",
    "BOOTSTRAP_STATE_UPDATE_FAILED",
    "CHAT_STORE_NOT_INITIALIZED",
    "CHAT_STORE_PERSIST_FAILED",
    "CHAT_TURN_CONFLICT",
    "CHAT_PROJECTION_FAILED",
    "EMPTY_TURN",
    "MALFORMED_ATTACHMENTS",
    "MESSAGE_DISPATCHER_NOT_INITIALIZED",
    "MessageDispatchOutcome",
    "RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED",
    "RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED",
    "SESSION_ID_REQUIRED",
    "dispatch_user_message",
]
