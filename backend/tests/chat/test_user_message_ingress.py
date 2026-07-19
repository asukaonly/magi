from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.chat import ingress as service
from magi.chat import first_context_projection as projection_confirmation
from magi.core.operation_barrier import AsyncOperationBarrier
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

    @asynccontextmanager
    async def user_message_operation(self):  # type: ignore[no-untyped-def]
        yield

    async def is_user_message_scope_blocked(self, **scope) -> bool:  # type: ignore[no-untyped-def]
        _ = scope
        return False

    async def enqueue_user_message(self, command) -> int:
        for index, existing in enumerate(self.commands, start=1):
            if (
                existing.correlation_id == command.correlation_id
                and existing.delivery_attempt_no == command.delivery_attempt_no
            ):
                return index
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
    created_at_ms: int
    persona_id: str | None = None


class _FakeChatStore:
    def __init__(self) -> None:
        self.created_turns: list[dict[str, object]] = []
        self.turns_by_id: dict[str, _FakeCreatedTurn] = {}
        self.delivery_by_id: dict[str, dict[str, object]] = {}
        self.runtime_envelope_by_id: dict[str, dict[str, object]] = {}
        self.request_fingerprint_by_id: dict[str, str] = {}

    async def load_user_turn_once(
        self,
        *,
        turn_id: str,
        request_fingerprint: str,
    ):  # type: ignore[no-untyped-def]
        existing = self.turns_by_id.get(turn_id)
        if existing is None:
            return None
        if self.request_fingerprint_by_id[turn_id] != request_fingerprint:
            raise service.ChatTurnConflictError("turn request conflict")
        delivery = self.delivery_by_id[turn_id]
        return type(
            "_Result",
            (),
            {
                "message": existing,
                "created": False,
                "projection_completed": delivery["projection_completed"],
                "delivery_attempt_no": delivery["delivery_attempt_no"],
                "delivery_state": delivery["delivery_state"],
                "current_command_id": delivery["current_command_id"],
                "runtime_envelope": dict(self.runtime_envelope_by_id[turn_id]),
            },
        )()

    async def create_user_turn_once(
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
        runtime_envelope: dict[str, object] | None = None,
        request_fingerprint: str = "",
    ):  # type: ignore[no-untyped-def]
        existing = self.turns_by_id.get(turn_id)
        if existing is not None:
            if self.request_fingerprint_by_id[turn_id] != request_fingerprint:
                raise service.ChatTurnConflictError("turn envelope conflict")
            delivery = self.delivery_by_id[turn_id]
            return type(
                "_Result",
                (),
                {
                    "message": existing,
                    "created": False,
                    "projection_completed": delivery["projection_completed"],
                    "delivery_attempt_no": delivery["delivery_attempt_no"],
                    "delivery_state": delivery["delivery_state"],
                    "current_command_id": delivery["current_command_id"],
                    "runtime_envelope": dict(self.runtime_envelope_by_id[turn_id]),
                },
            )()
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
        created = _FakeCreatedTurn(
            session_id=session_id,
            turn_id=turn_id,
            message_id=f"msg-{turn_id}",
            created_at_ms=created_at_ms,
            persona_id=persona_id,
        )
        self.turns_by_id[turn_id] = created
        self.delivery_by_id[turn_id] = {
            "projection_completed": False,
            "delivery_attempt_no": 0,
            "delivery_state": "ready",
            "current_command_id": None,
        }
        self.runtime_envelope_by_id[turn_id] = dict(runtime_envelope or {})
        self.request_fingerprint_by_id[turn_id] = request_fingerprint
        return type(
            "_Result",
            (),
            {
                "message": created,
                "created": True,
                "projection_completed": False,
                "delivery_attempt_no": 0,
                "delivery_state": "ready",
                "current_command_id": None,
                "runtime_envelope": dict(runtime_envelope or {}),
            },
        )()

    async def mark_user_turn_projection_completed(
        self, *, turn_id: str, updated_at_ms: int
    ) -> None:
        _ = updated_at_ms
        self.delivery_by_id[turn_id]["projection_completed"] = True

    async def mark_user_turn_delivery_queued(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        _ = updated_at_ms
        delivery = self.delivery_by_id[turn_id]
        if (
            delivery["delivery_state"] != "ready"
            or delivery["delivery_attempt_no"] != delivery_attempt_no
            or delivery["current_command_id"] is not None
        ):
            return False
        delivery["delivery_state"] = "queued"
        delivery["current_command_id"] = command_id
        return True

    async def get_user_turn_delivery(self, *, turn_id: str):  # type: ignore[no-untyped-def]
        delivery = self.delivery_by_id.get(turn_id)
        if delivery is None:
            return None
        return SimpleNamespace(
            delivery_attempt_no=delivery["delivery_attempt_no"],
            delivery_state=delivery["delivery_state"],
            current_command_id=delivery["current_command_id"],
        )


class _FakeChatProjector:
    def __init__(self) -> None:
        self.user_messages: list[dict[str, object]] = []

    async def project_user_message(self, **kwargs):  # type: ignore[no-untyped-def]
        self.user_messages.append(dict(kwargs))


class _FakeChatMessageNotifier:
    def __init__(self) -> None:
        self.upserts: list[dict[str, str]] = []

    async def broadcast_chat_message_upsert(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        self.upserts.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "message_id": message_id,
            }
        )


