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


class _FakeRuntimeCommandQueue:
    def __init__(self, queue_size: int = 5) -> None:
        self.queue_size = queue_size
        self.commands: list[object] = []
        self.next_command_id = 1

    async def enqueue_user_message(self, command) -> int:
        self.commands.append(command)
        command_id = self.next_command_id
        self.next_command_id += 1
        return command_id

    async def get_stats(self) -> dict[str, int]:
        return {"pending_count": self.queue_size}


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_message_bus_error_when_bus_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: (_ for _ in ()).throw(RuntimeError("missing")))

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
    )

    assert outcome.success is False
    assert outcome.error_code == service.RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED


@pytest.mark.asyncio
async def test_dispatch_user_message_only_requires_message_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _FakeRuntimeCommandQueue()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is True
    assert outcome.session_id == "session-for-u1"
    assert len(queue.commands) == 1


@pytest.mark.asyncio
async def test_dispatch_user_message_publishes_user_message_event(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _FakeRuntimeCommandQueue()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)

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
    assert len(queue.commands) == 1
    command = queue.commands[0]
    assert command.source == "api"
    assert command.message == "hello"
    assert command.metadata["origin"] == "test"
    assert command.runtime_namespace == "web"


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_publish_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingRuntimeCommandQueue(_FakeRuntimeCommandQueue):
        async def enqueue_user_message(self, command) -> int:
            raise RuntimeError("boom")

    queue = _FailingRuntimeCommandQueue()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)

    outcome = await service.dispatch_user_message(
        source="websocket",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is False
    assert outcome.error_code == service.RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED


@pytest.mark.asyncio
async def test_dispatch_user_message_preserves_explicit_session_turn_and_runtime_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)

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
    command = queue.commands[0]
    assert command.session_id == "explicit-session"
    assert command.turn_id == "turn-client-1"
    assert command.runtime_namespace == "telegram"


@pytest.mark.asyncio
async def test_dispatch_user_message_rejects_missing_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _FakeRuntimeCommandQueue()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id=None,
    )

    assert outcome.success is False
    assert outcome.error_code == service.SESSION_ID_REQUIRED
    assert queue.commands == []
