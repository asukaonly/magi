from __future__ import annotations

import pytest

from magi.chat.projector import ChatProjector
from magi.memory.event_contracts import MemoryEvent


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.events: list[MemoryEvent] = []

    async def ingest_event(self, event):  # type: ignore[no-untyped-def]
        self.events.append(event)
        return {
            "event_id": getattr(event, "event_id", "evt-1"),
            "ingest_target": getattr(getattr(event, "ingest_target", None), "label", "l1_only"),
            "l1_written": True,
            "l2_relation_count": 0,
            "l2_assertion_count": 0,
            "l4_skill_id": None,
        }


@pytest.mark.asyncio
async def test_chat_projector_emits_canonical_user_and_assistant_memory_events() -> None:
    memory = _FakeUnifiedMemory()
    projector = ChatProjector(unified_memory=memory)

    await projector.project_user_message(
        message_id="msg-user-1",
        user_id="u1",
        session_id="s1",
        turn_id="turn-1",
        content="hello",
        created_at_ms=1000,
    )
    await projector.project_assistant_message(
        message_id="msg-assistant-1",
        user_id="u1",
        session_id="s1",
        turn_id="turn-1",
        content="world",
        created_at_ms=1200,
    )

    assert [event.event_type for event in memory.events] == ["UserMessage", "AIResponse"]
    assert memory.events[0].event_id == "chat_msg-user-1"
    assert memory.events[1].event_id == "chat_msg-assistant-1"
    assert memory.events[0].content == "hello"
    assert memory.events[1].content == "world"