@pytest.fixture(autouse=True)
def _default_chat_projector(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    projector = _FakeChatProjector()
    monkeypatch.setattr(service, "get_chat_projector", lambda: projector)
    return projector


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
    options: tuple[str, ...] = ()
    allow_free_text: bool = True


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
async def test_dispatch_accepts_agent_admission_before_queue_stage_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_store = _FakeChatStore()

    class _FastAdmissionQueue(_FakeRuntimeCommandQueue):
        async def enqueue_user_message(self, command) -> int:
            command_id = await super().enqueue_user_message(command)
            delivery = chat_store.delivery_by_id[command.turn_id]
            delivery["delivery_state"] = "admitted"
            delivery["current_command_id"] = command_id
            return command_id

    queue = _FastAdmissionQueue()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="fast handoff",
        session_id="session-fast-admission",
        client_turn_id="turn-fast-admission",
    )

    assert outcome.success is True
    assert chat_store.delivery_by_id["turn-fast-admission"] == {
        "projection_completed": True,
        "delivery_attempt_no": 0,
        "delivery_state": "admitted",
        "current_command_id": 1,
    }


@pytest.mark.asyncio
async def test_dispatch_rejects_deleted_scope_before_chat_or_memory_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BlockedQueue(_FakeRuntimeCommandQueue):
        async def is_user_message_scope_blocked(self, **scope) -> bool:  # type: ignore[no-untyped-def]
            return scope["session_id"] == "session-deleted"

    queue = _BlockedQueue()
    chat_store = _FakeChatStore()
    chat_projector = _FakeChatProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: chat_projector)

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="must not be recreated",
        session_id="session-deleted",
        client_turn_id="turn-deleted",
    )

    assert outcome.success is False
    assert outcome.error_code == service.CHAT_SCOPE_DELETED
    assert chat_store.created_turns == []
    assert chat_projector.user_messages == []
    assert queue.commands == []


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
async def test_dispatch_user_message_rejects_non_option_choice_only_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    broker = _FakeControlInteractionBroker()
    ask_state = _FakeAskState(
        request_id="ask-1",
        options=("main", "later"),
        allow_free_text=False,
    )
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
        message="something else",
        session_id="session-for-u1",
    )

    assert outcome.success is False
    assert outcome.error_code == service.ASK_RESPONSE_OPTION_REQUIRED
    assert outcome.handled_as == "ask_response"
    assert broker.resolutions == []
    assert chat_store.created_turns == []
    assert queue.commands == []


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
    assert len(command.attachments) == 1
    assert command.attachments[0]["kind"] == "image"
    assert command.attachments[0]["attachment_id"] == "att-1"
    assert command.attachments[0]["session_id"] == "session-for-u1"
    assert command.attachments[0]["turn_id"] == outcome.turn_id
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
        async def create_user_turn_once(
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
            runtime_envelope: dict[str, object] | None = None,
            request_fingerprint: str = "",
        ) -> _FakeCreatedTurn:
            _ = (
                attachment_payloads,
                message_payload,
                reply_to_message_id,
                persona_id,
                runtime_envelope,
                request_fingerprint,
            )
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


@pytest.mark.asyncio
async def test_dispatch_and_clear_share_one_linear_boundary_without_partial_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoundaryRuntimeCommandQueue(_FakeRuntimeCommandQueue):
        def __init__(self) -> None:
            super().__init__()
            self._barrier = AsyncOperationBarrier()
            self.generation = 0

        @asynccontextmanager
        async def user_message_operation(self):  # type: ignore[no-untyped-def]
            async with self._barrier.operation():
                yield

        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            async with self._barrier.exclusive():
                yield

        async def advance_user_message_generation_and_purge(self) -> tuple[int, int]:
            self.generation += 1
            purged = len(self.commands)
            self.commands.clear()
            return self.generation, purged

    memory_barrier = AsyncOperationBarrier()
    projection_started = asyncio.Event()
    projection_release = asyncio.Event()

    class _BlockingProjector(_FakeChatProjector):
        async def project_user_message(self, **kwargs):  # type: ignore[no-untyped-def]
            async with memory_barrier.operation():
                self.user_messages.append(dict(kwargs))
                projection_started.set()
                await projection_release.wait()

    queue = _BoundaryRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    chat_projector = _BlockingProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: chat_projector)

    dispatch_task = asyncio.create_task(
        service.dispatch_user_message(
            source="api",
            user_id="u1",
            message="clear me atomically",
            session_id="session-for-u1",
        )
    )
    await asyncio.wait_for(projection_started.wait(), timeout=1)
    assert len(chat_store.created_turns) == 1
    assert len(chat_projector.user_messages) == 1
    assert queue.commands == []

    clear_waiting = asyncio.Event()
    clear_entered = asyncio.Event()

    async def _clear() -> None:
        clear_waiting.set()
        async with queue.user_message_clear_boundary():
            clear_entered.set()
            await queue.advance_user_message_generation_and_purge()
            async with memory_barrier.exclusive():
                chat_store.created_turns.clear()
                chat_projector.user_messages.clear()

    clear_task = asyncio.create_task(_clear())
    await asyncio.wait_for(clear_waiting.wait(), timeout=1)
    await asyncio.sleep(0)
    assert not clear_entered.is_set()

    projection_release.set()
    outcome, _ = await asyncio.wait_for(
        asyncio.gather(dispatch_task, clear_task),
        timeout=2,
    )

    assert outcome.success is True
    assert chat_store.created_turns == []
    assert chat_projector.user_messages == []
    assert queue.commands == []


