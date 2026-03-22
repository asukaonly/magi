from __future__ import annotations

import pytest

from magi.api.services import message_dispatch_service as service
from magi.events.events import REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY


class _FakeBus:
    def __init__(self, publish_result: bool = True) -> None:
        self.publish_result = publish_result
        self.events: list[object] = []

    async def publish(self, event) -> bool:
        self.events.append(event)
        return self.publish_result

    async def get_stats(self) -> dict[str, int]:
        return {"queue_size": 5}


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_message_bus_error_when_bus_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "require_message_bus", lambda: (_ for _ in ()).throw(RuntimeError("missing")))

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
    )

    assert outcome.success is False
    assert outcome.error_code == service.MESSAGE_BUS_NOT_INITIALIZED


@pytest.mark.asyncio
async def test_dispatch_user_message_only_requires_message_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = _FakeBus()
    monkeypatch.setattr(service, "require_message_bus", lambda: bus)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is True
    assert outcome.session_id == "session-for-u1"
    assert len(bus.events) == 1


@pytest.mark.asyncio
async def test_dispatch_user_message_publishes_user_message_event(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = _FakeBus()
    monkeypatch.setattr(service, "require_message_bus", lambda: bus)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
        metadata={"origin": "test"},
    )

    assert outcome.success is True
    assert outcome.session_id == "session-for-u1"
    assert outcome.turn_id is not None
    assert outcome.queue_size == 5
    assert len(bus.events) == 1
    event = bus.events[0]
    assert event.type == "UserMessage"
    assert event.source == "api"
    assert event.data["content"] == "hello"
    assert event.data["author_type"] == "user"
    assert event.data["content_type"] == "text"
    assert event.data["metadata"]["origin"] == "test"
    assert "message" not in event.data
    assert event.metadata[REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY] is True


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_publish_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = _FakeBus(publish_result=False)
    monkeypatch.setattr(service, "require_message_bus", lambda: bus)

    outcome = await service.dispatch_user_message(
        source="websocket",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is False
    assert outcome.error_code == service.MESSAGE_BUS_PUBLISH_FAILED


@pytest.mark.asyncio
async def test_dispatch_user_message_preserves_explicit_session_turn_and_runtime_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = _FakeBus()
    monkeypatch.setattr(service, "require_message_bus", lambda: bus)

    outcome = await service.dispatch_user_message(
        source="websocket",
        user_id="u1",
        message="hello",
        session_id="explicit-session",
        client_turn_id="turn-client-1",
        runtime_namespace=" telegram ",
    )

    assert outcome.success is True
    assert outcome.session_id == "explicit-session"
    assert outcome.turn_id == "turn-client-1"
    event = bus.events[0]
    assert event.data["session_id"] == "explicit-session"
    assert event.data["turn_id"] == "turn-client-1"
    assert event.data["runtime_namespace"] == "telegram"


@pytest.mark.asyncio
async def test_dispatch_user_message_rejects_missing_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = _FakeBus()
    monkeypatch.setattr(service, "require_message_bus", lambda: bus)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id=None,
    )

    assert outcome.success is False
    assert outcome.error_code == service.SESSION_ID_REQUIRED
    assert bus.events == []
