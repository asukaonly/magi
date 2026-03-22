"""Shared user-message dispatch helpers for API and websocket transports."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import UserMessageCommand


RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED = "RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED"
RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED = "RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED"
SESSION_ID_REQUIRED = "SESSION_ID_REQUIRED"


@dataclass(slots=True)
class MessageDispatchOutcome:
    success: bool
    user_id: str
    session_id: str | None = None
    turn_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    queue_size: int | None = None


async def dispatch_user_message(
    *,
    source: str,
    user_id: str,
    message: str,
    session_id: str | None = None,
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

    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=SESSION_ID_REQUIRED,
            error_message="Session ID is required.",
        )
    turn_id = str(client_turn_id or "").strip() or f"turn_{uuid.uuid4().hex[:12]}"
    try:
        await runtime_command_queue.enqueue_user_message(
            UserMessageCommand(
                source=source,
                user_id=user_id,
                session_id=resolved_session_id,
                turn_id=turn_id,
                message=message,
                runtime_namespace=str(runtime_namespace or "").strip() or "web",
                metadata=dict(metadata or {}),
                created_at=time.time(),
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
    return MessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=resolved_session_id,
        turn_id=turn_id,
        queue_size=int(queue_size) if isinstance(queue_size, int) else None,
    )