@pytest.mark.asyncio
async def test_dispatch_started_during_clear_waits_and_is_fully_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoundaryRuntimeCommandQueue(_FakeRuntimeCommandQueue):
        def __init__(self) -> None:
            super().__init__()
            self._barrier = AsyncOperationBarrier()

        @asynccontextmanager
        async def user_message_operation(self):  # type: ignore[no-untyped-def]
            async with self._barrier.operation():
                yield

        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            async with self._barrier.exclusive():
                yield

    queue = _BoundaryRuntimeCommandQueue()
    chat_store = _FakeChatStore()
    chat_projector = _FakeChatProjector()
    clear_entered = asyncio.Event()
    clear_release = asyncio.Event()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: chat_projector)

    async def _hold_clear() -> None:
        async with queue.user_message_clear_boundary():
            clear_entered.set()
            await clear_release.wait()

    clear_task = asyncio.create_task(_hold_clear())
    await asyncio.wait_for(clear_entered.wait(), timeout=1)
    dispatch_task = asyncio.create_task(
        service.dispatch_user_message(
            source="api",
            user_id="u1",
            message="keep me completely",
            session_id="session-for-u1",
        )
    )
    await asyncio.sleep(0)
    assert chat_store.created_turns == []
    assert chat_projector.user_messages == []
    assert queue.commands == []

    clear_release.set()
    await asyncio.wait_for(clear_task, timeout=1)
    outcome = await asyncio.wait_for(dispatch_task, timeout=1)

    assert outcome.success is True
    assert len(chat_store.created_turns) == 1
    assert len(chat_projector.user_messages) == 1
    assert len(queue.commands) == 1


@pytest.mark.asyncio
async def test_same_turn_retry_completes_enqueue_without_duplicate_delivery(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    from magi.chat.store import ChatStore
    from magi.personality.bootstrap_service import BootstrapDialogueService

    class _FailOnceQueue(_FakeRuntimeCommandQueue):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def enqueue_user_message(self, command) -> int:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary enqueue failure")
            return await super().enqueue_user_message(command)

    class _GrowthEngine:
        def __init__(self) -> None:
            self.milestones: list[SimpleNamespace] = []

        async def get_milestones(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return list(self.milestones)

        async def record_milestone(self, **kwargs):  # type: ignore[no-untyped-def]
            self.milestones.append(SimpleNamespace(metadata=dict(kwargs.get("metadata") or {})))

    queue = _FailOnceQueue()
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    chat_projector = _FakeChatProjector()
    growth = _GrowthEngine()
    notifier = _FakeChatMessageNotifier()

    async def _active_persona_id() -> str:
        return "persona-active"

    async def _growth_engine():
        return growth

    async def _projection_confirmed(*, message_id: str) -> bool:
        _ = message_id
        return True

    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: chat_projector)
    monkeypatch.setattr(service, "get_chat_message_notifier", lambda: notifier)
    monkeypatch.setattr(
        service,
        "wait_for_first_context_memory_projection",
        _projection_confirmed,
    )
    monkeypatch.setattr(service, "_resolve_active_persona_id", _active_persona_id)
    monkeypatch.setattr(
        "magi.personality.active_persona.get_current_personality",
        lambda: "test-persona",
    )
    monkeypatch.setattr(
        "magi.personality.bootstrap_service.get_shared_growth_engine",
        _growth_engine,
    )

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "我最近失恋了，你能陪我聊聊吗？",
        "session_id": "session-first-context",
        "client_turn_id": "turn-first-context",
        "interaction_kind": "first_context_story",
        "first_context": {
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    }

    first = await service.dispatch_user_message(**request)
    assert first.success is False
    assert first.error_code == service.RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED
    assert growth.milestones == []
    assert notifier.upserts == []

    second = await service.dispatch_user_message(**request)
    assert notifier.upserts == [
        {
            "user_id": "u1",
            "session_id": "session-first-context",
            "message_id": second.message_id,
        }
    ]
    third = await service.dispatch_user_message(**request)

    assert second.success is True
    assert third.success is True
    assert second.message_id == third.message_id
    assert len(chat_projector.user_messages) == 1
    assert len(queue.commands) == 1
    assert queue.attempts == 2
    assert queue.commands[0].correlation_id == f"user_message:{second.message_id}"
    assert len(notifier.upserts) == 2
    assert notifier.upserts[1] == notifier.upserts[0]
    assert len(growth.milestones) == 1
    bootstrap = BootstrapDialogueService(growth_engine=growth)  # type: ignore[arg-type]
    assert (
        await bootstrap.needs_bootstrap_init(
            "test-persona",
            persona_id="persona-active",
        )
        is False
    )

    with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE turn_id = ? AND role = 'user'",
            ("turn-first-context",),
        ).fetchone() == (1,)
        assert db.execute(
            """
            SELECT projection_completed, delivery_attempt_no,
                   delivery_state, current_command_id
            FROM chat_user_turn_delivery
            WHERE turn_id = ?
            """,
            ("turn-first-context",),
        ).fetchone() == (1, 0, "queued", 1)


