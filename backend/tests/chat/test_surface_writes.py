from __future__ import annotations

import json

import pytest

from magi.chat.surface_writes import ChatSurfaceWriteService
from magi.chat import surface_writes as surface_writes_module


class _FakeChatStore:
    def __init__(self) -> None:
        self.messages: dict[str, object] = {}
        self.appended: list[object] = []
        self.bumped_sessions: list[str] = []

    async def append_message(self, record, **kwargs):  # type: ignore[no-untyped-def]
        self.messages[record.message_id] = record
        self.appended.append(record)

    async def next_sequence_no(self, *, session_id: str) -> int:
        return len(self.appended) + 1

    async def bump_history_version(self, session_id: str) -> None:
        self.bumped_sessions.append(session_id)

    async def get_message(self, message_id: str):
        return self.messages.get(message_id)


class _FakeNotifier:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, str, str]] = []
        self.hidden: list[tuple[str, str, str]] = []

    async def broadcast_chat_message_upsert(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        self.upserts.append((user_id, session_id, message_id))

    async def broadcast_chat_message_hidden(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        self.hidden.append((user_id, session_id, message_id))


@pytest.fixture
def chat_surface(monkeypatch: pytest.MonkeyPatch):
    store = _FakeChatStore()
    notifier = _FakeNotifier()
    monkeypatch.setattr(surface_writes_module, "get_chat_store", lambda: store)
    monkeypatch.setattr(surface_writes_module, "get_chat_message_notifier", lambda: notifier)
    return ChatSurfaceWriteService(), store, notifier


@pytest.mark.asyncio
async def test_command_failure_result_does_not_emit_missing_invocation_id(chat_surface) -> None:
    service, store, notifier = chat_surface

    message_id = await service.append_command_result(
        user_id="u1",
        session_id="s1",
        turn_id="cmd-1",
        invocation_message_id="",
        tool_name="ghost",
        arguments={},
        output_text="Tool not found",
        success=False,
        error="Tool not found",
        error_code="tool_not_found",
        execution_time_ms=0,
        invocation_text="/ghost",
    )

    record = store.messages[message_id]
    payload = json.loads(record.payload_json)["command_result"]
    assert payload["invocation_text"] == "/ghost"
    assert "invocation_message_id" not in payload
    assert record.sequence_no == 1
    assert notifier.upserts == [("u1", "s1", message_id)]


@pytest.mark.asyncio
async def test_background_pending_message_attach_updates_payload(chat_surface) -> None:
    service, store, notifier = chat_surface

    message_id = await service.create_background_task_pending_message(
        user_id="u1",
        session_id="s1",
        title="/deep-scan",
        trigger_source="manual",
        skill_name="deep-scan",
        invocation_text="/deep-scan",
    )
    await service.attach_background_task_id(
        user_id="u1",
        session_id="s1",
        message_id=message_id,
        task_id="task-1",
    )

    record = store.messages[message_id]
    payload = json.loads(record.payload_json)
    assert record.message_kind == "background_task_pending"
    assert record.content_text == "[Background task] /deep-scan\n(running…)"
    assert payload["background_task_id"] == "task-1"
    assert store.bumped_sessions == ["s1"]
    assert notifier.upserts == [("u1", "s1", message_id), ("u1", "s1", message_id)]
