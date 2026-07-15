from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from magi.chat import ingress as service
from magi.i18n import language_context
from magi.utils.runtime import get_runtime_paths, set_runtime_dir


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
        message_payload: dict[str, object] | None = None,
        created_at_ms: int,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> _FakeCreatedTurn:
        self.created_turns.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "turn_id": turn_id,
                "message_text": message_text,
                "attachment_payloads": list(attachment_payloads or []),
                "message_payload": dict(message_payload or {}),
                "created_at_ms": created_at_ms,
                "reply_to_message_id": reply_to_message_id,
                "persona_id": persona_id,
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


class _FakeChatReadService:
    def __init__(self, workspace_path: str | None) -> None:
        self.workspace_path = workspace_path

    async def aget_session_summary(self, user_id: str, session_id: str):  # type: ignore[no-untyped-def]
        return type(
            "_Summary",
            (),
            {"workspace_path": self.workspace_path, "user_id": user_id, "session_id": session_id},
        )()


@dataclass(slots=True)
class _FakeAskState:
    request_id: str
    status: str = "pending"
    expires_at: float | None = None


class _FakeControlSessionStore:
    def __init__(self, ask_state: _FakeAskState | None) -> None:
        self._ask_state = ask_state

    def ask_state(self, session_id: str) -> _FakeAskState | None:
        return self._ask_state if session_id == "session-for-u1" else None


class _FakeControlInteractionBroker:
    def __init__(self, resolve_result: bool = True) -> None:
        self.resolve_result = resolve_result
        self.resolutions: list[dict[str, object]] = []

    async def resolve(self, *, interaction_id: str, kind: str, response: object) -> bool:
        self.resolutions.append(
            {
                "interaction_id": interaction_id,
                "kind": kind,
                "response": response,
            }
        )
        return self.resolve_result


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_message_bus_error_when_bus_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service,
        "require_runtime_command_queue",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
    )

    assert outcome.success is False
    assert outcome.error_code == service.RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED


@pytest.mark.asyncio
async def test_dispatch_user_message_persists_chat_turn_before_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    chat_projector = _FakeChatProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: chat_projector)

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
    assert chat_projector.user_messages[0]["metadata"] == {}
    assert len(queue.commands) == 1


@pytest.mark.asyncio
async def test_dispatch_user_message_persists_and_enqueues_recall_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    chat_projector = _FakeChatProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: chat_projector)

    feedback = {
        "kind": "item_irrelevant",
        "target_message_id": "assistant-1",
        "finding_ref": "event:event-1",
    }
    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="Leave this record out.",
        session_id="session-for-u1",
        reply_to_message_id="assistant-1",
        metadata={"recall_feedback": feedback},
    )

    assert outcome.success is True
    assert chat_store.created_turns[0]["message_payload"] == {
        "recall_feedback": feedback,
    }
    assert queue.commands[0].metadata["recall_feedback"] == feedback
    assert chat_projector.user_messages[0]["interaction_kind"] == "recall_feedback"


@pytest.mark.asyncio
async def test_dispatch_user_message_resolves_pending_ask_before_chat_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    broker = _FakeControlInteractionBroker()
    ask_state = _FakeAskState(request_id="ask-1")
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(
        service, "resolve_control_session_store", lambda: _FakeControlSessionStore(ask_state)
    )
    monkeypatch.setattr(service, "resolve_control_interaction_broker", lambda: broker)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="  main  ",
        session_id="session-for-u1",
    )

    assert outcome.success is True
    assert outcome.handled_as == "ask_response"
    assert outcome.ask_request_id == "ask-1"
    assert outcome.session_id == "session-for-u1"
    assert chat_store.created_turns == []
    assert queue.commands == []
    assert broker.resolutions == [
        {
            "interaction_id": "ask-1",
            "kind": "ask",
            "response": "main",
        }
    ]


@pytest.mark.asyncio
async def test_dispatch_recall_feedback_does_not_answer_a_pending_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    broker = _FakeControlInteractionBroker()
    ask_state = _FakeAskState(request_id="ask-1")
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(
        service,
        "resolve_control_session_store",
        lambda: _FakeControlSessionStore(ask_state),
    )
    monkeypatch.setattr(service, "resolve_control_interaction_broker", lambda: broker)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="Leave that record out.",
        session_id="session-for-u1",
        metadata={
            "recall_feedback": {
                "kind": "item_irrelevant",
                "target_message_id": "assistant-1",
                "finding_ref": "event:event-1",
            }
        },
    )

    assert outcome.success is False
    assert outcome.error_code == service.RECALL_FEEDBACK_PENDING_ASK
    assert broker.resolutions == []
    assert chat_store.created_turns == []
    assert queue.commands == []