@pytest.mark.asyncio
async def test_same_turn_retry_skips_hook_and_attachment_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.hooks.contracts import HookDecision

    class _FailOnceQueue(_FakeRuntimeCommandQueue):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def enqueue_user_message(self, command) -> int:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary enqueue failure")
            return await super().enqueue_user_message(command)

    queue = _FailOnceQueue()
    store = _FakeChatStore()
    hook_calls = 0
    attachment_prepare_calls = 0

    async def _modify_hook(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal hook_calls
        _ = (args, kwargs)
        hook_calls += 1
        return HookDecision.modify(user_message=f"hooked-{hook_calls}")

    async def _prepare_attachments(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal attachment_prepare_calls
        attachment_prepare_calls += 1
        return [
            {
                **dict(item),
                "prepared_once": attachment_prepare_calls,
            }
            for item in kwargs["attachments"]
        ]

    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(service, "_prepare_runtime_attachments", _prepare_attachments)
    monkeypatch.setattr("magi.hooks.dispatch.dispatch_hook", _modify_hook)

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "raw input",
        "session_id": "session-hook-retry",
        "client_turn_id": "turn-hook-retry",
        "attachments": [{"kind": "file", "attachment_id": "attachment-1"}],
    }
    first = await service.dispatch_user_message(**request)
    second = await service.dispatch_user_message(**request)

    assert first.error_code == service.RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED
    assert second.success is True
    assert hook_calls == 1
    assert attachment_prepare_calls == 1
    assert queue.attempts == 2
    assert queue.commands[0].message == "hooked-1"
    assert queue.commands[0].attachments[0]["prepared_once"] == 1


@pytest.mark.asyncio
async def test_existing_turn_retry_bypasses_new_pending_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailRuntimeStageOnceStore(_FakeChatStore):
        def __init__(self) -> None:
            super().__init__()
            self.runtime_stage_attempts = 0

        async def mark_user_turn_delivery_queued(
            self,
            *,
            turn_id: str,
            delivery_attempt_no: int,
            command_id: int,
            updated_at_ms: int,
        ) -> bool:
            self.runtime_stage_attempts += 1
            if self.runtime_stage_attempts == 1:
                raise RuntimeError("temporary runtime-stage failure")
            return await super().mark_user_turn_delivery_queued(
                turn_id=turn_id,
                delivery_attempt_no=delivery_attempt_no,
                command_id=command_id,
                updated_at_ms=updated_at_ms,
            )

    queue = _FakeRuntimeCommandQueue()
    store = _FailRuntimeStageOnceStore()
    broker = _FakeControlInteractionBroker()
    active_ask: _FakeAskState | None = None

    class _DynamicControlSessionStore:
        def ask_state(self, session_id: str) -> _FakeAskState | None:
            _ = session_id
            return active_ask

    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(
        service,
        "resolve_control_session_store",
        lambda: _DynamicControlSessionStore(),
    )
    monkeypatch.setattr(service, "resolve_control_interaction_broker", lambda: broker)

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "original user message",
        "session_id": "session-pending-ask-retry",
        "client_turn_id": "turn-pending-ask-retry",
    }
    first = await service.dispatch_user_message(**request)
    active_ask = _FakeAskState(request_id="ask-created-by-runtime")
    second = await service.dispatch_user_message(**request)

    assert first.error_code == service.CHAT_STORE_PERSIST_FAILED
    assert second.success is True
    assert second.handled_as is None
    assert store.runtime_stage_attempts == 2
    assert len(queue.commands) == 1
    assert broker.resolutions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("attachments", [{"kind": "file", "attachment_id": "attachment-2"}]),
        ("workspace_path", "/workspace/two"),
        ("metadata", {"custom": "two"}),
    ],
)
async def test_same_turn_retry_rejects_caller_owned_input_drift(
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
    changed_value: object,
) -> None:
    class _FailingQueue(_FakeRuntimeCommandQueue):
        async def enqueue_user_message(self, command) -> int:
            _ = command
            raise RuntimeError("leave persisted turn incomplete")

    async def _prepare_attachments(**kwargs):  # type: ignore[no-untyped-def]
        return [dict(item) for item in kwargs["attachments"]]

    queue = _FailingQueue()
    store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(service, "_prepare_runtime_attachments", _prepare_attachments)

    first_request: dict[str, object] = {
        "source": "api",
        "user_id": "u1",
        "message": "same text",
        "session_id": "session-request-drift",
        "client_turn_id": "turn-request-drift",
        "attachments": [{"kind": "file", "attachment_id": "attachment-1"}],
        "workspace_path": "/workspace/one",
        "metadata": {"custom": "one"},
    }
    second_request = dict(first_request)
    second_request[changed_field] = changed_value

    first = await service.dispatch_user_message(**first_request)  # type: ignore[arg-type]
    second = await service.dispatch_user_message(**second_request)  # type: ignore[arg-type]

    assert first.error_code == service.RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED
    assert second.success is False
    assert second.error_code == service.CHAT_TURN_CONFLICT


