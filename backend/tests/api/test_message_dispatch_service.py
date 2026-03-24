from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(slots=True)
class _FakeCreatedTurn:
    session_id: str
    turn_id: str
    message_id: str


class _FakeChatStore:
    def __init__(self) -> None:
        self.created_turns: list[dict[str, object]] = []

    async def create_user_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None = None,
        created_at_ms: int,
    ) -> _FakeCreatedTurn:
        self.created_turns.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "turn_id": turn_id,
                "message_text": message_text,
                "attachment_payloads": list(attachment_payloads or []),
                "created_at_ms": created_at_ms,
            }
        )
        return _FakeCreatedTurn(
            session_id=session_id,
            turn_id=turn_id,
            message_id=f"msg-{turn_id}",
        )


class _FakeChatProjector:
    def __init__(self) -> None:
        self.user_messages: list[dict[str, object]] = []

    async def project_user_message(self, **kwargs):  # type: ignore[no-untyped-def]
        self.user_messages.append(dict(kwargs))


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
async def test_dispatch_user_message_persists_chat_turn_before_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    chat_projector = _FakeChatProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "require_chat_projector", lambda: chat_projector)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is True
    assert outcome.session_id == "session-for-u1"
    assert outcome.turn_id is not None
    assert len(chat_store.created_turns) == 1
    assert chat_store.created_turns[0]["turn_id"] == outcome.turn_id
    assert chat_store.created_turns[0]["message_text"] == "hello"
    assert chat_projector.user_messages[0]["message_id"] == f"msg-{outcome.turn_id}"
    assert len(queue.commands) == 1


@pytest.mark.asyncio
async def test_dispatch_user_message_publishes_user_message_event(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)

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
    assert command.runtime_namespace == "desktop"


@pytest.mark.asyncio
async def test_dispatch_user_message_carries_attachments_and_workspace_path_into_runtime_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="",
        session_id="session-for-u1",
        attachments=[{"kind": "image", "attachment_id": "att-1"}],
        workspace_path="/Users/asuka/code/magi",
    )

    assert outcome.success is True
    command = queue.commands[0]
    assert command.attachments == [{"kind": "image", "attachment_id": "att-1"}]
    assert command.workspace_path == "/Users/asuka/code/magi"


@pytest.mark.asyncio
async def test_dispatch_user_message_rejects_empty_turn_without_text_or_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="   ",
        session_id="session-for-u1",
        attachments=[],
    )

    assert outcome.success is False
    assert outcome.error_message == "Message text or attachments are required."
    assert queue.commands == []


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_publish_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingRuntimeCommandQueue(_FakeRuntimeCommandQueue):
        async def enqueue_user_message(self, command) -> int:
            raise RuntimeError("boom")

    queue = _FailingRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)

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
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)

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
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id=None,
    )

    assert outcome.success is False
    assert outcome.error_code == service.SESSION_ID_REQUIRED
    assert queue.commands == []


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_chat_persist_failure_before_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingChatStore(_FakeChatStore):
        async def create_user_turn(
            self,
            *,
            session_id: str,
            user_id: str,
            turn_id: str,
            message_text: str,
            attachment_payloads: list[dict[str, object]] | None = None,
            created_at_ms: int,
        ) -> _FakeCreatedTurn:
            _ = attachment_payloads
            raise RuntimeError("persist failed")

    queue = _FakeRuntimeCommandQueue()
    chat_store = _FailingChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "require_chat_store", lambda: chat_store)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is False
    assert outcome.error_code == service.CHAT_STORE_PERSIST_FAILED
    assert queue.commands == []
