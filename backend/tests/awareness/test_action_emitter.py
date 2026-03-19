from __future__ import annotations

import pytest

from magi.awareness.action_emitter import ActionEmitter
from magi.awareness.contracts import ActionEmissionRecord
from magi.events.events import (
    EventTypes,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)


class _FakeMessageBus:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def publish(self, event) -> bool:
        self.events.append(event)
        return True


@pytest.mark.asyncio
async def test_emit_chat_response_marks_event_for_subscriber_delivery() -> None:
    message_bus = _FakeMessageBus()
    emitter = ActionEmitter(message_bus)

    await emitter.emit_chat_response_event(
        user_id="u1",
        session_id="s1",
        response="hello",
        correlation_id="corr-1",
        turn_id="turn-1",
    )

    event = message_bus.events[0]
    assert event.type == EventTypes.AI_RESPONSE
    assert event.metadata[REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY] is True


@pytest.mark.asyncio
async def test_emit_runtime_event_marks_event_for_subscriber_delivery() -> None:
    message_bus = _FakeMessageBus()
    emitter = ActionEmitter(message_bus)

    await emitter.emit_runtime_event(
        event_type="TURN_TRACE_COMPLETED",
        payload={"turn_id": "turn-1"},
        correlation_id="corr-1",
    )

    event = message_bus.events[0]
    assert event.type == "TURN_TRACE_COMPLETED"
    assert event.metadata[REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY] is True


@pytest.mark.asyncio
async def test_emit_action_event_marks_event_for_subscriber_delivery() -> None:
    message_bus = _FakeMessageBus()
    emitter = ActionEmitter(message_bus)

    await emitter.emit_action_event(
        ActionEmissionRecord(
            agent_id="agent-1",
            event_type=EventTypes.USER_MESSAGE,
            payload={"user_id": "u1", "session_id": "s1", "turn_id": "turn-1"},
            correlation_id="corr-1",
        ),
        success=True,
    )

    event = message_bus.events[0]
    assert event.type == EventTypes.ACTION_EXECUTED
    assert event.metadata[REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY] is True