@pytest.mark.asyncio
async def test_runtime_stage_retry_restores_canonical_scheduling_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StrictQueue(_FakeRuntimeCommandQueue):
        async def enqueue_user_message(self, command) -> int:
            for index, existing in enumerate(self.commands, start=1):
                if existing.correlation_id != command.correlation_id:
                    continue
                if existing.to_payload() != command.to_payload():
                    raise ValueError("same correlation received a different payload")
                return index
            return await super().enqueue_user_message(command)

    class _FailRuntimeStageOnceStore(_FakeChatStore):
        def __init__(self) -> None:
            super().__init__()
            self.runtime_stage_attempts = 0

        async def mark_user_turn_delivery_queued(
            self,
            *,
            turn_id: str,
            delivery_attempt_no: int,
            command_id: int,
            updated_at_ms: int,
        ) -> bool:
            self.runtime_stage_attempts += 1
            if self.runtime_stage_attempts == 1:
                raise RuntimeError("temporary runtime-stage failure")
            return await super().mark_user_turn_delivery_queued(
                turn_id=turn_id,
                delivery_attempt_no=delivery_attempt_no,
                command_id=command_id,
                updated_at_ms=updated_at_ms,
            )

    queue = _StrictQueue()
    store = _FailRuntimeStageOnceStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)

    base_request = {
        "source": "api",
        "user_id": "u1",
        "message": "same text",
        "session_id": "session-scheduling-retry",
        "client_turn_id": "turn-scheduling-retry",
    }
    first = await service.dispatch_user_message(
        **base_request,
        metadata={
            "l2_batch_owner": "bootstrap:old",
            "l2_batch_max_wait_seconds": 1.0,
        },
    )
    second = await service.dispatch_user_message(
        **base_request,
        metadata={
            "l2_batch_owner": "bootstrap:new",
            "l2_batch_max_wait_seconds": 2.0,
        },
    )

    assert first.error_code == service.CHAT_STORE_PERSIST_FAILED
    assert second.success is True
    assert store.runtime_stage_attempts == 2
    assert len(queue.commands) == 1
    assert queue.commands[0].metadata["l2_batch_owner"] == "bootstrap:old"
    assert queue.commands[0].metadata["l2_batch_max_wait_seconds"] == 1.0


@pytest.mark.asyncio
async def test_concurrent_different_envelopes_choose_one_turn_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    store = _FakeChatStore()
    projector = _FakeChatProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: projector)

    base_request = {
        "source": "api",
        "user_id": "u1",
        "message": "same text",
        "session_id": "session-concurrent-conflict",
        "client_turn_id": "turn-concurrent-conflict",
    }
    outcomes = await asyncio.gather(
        service.dispatch_user_message(**base_request, metadata={"variant": "a"}),
        service.dispatch_user_message(**base_request, metadata={"variant": "b"}),
    )

    successful = [outcome for outcome in outcomes if outcome.success]
    conflicts = [
        outcome for outcome in outcomes if outcome.error_code == service.CHAT_TURN_CONFLICT
    ]
    assert len(successful) == 1
    assert len(conflicts) == 1
    assert len(store.created_turns) == 1
    assert len(projector.user_messages) == 1
    assert len(queue.commands) == 1
    winner_metadata = store.runtime_envelope_by_id["turn-concurrent-conflict"]["metadata"]
    assert queue.commands[0].metadata == winner_metadata


