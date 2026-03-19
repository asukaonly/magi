"""Shared user-message dispatch helpers for API and websocket transports."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from ...core.runtime_bindings import require_agent_runtime, require_message_bus
from ...events.events import (
    Event,
    EventLevel,
    EventTypes,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)
from .chat_read_service import get_chat_read_service


RUNTIME_NOT_INITIALIZED = "RUNTIME_NOT_INITIALIZED"
MESSAGE_BUS_NOT_INITIALIZED = "MESSAGE_BUS_NOT_INITIALIZED"
MESSAGE_BUS_PUBLISH_FAILED = "MESSAGE_BUS_PUBLISH_FAILED"


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
        require_agent_runtime()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=RUNTIME_NOT_INITIALIZED,
            error_message="AgentRuntime not initialized. Please complete onboarding or check the saved configuration.",
        )

    try:
        message_bus = require_message_bus()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=MESSAGE_BUS_NOT_INITIALIZED,
            error_message="Message bus not initialized. Please complete onboarding or check the saved configuration.",
        )

    read_service = get_chat_read_service()
    resolved_session_id = session_id or read_service.get_current_session_id(user_id)
    turn_id = str(client_turn_id or "").strip() or f"turn_{uuid.uuid4().hex[:12]}"
    payload = {
        "message": message,
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
