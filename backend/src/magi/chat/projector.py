"""Projection of committed chat content into canonical memory events."""

from __future__ import annotations

from ..events.events import Event, EventLevel, EventTypes
from ..memory import UnifiedMemoryStore
from ..memory.event_contracts import normalize_runtime_event


class ChatProjector:
    """Project committed chat transcript entries into L1 memory."""

    def __init__(self, *, unified_memory: UnifiedMemoryStore) -> None:
        self._unified_memory = unified_memory

    async def project_user_message(
        self,
        *,
        message_id: str,
        user_id: str,
        session_id: str,
        turn_id: str,
        content: str,
        created_at_ms: int,
    ) -> None:
        await self._project(
            event_type=EventTypes.USER_MESSAGE,
            message_id=message_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            created_at_ms=created_at_ms,
        )

    async def project_assistant_message(
        self,
        *,
        message_id: str,
        user_id: str,
        session_id: str,
        turn_id: str,
        content: str,
        created_at_ms: int,
    ) -> None:
        await self._project(
            event_type=EventTypes.AI_RESPONSE,
            message_id=message_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            created_at_ms=created_at_ms,
        )

    async def _project(
        self,
        *,
        event_type: str,
        message_id: str,
        user_id: str,
        session_id: str,
        turn_id: str,
        content: str,
        created_at_ms: int,
    ) -> None:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return
        event = Event(
            type=event_type,
            data={
                "content": normalized_content,
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "source_item_id": message_id,
                "author_type": "user" if event_type == EventTypes.USER_MESSAGE else "assistant",
                "content_type": "text",
            },
            source="chat_projector",
            level=EventLevel.INFO,
            timestamp=float(created_at_ms) / 1000.0,
            correlation_id=turn_id,
            metadata={
                "chat_message_id": message_id,
                "chat_projection": True,
            },
        )
        memory_event = normalize_runtime_event(event, idempotency_key=message_id)
        await self._unified_memory.ingest_event(memory_event)