@pytest.mark.asyncio
async def test_concurrent_same_first_context_turn_records_one_bootstrap_start(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
    _default_chat_projector,
) -> None:
    from magi.chat.store import ChatStore
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue
    from magi.personality.growth_memory import GrowthMemoryEngine, MilestoneType

    queue = SQLiteRuntimeCommandQueue(db_path=str(runtime_paths_with_schema.message_queue_db_path))
    await queue.start()
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    growth = GrowthMemoryEngine(str(runtime_paths_with_schema.growth_db_path))
    notifier = _FakeChatMessageNotifier()

    async def _active_persona_id() -> str:
        return "persona-active"

    async def _growth_engine():
        return growth

    async def _projection_confirmed(*, message_id: str) -> bool:
        _ = message_id
        return True

    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: chat_store)
    monkeypatch.setattr(service, "get_chat_message_notifier", lambda: notifier)
    monkeypatch.setattr(
        service,
        "wait_for_first_context_memory_projection",
        _projection_confirmed,
    )
    monkeypatch.setattr(service, "_resolve_active_persona_id", _active_persona_id)
    monkeypatch.setattr(
        "magi.personality.active_persona.get_current_personality",
        lambda: "test-persona",
    )
    monkeypatch.setattr(
        "magi.personality.bootstrap_service.get_shared_growth_engine",
        _growth_engine,
    )

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "最近开始每天晚饭后散步。",
        "session_id": "session-concurrent-first-context",
        "client_turn_id": "turn-concurrent-first-context",
        "interaction_kind": "first_context_story",
        "first_context": {
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    }

    try:
        outcomes = await asyncio.gather(
            service.dispatch_user_message(**request),
            service.dispatch_user_message(**request),
        )

        assert all(outcome.success for outcome in outcomes)
        assert outcomes[0].message_id == outcomes[1].message_id
        milestones = await growth.get_milestones(
            milestone_type=MilestoneType.BOOTSTRAP_STARTED,
        )
        assert len(milestones) == 1
        assert milestones[0].metadata["message_id"] == outcomes[0].message_id
        stats = await queue.get_stats()
        assert stats["pending_count"] == 1
        assert len(_default_chat_projector.user_messages) == 1
        with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as db:
            assert db.execute(
                """
                SELECT COUNT(*)
                FROM chat_messages
                WHERE turn_id = ? AND role = 'user'
                """,
                (request["client_turn_id"],),
            ).fetchone() == (1,)
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_projection_failure_is_retried_before_runtime_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    from magi.chat.store import ChatStore

    class _FailOnceProjector(_FakeChatProjector):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def project_user_message(self, **kwargs):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary projection failure")
            await super().project_user_message(**kwargs)

    queue = _FakeRuntimeCommandQueue()
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    projector = _FailOnceProjector()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: projector)

    async def _skip_bootstrap_mark(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    async def _projection_confirmed(*, message_id: str) -> bool:
        _ = message_id
        return True

    monkeypatch.setattr(service, "_mark_first_context_bootstrap_started", _skip_bootstrap_mark)
    monkeypatch.setattr(
        service,
        "wait_for_first_context_memory_projection",
        _projection_confirmed,
    )

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "还行",
        "session_id": "session-projection-retry",
        "client_turn_id": "turn-projection-retry",
        "interaction_kind": "first_context_story",
        "first_context": {
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    }
    first = await service.dispatch_user_message(**request)
    second = await service.dispatch_user_message(**request)
    third = await service.dispatch_user_message(**request)

    assert first.error_code == service.CHAT_PROJECTION_FAILED
    assert second.success is True
    assert third.success is True
    assert projector.attempts == 2
    assert len(projector.user_messages) == 1
    assert len(queue.commands) == 1


@pytest.mark.asyncio
async def test_ordinary_chat_remains_available_without_chat_projector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    store = _FakeChatStore()
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(
        service,
        "get_chat_projector",
        lambda: (_ for _ in ()).throw(RuntimeError("projector disabled")),
    )

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="session-no-projector",
        client_turn_id="turn-no-projector",
    )

    assert outcome.success is True
    assert len(queue.commands) == 1
    assert store.delivery_by_id["turn-no-projector"] == {
        "projection_completed": True,
        "delivery_attempt_no": 0,
        "delivery_state": "queued",
        "current_command_id": 1,
    }


@pytest.mark.asyncio
async def test_republished_projection_keeps_one_l1_event_when_stage_mark_retries(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    from magi.chat.projector import ChatProjector
    from magi.chat.store import ChatStore
    from magi.memory.event_translation import translate
    from magi.memory.l1.event_store import L1EventStore

    class _CollectingBus:
        def __init__(self) -> None:
            self.events: list[object] = []

        async def publish(self, event) -> bool:  # type: ignore[no-untyped-def]
            self.events.append(event)
            return True

    queue = _FakeRuntimeCommandQueue()
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    bus = _CollectingBus()
    projector = ChatProjector(event_bus=bus)
    original_mark = store.mark_user_turn_projection_completed
    mark_attempts = 0

    async def _fail_mark_once(*, turn_id: str, updated_at_ms: int) -> None:
        nonlocal mark_attempts
        mark_attempts += 1
        if mark_attempts == 1:
            raise RuntimeError("temporary delivery-state failure")
        await original_mark(turn_id=turn_id, updated_at_ms=updated_at_ms)

    monkeypatch.setattr(store, "mark_user_turn_projection_completed", _fail_mark_once)
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: projector)

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "I like jazz.",
        "session_id": "session-stage-retry",
        "client_turn_id": "turn-stage-retry",
    }
    first = await service.dispatch_user_message(**request)
    second = await service.dispatch_user_message(**request)
    third = await service.dispatch_user_message(**request)

    assert first.error_code == service.CHAT_STORE_PERSIST_FAILED
    assert second.success is True
    assert third.success is True
    assert len(bus.events) == 2
    idempotency_keys = {
        event.data.metadata["idempotency_key"]  # type: ignore[union-attr]
        for event in bus.events
    }
    assert len(idempotency_keys) == 1

    l1 = L1EventStore(
        db_path=str(runtime_paths_with_schema.l1_memory_db_path),
        vector_enabled=False,
    )
    await l1.initialize()
    translated = [translate(event) for event in bus.events]
    assert all(item is not None for item in translated)
    stored_ids = [await l1.store(item) for item in translated if item is not None]
    assert stored_ids == [stored_ids[0], stored_ids[0]]
    with sqlite3.connect(runtime_paths_with_schema.l1_memory_db_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM fact_events WHERE idempotency_key = ?",
            (next(iter(idempotency_keys)),),
        ).fetchone() == (1,)


