"""Projection of committed chat content into canonical domain events on the bus."""

from __future__ import annotations

from ..events.domain_payloads import (
    AssistantResponseProduced,
    TaskContext,
    UserMessageReceived,
)
from ..events.events import (
    Event,
    EventLevel,
    EventTypes,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)


CHAT_MEMORY_SOURCE = "chat"


class ChatProjector:
    """Project committed chat transcript entries onto the runtime event bus."""

    def __init__(self, *, event_bus) -> None:
        self._event_bus = event_bus

    async def project_user_message(
        self,
        *,
        message_id: str,
        user_id: str,
        session_id: str,
        turn_id: str,
        content: str,
        created_at_ms: int,
        interaction_kind: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> bool:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return True
        event_metadata = {
            "source_item_id": message_id,
            "author_type": "user",
            "content_type": "text",
            "chat_message_id": message_id,
            "chat_projection": True,
            "idempotency_key": message_id,
            **dict(metadata or {}),
        }
        payload = UserMessageReceived(
            content=normalized_content,
            context=TaskContext(
                session_id=session_id,
                turn_id=turn_id,
                task_id=None,
                user_id=user_id,
            ),
            interaction_kind=str(interaction_kind or "").strip() or None,
            metadata=event_metadata,
        )
        published = await self._event_bus.publish(
            Event(
                type=EventTypes.USER_MESSAGE_RECEIVED,
                data=payload,
                source=CHAT_MEMORY_SOURCE,
                level=EventLevel.INFO,
                timestamp=float(created_at_ms) / 1000.0,
                correlation_id=turn_id,
            )
        )
        if published is False:
            raise RuntimeError("Chat user-message projection was not delivered")
        return True

    async def project_assistant_message(
        self,
        *,
        message_id: str,
        user_id: str,
        session_id: str,
        turn_id: str,
        content: str,
        created_at_ms: int,
        metadata: dict[str, object] | None = None,
    ) -> bool:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return True
        event_metadata = {
            "source_item_id": message_id,
            "author_type": "assistant",
            "content_type": "text",
            "chat_message_id": message_id,
            "chat_projection": True,
            "idempotency_key": message_id,
            **dict(metadata or {}),
        }
        payload = AssistantResponseProduced(
            content=normalized_content,
            context=TaskContext(
                session_id=session_id,
                turn_id=turn_id,
                task_id=None,
                user_id=user_id,
            ),
            metadata=event_metadata,
        )
        published = await self._event_bus.publish(
            Event(
                type=EventTypes.ASSISTANT_RESPONSE_PRODUCED,
                data=payload,
                source=CHAT_MEMORY_SOURCE,
                level=EventLevel.INFO,
                timestamp=float(created_at_ms) / 1000.0,
                correlation_id=turn_id,
                metadata={REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True},
            )
        )
        if published is False:
            raise RuntimeError("Chat assistant-message projection was not delivered")
        return True
