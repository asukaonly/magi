from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from magi.chat.forgetting import ChatForgettingService
from magi.chat.runtime_forgetting import ChatRuntimeForgettingCoordinator
from magi.chat.session_mutations import chat_session_mutation
from magi.memory.forgetting import ForgetOutcome


@dataclass(frozen=True)
class _MessageIdentity:
    message_id: str
    role: str
    turn_id: str | None


class _FakeReadService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.session_exists = True
        self.turn_ids = ["turn-1", "turn-2"]
        self.message_identity: _MessageIdentity | None = _MessageIdentity(
            "message-1",
            "assistant",
            "turn-1",
        )
        self.forget_message_result = True

    async def aget_session_summary(self, user_id: str, session_id: str):
        self.calls.append(f"read-session:{user_id}:{session_id}")
        return object() if self.session_exists else None

    async def alist_session_turn_ids(self, user_id: str, session_id: str) -> list[str]:
        self.calls.append(f"read-turns:{user_id}:{session_id}")
        return list(self.turn_ids)

    async def aget_message_source_identity(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> _MessageIdentity | None:
        self.calls.append(f"read-message:{user_id}:{session_id}:{message_id}")
        return self.message_identity

    async def alist_session_message_source_identities(
        self,
        user_id: str,
        session_id: str,
    ) -> list[_MessageIdentity]:
        self.calls.append(f"read-messages:{user_id}:{session_id}")
        return [
            _MessageIdentity("message-user", "user", "turn-1"),
            _MessageIdentity("message-assistant", "assistant", "turn-1"),
        ]

    async def aclear_conversation_history_snapshot(
        self,
        user_id: str,
        session_id: str,
        message_ids: list[str],
        turn_ids: list[str],
    ) -> None:
        assert message_ids == ["message-user", "message-assistant"]
        assert turn_ids == ["turn-1", "turn-2"]
        self.calls.append(f"clear-chat:{user_id}:{session_id}")

    async def adelete_session(self, user_id: str, session_id: str) -> None:
        self.calls.append(f"delete-chat:{user_id}:{session_id}")

    async def aforget_message_artifacts(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        self.calls.append(f"forget-chat-message:{user_id}:{session_id}:{message_id}")
        return self.forget_message_result


class _FakeSurfaceWriteService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.hide_result = True

    async def hide_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        self.calls.append(f"hide-message:{user_id}:{session_id}:{message_id}")
        return self.hide_result


class _FakeMemory:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.failure: RuntimeError | None = None
        self.completed_session_user: str | None = None

    async def forget_chat_session_sources(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        reason: str,
    ) -> ForgetOutcome:
        self.calls.append(f"forget-session:{user_id}:{session_id}:{','.join(turn_ids)}:{reason}")
        if self.failure is not None:
            raise self.failure
        return ForgetOutcome("forget-session", "chat_session", 2, {})

    async def forget_chat_message_source(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        source: str,
        event_type: str,
        reason: str,
    ) -> ForgetOutcome:
        self.calls.append(
            f"forget-message:{user_id}:{session_id}:{message_id}:{source}:{event_type}:{reason}"
        )
        if self.failure is not None:
            raise self.failure
        return ForgetOutcome("forget-message", "chat_message", 1, {})

    async def was_chat_session_forgotten(self, *, user_id: str, session_id: str) -> bool:
        self.calls.append(f"was-session-forgotten:{user_id}:{session_id}")
        return self.completed_session_user == user_id

    async def forget_chat_history_sources(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        messages: list[dict[str, str]],
        surface_message_ids: list[str],
        reason: str,
    ) -> ForgetOutcome:
        self.calls.append(
            f"forget-history:{user_id}:{session_id}:{','.join(turn_ids)}:"
            f"{','.join(item['message_id'] for item in messages)}:{reason}"
        )
        if self.failure is not None:
            raise self.failure
        assert surface_message_ids == ["message-user", "message-assistant"]
        return ForgetOutcome("forget-history", "chat_history", 2, {})

    async def list_pending_chat_surface_finalizations(self):
        return []

    async def mark_chat_surface_finalized(self, operation_id: str) -> None:
        self.calls.append(f"finalize-surface:{operation_id}")


class _FakeRuntime:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.failure: RuntimeError | None = None

    async def prepare_session_delete(self, *, user_id: str, session_id: str) -> object:
        self.calls.append(f"block-session:{user_id}:{session_id}")
        if self.failure is not None:
            raise self.failure
        return object()

    async def prepare_message_delete(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
    ) -> object:
        self.calls.append(f"block-message:{user_id}:{session_id}:{turn_id}:{message_id}")
        if self.failure is not None:
            raise self.failure
        return object()

    async def quiesce_history_clear(self, *, user_id: str, session_id: str) -> object:
        self.calls.append(f"quiesce-history:{user_id}:{session_id}")
        if self.failure is not None:
            raise self.failure
        return object()

    async def prepare_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        messages: list[_MessageIdentity],
    ) -> object:
        self.calls.append(
            f"block-history:{user_id}:{session_id}:{','.join(turn_ids)}:"
            f"{','.join(item.message_id for item in messages)}"
        )
        if self.failure is not None:
            raise self.failure
        return object()


def _service(calls: list[str]):
    read = _FakeReadService(calls)
    surface = _FakeSurfaceWriteService(calls)
    memory = _FakeMemory(calls)
    runtime = _FakeRuntime(calls)
    return (
        ChatForgettingService(
            chat_read_service=read,
            chat_surface_write_service=surface,
            memory=memory,
            runtime=runtime,
        ),
        read,
        surface,
        memory,
        runtime,
    )


@pytest.mark.asyncio
async def test_session_memory_is_governed_before_chat_rows_are_removed() -> None:
    calls: list[str] = []
    service, _, _, _, _ = _service(calls)

    await service.delete_session(user_id="u1", session_id="session-1")

    assert calls == [
        "read-session:u1:session-1",
        "read-turns:u1:session-1",
        "block-session:u1:session-1",
        "forget-session:u1:session-1:turn-1,turn-2:user_delete_chat_session",
        "delete-chat:u1:session-1",
        "finalize-surface:forget-session",
    ]


@pytest.mark.asyncio
async def test_session_memory_failure_keeps_chat_truth_for_retry() -> None:
    calls: list[str] = []
    service, _, _, memory, _ = _service(calls)
    memory.failure = RuntimeError("memory cleanup failed")

    with pytest.raises(RuntimeError, match="memory cleanup failed"):
        await service.delete_session(user_id="u1", session_id="session-1")

    assert calls == [
        "read-session:u1:session-1",
        "read-turns:u1:session-1",
        "block-session:u1:session-1",
        "forget-session:u1:session-1:turn-1,turn-2:user_delete_chat_session",
    ]


@pytest.mark.asyncio
async def test_runtime_barrier_failure_keeps_memory_and_chat_truth_untouched() -> None:
    calls: list[str] = []
    service, _, _, _, runtime = _service(calls)
    runtime.failure = RuntimeError("runtime barrier failed")

    with pytest.raises(RuntimeError, match="runtime barrier failed"):
        await service.delete_session(user_id="u1", session_id="session-1")

    assert calls == [
        "read-session:u1:session-1",
        "read-turns:u1:session-1",
        "block-session:u1:session-1",
    ]


@pytest.mark.asyncio
async def test_exact_message_is_governed_before_the_message_is_hidden() -> None:
    calls: list[str] = []
    service, _, _, _, _ = _service(calls)

    assert (
        await service.delete_message(
            user_id="u1",
            session_id="session-1",
            message_id="message-1",
        )
        is True
    )

    assert calls == [
        "read-message:u1:session-1:message-1",
        "block-message:u1:session-1:turn-1:message-1",
        "forget-message:u1:session-1:message-1:chat:AIResponse:user_delete_chat_message",
        "forget-chat-message:u1:session-1:message-1",
        "hide-message:u1:session-1:message-1",
        "finalize-surface:forget-message",
    ]


@pytest.mark.asyncio
async def test_message_memory_failure_does_not_hide_the_message() -> None:
    calls: list[str] = []
    service, _, _, memory, _ = _service(calls)
    memory.failure = RuntimeError("memory cleanup failed")

    with pytest.raises(RuntimeError, match="memory cleanup failed"):
        await service.delete_message(
            user_id="u1",
            session_id="session-1",
            message_id="message-1",
        )

    assert calls == [
        "read-message:u1:session-1:message-1",
        "block-message:u1:session-1:turn-1:message-1",
        "forget-message:u1:session-1:message-1:chat:AIResponse:user_delete_chat_message",
    ]


@pytest.mark.asyncio
async def test_message_delete_is_idempotent_after_the_row_was_already_hidden() -> None:
    calls: list[str] = []
    service, _, surface, _, _ = _service(calls)
    surface.hide_result = False

    assert (
        await service.delete_message(
            user_id="u1",
            session_id="session-1",
            message_id="message-1",
        )
        is True
    )


@pytest.mark.asyncio
async def test_missing_chat_artifact_is_treated_as_an_idempotent_delete() -> None:
    calls: list[str] = []
    service, read, _, _, _ = _service(calls)
    read.forget_message_result = False

    assert (
        await service.delete_message(
            user_id="u1",
            session_id="session-1",
            message_id="message-1",
        )
        is True
    )
    assert calls[-2:] == [
        "hide-message:u1:session-1:message-1",
        "finalize-surface:forget-message",
    ]


@pytest.mark.asyncio
async def test_unknown_message_does_not_create_a_memory_barrier() -> None:
    calls: list[str] = []
    service, read, _, _, _ = _service(calls)
    read.message_identity = None

    assert (
        await service.delete_message(
            user_id="u1",
            session_id="session-1",
            message_id="missing",
        )
        is False
    )
    assert calls == ["read-message:u1:session-1:missing"]


@pytest.mark.asyncio
async def test_unknown_session_does_not_create_a_memory_barrier() -> None:
    calls: list[str] = []
    service, read, _, memory, _ = _service(calls)
    read.session_exists = False

    assert await service.delete_session(user_id="u1", session_id="missing") is False
    assert calls == [
        "read-session:u1:missing",
        "was-session-forgotten:u1:missing",
    ]

    memory.completed_session_user = "u1"
    assert await service.delete_session(user_id="u1", session_id="missing") is True
    assert await service.delete_session(user_id="u2", session_id="missing") is False


@pytest.mark.asyncio
async def test_history_clear_quiesces_then_snapshots_and_forgets_before_chat_clear() -> None:
    calls: list[str] = []
    service, _, _, _, _ = _service(calls)

    assert await service.clear_history(user_id="u1", session_id="session-1") is True

    assert calls == [
        "read-session:u1:session-1",
        "quiesce-history:u1:session-1",
        "read-turns:u1:session-1",
        "read-messages:u1:session-1",
        "block-history:u1:session-1:turn-1,turn-2:message-user,message-assistant",
        "forget-history:u1:session-1:turn-1,turn-2:message-user,message-assistant:user_clear_chat_history",
        "clear-chat:u1:session-1",
        "finalize-surface:forget-history",
    ]


@pytest.mark.asyncio
async def test_history_memory_failure_keeps_transcript_and_releases_waiting_ingress() -> None:
    calls: list[str] = []
    service, _, _, memory, _ = _service(calls)
    started = __import__("asyncio").Event()
    release = __import__("asyncio").Event()
    original = memory.forget_chat_history_sources

    async def fail_after_pause(**kwargs):  # type: ignore[no-untyped-def]
        started.set()
        await release.wait()
        await original(**kwargs)
        raise RuntimeError("history cleanup failed")

    memory.forget_chat_history_sources = fail_after_pause  # type: ignore[method-assign]
    clear_task = __import__("asyncio").create_task(
        service.clear_history(user_id="u1", session_id="session-1")
    )
    await started.wait()

    ingress_entered = __import__("asyncio").Event()

    async def competing_ingress() -> None:
        async with chat_session_mutation("session-1"):
            calls.append("new-ingress")
            ingress_entered.set()

    ingress_task = __import__("asyncio").create_task(competing_ingress())
    await __import__("asyncio").sleep(0)
    assert not ingress_entered.is_set()

    release.set()
    with pytest.raises(RuntimeError, match="history cleanup failed"):
        await clear_task
    await ingress_task

    assert "clear-chat:u1:session-1" not in calls
    assert calls[-1] == "new-ingress"


@pytest.mark.asyncio
async def test_runtime_coordinator_persists_barrier_before_cancel_and_sensor_purge() -> None:
    calls: list[str] = []

    class _Queue:
        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            calls.append("queue-boundary-enter")
            yield
            calls.append("queue-boundary-exit")

        async def block_user_message_scope_and_purge(self, **scope) -> int:  # type: ignore[no-untyped-def]
            calls.append(f"queue-block:{scope['turn_id']}:{scope['message_id']}")
            return 2

    class _Manager:
        async def cancel_chat_session_work(self, **scope) -> bool:  # type: ignore[no-untyped-def]
            calls.append(f"cancel:{scope['session_id']}:{scope['turn_id']}")
            return True

    class _Hub:
        async def discard_user_message_scope(self, **scope) -> int:  # type: ignore[no-untyped-def]
            calls.append(f"sensor-purge:{scope['session_id']}:{scope['turn_id']}")
            return 1

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=_Manager(),
        sensor_hub=_Hub(),
    )

    result = await coordinator.prepare_message_delete(
        user_id="u1",
        session_id="session-1",
        turn_id="turn-1",
        message_id="message-1",
    )

    assert calls == [
        "queue-boundary-enter",
        "queue-block:turn-1:message-1",
        "queue-boundary-exit",
        "cancel:session-1:turn-1",
        "sensor-purge:session-1:turn-1",
    ]
    assert result.purged_commands == 2
    assert result.purged_sensor_events == 1
    assert result.cancelled_agent is True