class _ProjectionConfirmationL1:
    def __init__(self, *, event_id: str | None, memory_event: object | None) -> None:
        self.event_id = event_id
        self.memory_event = memory_event

    async def find_event_id_by_idempotency(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return self.event_id

    async def get_memory_event(self, event_id: str):  # type: ignore[no-untyped-def]
        _ = event_id
        return self.memory_event


class _ProjectionConfirmationL2:
    def __init__(self, results: list[bool]) -> None:
        self.results = list(results)
        self.calls = 0

    async def has_projection_job(self, *, event_id: str) -> bool:
        _ = event_id
        self.calls += 1
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


@pytest.mark.asyncio
async def test_first_context_projection_confirms_l1_for_policy_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    l1 = _ProjectionConfirmationL1(event_id="event-1", memory_event=object())
    l2 = _ProjectionConfirmationL2([False])
    memory = SimpleNamespace(l1=l1, l2=l2)
    monkeypatch.setattr(projection_confirmation, "_resolve_projection_memory", lambda: memory)
    monkeypatch.setattr(
        projection_confirmation,
        "_event_requires_l2_projection",
        lambda event: False,
    )
    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: True)

    assert await projection_confirmation.wait_for_first_context_memory_projection(
        message_id="message-1"
    ) is True
    assert l2.calls == 0


@pytest.mark.asyncio
async def test_first_context_projection_waits_for_durable_l2_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    l1 = _ProjectionConfirmationL1(event_id="event-1", memory_event=object())
    l2 = _ProjectionConfirmationL2([False, True])
    memory = SimpleNamespace(l1=l1, l2=l2)
    monkeypatch.setattr(projection_confirmation, "_resolve_projection_memory", lambda: memory)
    monkeypatch.setattr(
        projection_confirmation,
        "_event_requires_l2_projection",
        lambda event: True,
    )
    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: True)
    monkeypatch.setattr(
        projection_confirmation,
        "_FIRST_CONTEXT_PROJECTION_CONFIRM_INTERVAL_SECONDS",
        0,
    )

    assert await projection_confirmation.wait_for_first_context_memory_projection(
        message_id="message-1"
    ) is True
    assert l2.calls == 2


@pytest.mark.asyncio
async def test_first_context_projection_does_not_accept_l1_only_for_self_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    l1 = _ProjectionConfirmationL1(event_id="event-1", memory_event=object())
    l2 = _ProjectionConfirmationL2([False])
    memory = SimpleNamespace(l1=l1, l2=l2)
    monkeypatch.setattr(projection_confirmation, "_resolve_projection_memory", lambda: memory)
    monkeypatch.setattr(
        projection_confirmation,
        "_event_requires_l2_projection",
        lambda event: True,
    )
    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: True)
    monkeypatch.setattr(
        projection_confirmation,
        "_FIRST_CONTEXT_PROJECTION_CONFIRM_TIMEOUT_SECONDS",
        0,
    )

    assert await projection_confirmation.wait_for_first_context_memory_projection(
        message_id="message-1"
    ) is False

    l2.results = [True]
    assert await projection_confirmation.wait_for_first_context_memory_projection(
        message_id="message-1"
    ) is True


@pytest.mark.asyncio
async def test_first_context_projection_only_skips_explicitly_disabled_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        projection_confirmation,
        "_resolve_projection_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("memory unavailable")),
    )
    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: False)
    assert await projection_confirmation.wait_for_first_context_memory_projection(
        message_id="message-1"
    ) is True

    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: True)
    assert await projection_confirmation.wait_for_first_context_memory_projection(
        message_id="message-1"
    ) is False

    l1 = _ProjectionConfirmationL1(event_id="event-1", memory_event=object())
    monkeypatch.setattr(
        projection_confirmation,
        "_resolve_projection_memory",
        lambda: SimpleNamespace(l1=l1, l2=None),
    )
    monkeypatch.setattr(
        projection_confirmation,
        "_event_requires_l2_projection",
        lambda event: True,
    )
    monkeypatch.setattr(
        projection_confirmation,
        "_memory_layer_enabled",
        lambda layer: False if layer == "l2" else True,
    )
    assert await projection_confirmation.wait_for_first_context_memory_projection(
        message_id="message-1"
    ) is True


@pytest.mark.asyncio
async def test_first_context_projection_policy_error_stays_retriable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    store = _FakeChatStore()
    l1 = _ProjectionConfirmationL1(event_id="event-1", memory_event=object())
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(
        projection_confirmation,
        "_resolve_projection_memory",
        lambda: SimpleNamespace(l1=l1, l2=_ProjectionConfirmationL2([True])),
    )
    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: True)
    monkeypatch.setattr(
        projection_confirmation,
        "_event_requires_l2_projection",
        lambda event: (_ for _ in ()).throw(RuntimeError("classification failed")),
    )

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="I like jazz.",
        session_id="session-policy-error",
        client_turn_id="turn-policy-error",
        interaction_kind="first_context_story",
        first_context={
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    )

    assert outcome.success is False
    assert outcome.error_code == service.CHAT_PROJECTION_FAILED
    assert store.delivery_by_id["turn-policy-error"]["projection_completed"] is False
    assert queue.commands == []


