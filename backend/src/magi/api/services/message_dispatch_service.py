"""Shared user-message dispatch helpers for API and websocket transports."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from ...core.runtime_bindings import require_message_bus
from ...events.events import (
    Event,
    EventLevel,
    EventTypes,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)


MESSAGE_BUS_NOT_INITIALIZED = "MESSAGE_BUS_NOT_INITIALIZED"
MESSAGE_BUS_PUBLISH_FAILED = "MESSAGE_BUS_PUBLISH_FAILED"
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
    """Resolve session metadata and enqueue a USER_MESSAGE event."""

    try:
        message_bus = require_message_bus()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=MESSAGE_BUS_NOT_INITIALIZED,
            error_message="Message bus not initialized. Please complete onboarding or check the saved configuration.",
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
    payload = {
        "content": message,
        "author_type": "user",
        "content_type": "text",
        "user_id": user_id,
        "runtime_namespace": str(runtime_namespace or "").strip() or None,
        "session_id": resolved_session_id,
        "turn_id": turn_id,
        "timestamp": time.time(),
    }
    if metadata:
        payload["metadata"] = dict(metadata)

    published = await message_bus.publish(
        Event(
            type=EventTypes.USER_MESSAGE,
            data=payload,
            source=source,
            level=EventLevel.INFO,
            metadata={REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True},
        )
    )
    if not published:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            turn_id=turn_id,
            error_code=MESSAGE_BUS_PUBLISH_FAILED,
            error_message="Message bus publish failed",
        )

    stats = await message_bus.get_stats()
    queue_size = stats.get("queue_size") if isinstance(stats, dict) else None
    return MessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=resolved_session_id,
        turn_id=turn_id,
        queue_size=int(queue_size) if isinstance(queue_size, int) else None,
    )
