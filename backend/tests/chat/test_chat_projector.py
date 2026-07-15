from __future__ import annotations

import pytest

from magi.chat.projector import ChatProjector
from magi.events.domain_payloads import AssistantResponseProduced, UserMessageReceived
from magi.events.events import Event, EventTypes


class _FakeEventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_chat_projector_publishes_canonical_user_and_assistant_events() -> None:
    bus = _FakeEventBus()
    projector = ChatProjector(event_bus=bus)

    await projector.project_user_message(
        message_id="msg-user-1",
        user_id="u1",
        session_id="s1",
        turn_id="turn-1",
        content="hello",
        created_at_ms=1000,
        interaction_kind="recall_feedback",
    )
    await projector.project_assistant_message(
        message_id="msg-assistant-1",
        user_id="u1",
        session_id="s1",
        turn_id="turn-1",
        content="world",
        created_at_ms=1200,
    )

    assert [event.type for event in bus.events] == [
        EventTypes.USER_MESSAGE_RECEIVED,
        EventTypes.ASSISTANT_RESPONSE_PRODUCED,
    ]

    user_event = bus.events[0]
    assistant_event = bus.events[1]

    assert isinstance(user_event.data, UserMessageReceived)
    assert isinstance(assistant_event.data, AssistantResponseProduced)

    assert user_event.data.content == "hello"
    assert user_event.data.interaction_kind == "recall_feedback"
    assert assistant_event.data.content == "world"

    assert user_event.data.context.session_id == "s1"
    assert user_event.data.context.turn_id == "turn-1"
    assert user_event.data.context.user_id == "u1"
    assert user_event.data.context.task_id is None

    assert user_event.data.metadata["idempotency_key"] == "msg-user-1"
    assert user_event.data.metadata["author_type"] == "user"
    assert user_event.data.metadata["chat_message_id"] == "msg-user-1"
    assert user_event.data.metadata["chat_projection"] is True

    assert assistant_event.data.metadata["idempotency_key"] == "msg-assistant-1"
    assert assistant_event.data.metadata["author_type"] == "assistant"

    assert user_event.timestamp == 1.0
    assert assistant_event.timestamp == 1.2
    assert user_event.correlation_id == "turn-1"
    assert user_event.source == "chat"
    assert assistant_event.source == "chat"


@pytest.mark.asyncio
async def test_chat_projector_skips_empty_content() -> None:
    bus = _FakeEventBus()
    projector = ChatProjector(event_bus=bus)

    await projector.project_user_message(
        message_id="msg-empty",
        user_id="u1",
        session_id="s1",
        turn_id="turn-1",
        content="   ",
        created_at_ms=1000,
    )
    await projector.project_assistant_message(
        message_id="msg-empty-2",
        user_id="u1",
        session_id="s1",
        turn_id="turn-1",
        content="",
        created_at_ms=1000,
    )

    assert bus.events == []