@pytest.mark.asyncio
async def test_first_context_async_publish_without_durable_l1_stays_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _FakeRuntimeCommandQueue()
    store = _FakeChatStore()
    l1 = _ProjectionConfirmationL1(event_id=None, memory_event=None)
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(
        projection_confirmation,
        "_resolve_projection_memory",
        lambda: SimpleNamespace(l1=l1, l2=_ProjectionConfirmationL2([False])),
    )
    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: True)
    monkeypatch.setattr(
        projection_confirmation,
        "_FIRST_CONTEXT_PROJECTION_CONFIRM_TIMEOUT_SECONDS",
        0,
    )

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="I like jazz.",
        session_id="session-async-publish",
        client_turn_id="turn-async-publish",
        interaction_kind="first_context_story",
        first_context={
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    )

    assert outcome.success is False
    assert outcome.error_code == service.CHAT_PROJECTION_FAILED
    assert store.delivery_by_id["turn-async-publish"]["projection_completed"] is False
    assert queue.commands == []


@pytest.mark.asyncio
async def test_first_context_republish_converges_to_one_l1_event_and_l2_job(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    from magi.chat.projector import ChatProjector
    from magi.chat.store import ChatStore
    from magi.events.in_memory_backend import InMemoryMessageBusBackend
    from magi.memory.subscribers.memory_ingestion_subscriber import (
        MemoryIngestionSubscriber,
    )
    from magi.memory.unified_store import UnifiedMemoryStore

    memory = UnifiedMemoryStore(
        l1_db_path=str(runtime_paths_with_schema.l1_memory_db_path),
        memory_db_path=str(runtime_paths_with_schema.memory_db_path),
        persist_dir=str(runtime_paths_with_schema.memory_dir),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=60,
        scenario_llm_pool=None,
    )
    bus = InMemoryMessageBusBackend()
    subscriber = MemoryIngestionSubscriber(event_bus=bus, unified_memory=memory)
    await memory.initialize()
    bus.bind_memory_operation_epoch(memory.memory_operation_epoch)
    await bus.start()
    await subscriber.start()

    queue = _FakeRuntimeCommandQueue()
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    projector = ChatProjector(event_bus=bus)
    original_mark = store.mark_user_turn_projection_completed
    mark_attempts = 0

    async def _fail_mark_once(*, turn_id: str, updated_at_ms: int) -> None:
        nonlocal mark_attempts
        mark_attempts += 1
        if mark_attempts == 1:
            raise RuntimeError("temporary delivery-state failure")
        await original_mark(turn_id=turn_id, updated_at_ms=updated_at_ms)

    async def _skip_bootstrap_mark(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(store, "mark_user_turn_projection_completed", _fail_mark_once)
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: queue)
    monkeypatch.setattr(service, "get_chat_store", lambda: store)
    monkeypatch.setattr(service, "get_chat_projector", lambda: projector)
    monkeypatch.setattr(projection_confirmation, "_resolve_projection_memory", lambda: memory)
    monkeypatch.setattr(projection_confirmation, "_memory_layer_enabled", lambda layer: True)
    monkeypatch.setattr(service, "_mark_first_context_bootstrap_started", _skip_bootstrap_mark)

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "I love jazz and listen to it every evening.",
        "session_id": "session-durable-memory-retry",
        "client_turn_id": "turn-durable-memory-retry",
        "interaction_kind": "first_context_story",
        "first_context": {
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    }

    try:
        first = await service.dispatch_user_message(**request)
        second = await service.dispatch_user_message(**request)
        assert first.error_code == service.CHAT_STORE_PERSIST_FAILED
        assert second.success is True
        assert first.message_id == second.message_id

        for _ in range(100):
            stats = await bus.get_stats()
            if stats["queue_length"] == 0 and stats["active_dispatches"] == 0:
                break
            await asyncio.sleep(0.01)
        await subscriber.drain()

        with sqlite3.connect(runtime_paths_with_schema.l1_memory_db_path) as db:
            l1_rows = db.execute(
                """
                SELECT event_id
                FROM fact_events
                WHERE source = 'chat'
                  AND event_type = ?
                  AND idempotency_key = ?
                """,
                ("UserMessage", second.message_id),
            ).fetchall()
        assert len(l1_rows) == 1
        with sqlite3.connect(runtime_paths_with_schema.memory_db_path) as db:
            assert db.execute(
                """
                SELECT COUNT(*)
                FROM l2_projection_jobs
                WHERE event_id = ?
                """,
                (l1_rows[0][0],),
            ).fetchone() == (1,)
    finally:
        await subscriber.stop()
        await bus.stop()
        await memory.shutdown()