@pytest.mark.asyncio
async def test_dispatch_user_message_rejects_pending_ask_answer_with_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    broker = _FakeControlInteractionBroker()
    ask_state = _FakeAskState(request_id="ask-1")
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(
        service, "resolve_control_session_store", lambda: _FakeControlSessionStore(ask_state)
    )
    monkeypatch.setattr(service, "resolve_control_interaction_broker", lambda: broker)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="main",
        session_id="session-for-u1",
        attachments=[{"kind": "file", "attachment_id": "att-1"}],
    )

    assert outcome.success is False
    assert outcome.error_code == service.ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED
    assert outcome.handled_as == "ask_response"
    assert chat_store.created_turns == []
    assert queue.commands == []
    assert broker.resolutions == []


@pytest.mark.asyncio
async def test_dispatch_user_message_stores_active_persona_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()

    async def _fake_active_persona_id() -> str:
        return "persona-active"

    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "_resolve_active_persona_id", _fake_active_persona_id)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is True
    assert chat_store.created_turns[0]["persona_id"] == "persona-active"


@pytest.mark.asyncio
async def test_dispatch_user_message_projects_only_l2_queue_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    chat_projector = _FakeChatProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: chat_projector)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
        metadata={
            "origin": "test",
            "l2_batch_owner": "bootstrap:u1:test",
            "l2_batch_max_events": 1,
        },
    )

    assert outcome.success is True
    assert chat_projector.user_messages[0]["metadata"] == {
        "l2_batch_owner": "bootstrap:u1:test",
        "l2_batch_max_events": 1,
    }


@pytest.mark.asyncio
async def test_dispatch_user_message_publishes_user_message_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

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
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="",
        session_id="session-for-u1",
        attachments=[{"kind": "image", "attachment_id": "att-1"}],
        workspace_path="/tmp/magi",
    )

    assert outcome.success is True
    command = queue.commands[0]
    assert command.attachments == [{"kind": "image", "attachment_id": "att-1"}]
    assert command.workspace_path == "/tmp/magi"


@pytest.mark.asyncio
async def test_dispatch_user_message_prepares_text_attachment_before_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_runtime_base = get_runtime_paths().base_dir
    set_runtime_dir(tmp_path / "runtime")
    try:
        queue = _FakeRuntimeCommandQueue()
        chat_store = _FakeChatStore()
        monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
        monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
        attachment_dir = get_runtime_paths().chat_files_dir / "session-for-u1" / "turn-client-1"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        attachment_path = attachment_dir / "att-1__notes.md"
        attachment_path.write_text("# hello\nworld\n", encoding="utf-8")

        outcome = await service.dispatch_user_message(
            source="api",
            user_id="u1",
            message="",
            session_id="session-for-u1",
            client_turn_id="turn-client-1",
            attachments=[
                {
                    "kind": "text_file",
                    "attachment_id": "att-1",
                    "original_name": "notes.md",
                    "mime_type": "text/markdown",
                    "size_bytes": attachment_path.stat().st_size,
                    "storage_path": str(attachment_path),
                    "sha256": "sha",
                    "parse_status": "pending",
                }
            ],
        )

        assert outcome.success is True
        stored_attachment = chat_store.created_turns[0]["attachment_payloads"][0]
        assert stored_attachment["parse_status"] == "parsed"
        assert stored_attachment["derived_text_excerpt"] == "# hello\nworld\n"
        assert Path(str(stored_attachment["derived_text_path"])).is_file()
        assert queue.commands[0].attachments[0]["parse_status"] == "parsed"
    finally:
        set_runtime_dir(original_runtime_base)


@pytest.mark.asyncio
async def test_dispatch_user_message_falls_back_to_session_workspace_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(
        service,
        "get_chat_read_service",
        lambda: _FakeChatReadService("/tmp/magi"),
    )

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
        workspace_path=None,
    )

    assert outcome.success is True
    command = queue.commands[0]
    assert command.workspace_path == "/tmp/magi"


@pytest.mark.asyncio
async def test_dispatch_user_message_rejects_empty_turn_without_text_or_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

    with language_context("en"):
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
async def test_dispatch_user_message_rejects_empty_turn_in_zh_cn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

    with language_context("zh-CN"):
        outcome = await service.dispatch_user_message(
            source="api",
            user_id="u1",
            message="   ",
            session_id="session-for-u1",
            attachments=[],
        )

    assert outcome.success is False
    assert outcome.error_message == "请输入消息或添加附件。"
    assert queue.commands == []


@pytest.mark.asyncio
async def test_dispatch_user_message_returns_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingRuntimeCommandQueue(_FakeRuntimeCommandQueue):
        async def enqueue_user_message(self, command) -> int:
            raise RuntimeError("boom")

    queue = _FailingRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

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
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

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
async def test_dispatch_user_message_rejects_missing_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

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
            reply_to_message_id: str | None = None,
            persona_id: str | None = None,
        ) -> _FakeCreatedTurn:
            _ = (attachment_payloads, reply_to_message_id, persona_id)
            raise RuntimeError("persist failed")

    queue = _FakeRuntimeCommandQueue()
    chat_store = _FailingChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-for-u1",
    )

    assert outcome.success is False
    assert outcome.error_code == service.CHAT_STORE_PERSIST_FAILED
    assert queue.commands == []
