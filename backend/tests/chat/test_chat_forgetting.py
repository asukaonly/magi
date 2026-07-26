from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from magi.chat.forgetting import (
    ChatForgettingRecoveryService,
    ChatForgettingService,
    ChatHistoryClearResult,
)
from magi.chat.runtime_forgetting import ChatRuntimeForgettingCoordinator
from magi.chat.session_mutations import chat_session_mutation
from magi.memory.forgetting import ForgetOutcome, ForgetSelector


@dataclass(frozen=True)
class _MessageIdentity:
    message_id: str
    role: str
    turn_id: str | None
    run_id: str | None = "run-1"
    run_revision: int = 0
    source_message_id: str | None = None
    background_task_id: str | None = None


@dataclass(frozen=True)
class _PreparedIntent:
    operation_id: str
    selector: ForgetSelector


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
        self.message_identities = [
            _MessageIdentity("message-user", "user", "turn-1"),
            _MessageIdentity("message-assistant", "assistant", "turn-1"),
        ]
        self.replacement_identities: list[_MessageIdentity] | None = None
        self.replacement_identity_snapshots: list[list[_MessageIdentity]] = []
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
        return list(self.message_identities)

    async def alist_message_replacement_source_identities(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> list[_MessageIdentity]:
        self.calls.append(
            f"read-replacements:{user_id}:{session_id}:{message_id}"
        )
        if self.replacement_identity_snapshots:
            return list(self.replacement_identity_snapshots.pop(0))
        if self.replacement_identities is not None:
            return list(self.replacement_identities)
        return [self.message_identity] if self.message_identity is not None else []

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
        self._prepared_calls: dict[str, str] = {}
        self._prepared_outcomes: dict[str, ForgetOutcome] = {}
        self._prepared_intents: dict[str, _PreparedIntent] = {}
        self.activated_operation_ids: set[str] = set()
        self.prepared_history_messages: list[dict[str, str]] = []
        self.prepared_surface_message_ids: list[str] = []

    @asynccontextmanager
    async def chat_forget_operation_guard(self):
        yield

    async def prepare_chat_session_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        reason: str,
    ) -> _PreparedIntent:
        operation_id = "forget-session"
        self._prepared_calls[operation_id] = (
            f"forget-session:{user_id}:{session_id}:{','.join(turn_ids)}:{reason}"
        )
        self._prepared_outcomes[operation_id] = ForgetOutcome(
            operation_id,
            "chat_session",
            2,
            {},
        )
        intent = _PreparedIntent(
            operation_id,
            ForgetSelector.chat_session(
                user_id=user_id,
                session_id=session_id,
                turn_ids=turn_ids,
            ),
        )
        self._prepared_intents[operation_id] = intent
        return intent

    async def prepare_chat_message_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        source_message_id: str,
        turn_id: str,
        source: str,
        event_type: str,
        runtime_turn_ids: list[str],
        runtime_replay_turn_ids: list[str],
        messages: list[dict[str, str]],
        surface_message_ids: list[str],
        reason: str,
    ) -> _PreparedIntent:
        assert turn_id in runtime_turn_ids
        assert turn_id not in runtime_replay_turn_ids
        operation_id = "forget-message"
        self._prepared_calls[operation_id] = (
            f"forget-message:{user_id}:{session_id}:{message_id}:"
            f"{source_message_id}:{turn_id}:"
            f"{source}:{event_type}:{reason}"
        )
        self._prepared_outcomes[operation_id] = ForgetOutcome(
            operation_id,
            "chat_message",
            1,
            {},
        )
        intent = _PreparedIntent(
            operation_id,
            ForgetSelector.chat_message(
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                source_message_id=source_message_id,
                turn_id=turn_id,
                source=source,
                event_type=event_type,
                runtime_turn_ids=runtime_turn_ids,
                runtime_replay_turn_ids=runtime_replay_turn_ids,
                messages=messages,
                surface_message_ids=surface_message_ids,
            ),
        )
        self._prepared_intents[operation_id] = intent
        return intent

    async def prepare_chat_history_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        messages: list[dict[str, str]],
        surface_message_ids: list[str],
        reason: str,
    ) -> _PreparedIntent:
        operation_id = "forget-history"
        self.prepared_history_messages = [dict(item) for item in messages]
        self.prepared_surface_message_ids = list(surface_message_ids)
        self._prepared_calls[operation_id] = (
            f"forget-history:{user_id}:{session_id}:{','.join(turn_ids)}:"
            f"{','.join(item['message_id'] for item in messages)}:{reason}"
        )
        self._prepared_outcomes[operation_id] = ForgetOutcome(
            operation_id,
            "chat_history",
            2,
            {},
        )
        intent = _PreparedIntent(
            operation_id,
            ForgetSelector.chat_history(
                user_id=user_id,
                session_id=session_id,
                turn_ids=turn_ids,
                messages=messages,
                surface_message_ids=surface_message_ids,
            ),
        )
        self._prepared_intents[operation_id] = intent
        return intent

    async def activate_chat_forget_intent(self, operation_id: str) -> _PreparedIntent:
        self.activated_operation_ids.add(operation_id)
        return self._prepared_intents[operation_id]

    async def execute_prepared_forget(self, operation_id: str) -> ForgetOutcome:
        self.calls.append(self._prepared_calls[operation_id])
        if self.failure is not None:
            raise self.failure
        return self._prepared_outcomes[operation_id]

    async def list_chat_forget_intents_awaiting_runtime_barriers(self):
        return []

    async def was_chat_session_forgotten(self, *, user_id: str, session_id: str) -> bool:
        self.calls.append(f"was-session-forgotten:{user_id}:{session_id}")
        return self.completed_session_user == user_id

    async def list_pending_chat_surface_finalizations(self):
        return []

    async def mark_chat_surface_finalized(self, operation_id: str) -> None:
        self.calls.append(f"finalize-surface:{operation_id}")


class _FakeRuntime:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.failure: RuntimeError | None = None
        self.expected_background_task_ids: list[str] = []
        self.expected_related_message_ids: list[str] | None = None
        self.record_background_scope = False

    @asynccontextmanager
    async def forget_operation_boundary(self):
        yield

    @asynccontextmanager
    async def background_scope_boundary(self, **_scope):  # type: ignore[no-untyped-def]
        if self.record_background_scope:
            self.calls.append("background-scope-enter")
        try:
            yield
        finally:
            if self.record_background_scope:
                self.calls.append("background-scope-exit")

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
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str] | None = None,
        replay_turn_ids: list[str] | None = None,
        related_message_ids: list[str] | None = None,
        background_task_ids: list[str] | None = None,
    ) -> object:
        scope = "turn-and-message" if include_turn_scope else "message-only"
        self.calls.append(
            f"block-message:{user_id}:{session_id}:{turn_id}:{message_id}:{scope}:"
            f"{run_id}:{run_revision}"
        )
        if self.failure is not None:
            raise self.failure
        return object()

    @asynccontextmanager
    async def message_delete_boundary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str],
        replay_turn_ids: list[str],
        related_message_ids: list[str],
        background_task_ids: list[str],
        prepare_intent,
    ):
        assert background_task_ids == self.expected_background_task_ids
        assert related_message_ids == (
            self.expected_related_message_ids or [message_id]
        )
        await prepare_intent(runtime_turn_ids, replay_turn_ids)
        result = await self.prepare_message_delete(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            include_turn_scope=include_turn_scope,
            run_id=run_id,
            run_revision=run_revision,
            runtime_turn_ids=runtime_turn_ids,
            replay_turn_ids=replay_turn_ids,
            related_message_ids=related_message_ids,
            background_task_ids=background_task_ids,
        )
        yield result

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
        message_ids: list[str],
    ) -> object:
        self.calls.append(
            f"block-history:{user_id}:{session_id}:{','.join(turn_ids)}:"
            f"{','.join(message_ids)}"
        )
        if self.failure is not None:
            raise self.failure
        return object()


class _FakeAssistantMemoryOutbox:
    def __init__(self, calls: list[str], memory: _FakeMemory) -> None:
        self.calls = calls
        self.memory = memory

    async def cancel_assistant_memory_projections(
        self,
        *,
        canonical_message_ids: list[str] | tuple[str, ...] = (),
        session_id: str | None = None,
    ) -> int:
        assert self.memory.activated_operation_ids
        if session_id:
            self.calls.append(f"cancel-outbox-session:{session_id}")
        if canonical_message_ids:
            self.calls.append(
                "cancel-outbox-messages:" + ",".join(canonical_message_ids)
            )
        return len(canonical_message_ids) + int(bool(session_id))


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


def _service_with_outbox(calls: list[str]):
    read = _FakeReadService(calls)
    surface = _FakeSurfaceWriteService(calls)
    memory = _FakeMemory(calls)
    runtime = _FakeRuntime(calls)
    outbox = _FakeAssistantMemoryOutbox(calls, memory)
    return (
        ChatForgettingService(
            chat_read_service=read,
            chat_surface_write_service=surface,
            memory=memory,
            runtime=runtime,
            assistant_memory_outbox=outbox,
        ),
        read,
        surface,
        memory,
        runtime,
        outbox,
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
async def test_session_background_scope_is_held_through_surface_deletion() -> None:
    calls: list[str] = []
    service, _, _, _, runtime = _service(calls)
    runtime.record_background_scope = True

    assert await service.delete_session(
        user_id="u1",
        session_id="session-1",
    )

    assert calls[0] == "background-scope-enter"
    assert calls[-1] == "background-scope-exit"
    assert calls.index("delete-chat:u1:session-1") < calls.index(
        "background-scope-exit"
    )
    assert calls.index("finalize-surface:forget-session") < calls.index(
        "background-scope-exit"
    )


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
async def test_session_delete_cancels_outbox_after_forget_activation() -> None:
    calls: list[str] = []
    service, _, _, _, _, _ = _service_with_outbox(calls)

    assert await service.delete_session(user_id="u1", session_id="session-1")

    assert "cancel-outbox-session:session-1" in calls
    assert calls.index("cancel-outbox-session:session-1") < calls.index(
        "forget-session:u1:session-1:turn-1,turn-2:user_delete_chat_session"
    )


@pytest.mark.asyncio
async def test_pre_activation_failure_does_not_cancel_outbox() -> None:
    calls: list[str] = []
    service, _, _, _, runtime, _ = _service_with_outbox(calls)
    runtime.failure = RuntimeError("runtime barrier failed")

    with pytest.raises(RuntimeError, match="runtime barrier failed"):
        await service.delete_session(user_id="u1", session_id="session-1")

    assert not any(call.startswith("cancel-outbox") for call in calls)


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
        "read-replacements:u1:session-1:message-1",
        "read-replacements:u1:session-1:message-1",
        "block-message:u1:session-1:turn-1:message-1:message-only:run-1:0",
        "forget-message:u1:session-1:message-1:message-1:turn-1:"
        "chat:AIResponse:user_delete_chat_message",
        "forget-chat-message:u1:session-1:message-1",
        "hide-message:u1:session-1:message-1",
        "finalize-surface:forget-message",
    ]


@pytest.mark.asyncio
async def test_message_delete_governs_the_complete_existing_replacement_chain() -> None:
    calls: list[str] = []
    service, read, _, memory, runtime, _ = _service_with_outbox(calls)
    pending = _MessageIdentity(
        "pending-1",
        "assistant",
        "turn-1",
        background_task_id="task-1",
    )
    completion = _MessageIdentity(
        "completion-1",
        "assistant",
        "turn-1",
        background_task_id="task-1",
    )
    read.message_identity = pending
    read.replacement_identities = [pending, completion]
    runtime.expected_related_message_ids = ["pending-1", "completion-1"]
    runtime.expected_background_task_ids = ["task-1"]

    assert await service.delete_message(
        user_id="u1",
        session_id="session-1",
        message_id="pending-1",
    )

    selector = memory._prepared_intents["forget-message"].selector
    assert selector.payload["surface_message_ids"] == [
        "pending-1",
        "completion-1",
    ]
    assert {
        item["message_id"]
        for item in selector.payload["messages"]
    } == {"pending-1", "completion-1"}
    assert [
        call
        for call in calls
        if call.startswith("forget-chat-message:")
    ] == [
        "forget-chat-message:u1:session-1:completion-1",
        "forget-chat-message:u1:session-1:pending-1",
    ]
    assert [
        call
        for call in calls
        if call.startswith("hide-message:")
    ] == [
        "hide-message:u1:session-1:completion-1",
        "hide-message:u1:session-1:pending-1",
    ]


@pytest.mark.asyncio
async def test_message_delete_captures_a_replacement_written_while_quiescing() -> None:
    calls: list[str] = []
    service, read, _, memory, runtime = _service(calls)
    pending = _MessageIdentity(
        "pending-1",
        "assistant",
        "turn-1",
        background_task_id="task-1",
    )
    completion = _MessageIdentity(
        "completion-1",
        "assistant",
        "turn-1",
        background_task_id="task-1",
    )
    read.message_identity = pending
    read.replacement_identity_snapshots = [
        [pending],
        [pending, completion],
    ]
    runtime.expected_related_message_ids = ["pending-1"]
    runtime.expected_background_task_ids = ["task-1"]

    assert await service.delete_message(
        user_id="u1",
        session_id="session-1",
        message_id="pending-1",
    )

    selector = memory._prepared_intents["forget-message"].selector
    assert selector.payload["surface_message_ids"] == [
        "pending-1",
        "completion-1",
    ]
    assert "forget-chat-message:u1:session-1:completion-1" in calls
    assert "hide-message:u1:session-1:completion-1" in calls


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_message_id", ["rhythm-2", "rhythm-3"])
async def test_rhythm_segment_delete_forgets_canonical_source_only(
    selected_message_id: str,
) -> None:
    calls: list[str] = []
    service, read, _, _, _ = _service(calls)
    read.message_identity = _MessageIdentity(
        selected_message_id,
        "assistant",
        "turn-1",
        source_message_id="rhythm-1",
    )

    assert await service.delete_message(
        user_id="u1",
        session_id="session-1",
        message_id=selected_message_id,
    )

    assert calls == [
        f"read-message:u1:session-1:{selected_message_id}",
        f"read-replacements:u1:session-1:{selected_message_id}",
        f"read-replacements:u1:session-1:{selected_message_id}",
        f"block-message:u1:session-1:turn-1:{selected_message_id}:"
        "message-only:run-1:0",
        f"forget-message:u1:session-1:{selected_message_id}:rhythm-1:turn-1:"
        "chat:AIResponse:user_delete_chat_message",
        f"forget-chat-message:u1:session-1:{selected_message_id}",
        f"hide-message:u1:session-1:{selected_message_id}",
        "finalize-surface:forget-message",
    ]


@pytest.mark.asyncio
async def test_rhythm_segment_delete_cancels_canonical_outbox_identity() -> None:
    calls: list[str] = []
    service, read, _, _, _, _ = _service_with_outbox(calls)
    read.message_identity = _MessageIdentity(
        "rhythm-3",
        "assistant",
        "turn-1",
        source_message_id="rhythm-1",
    )

    assert await service.delete_message(
        user_id="u1",
        session_id="session-1",
        message_id="rhythm-3",
    )

    assert "cancel-outbox-messages:rhythm-1" in calls
    assert calls.index("cancel-outbox-messages:rhythm-1") < calls.index(
        "forget-message:u1:session-1:rhythm-3:rhythm-1:turn-1:"
        "chat:AIResponse:user_delete_chat_message"
    )


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
        "read-replacements:u1:session-1:message-1",
        "read-replacements:u1:session-1:message-1",
        "block-message:u1:session-1:turn-1:message-1:message-only:run-1:0",
        "forget-message:u1:session-1:message-1:message-1:turn-1:"
        "chat:AIResponse:user_delete_chat_message",
    ]


@pytest.mark.asyncio
async def test_user_message_delete_blocks_its_turn_scope() -> None:
    calls: list[str] = []
    service, read, _, _, _ = _service(calls)
    read.message_identity = _MessageIdentity("message-1", "user", "turn-1")

    assert await service.delete_message(
        user_id="u1",
        session_id="session-1",
        message_id="message-1",
    )

    assert calls[3] == (
        "block-message:u1:session-1:turn-1:message-1:"
        "turn-and-message:run-1:0"
    )


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

    assert await service.clear_history(
        user_id="u1",
        session_id="session-1",
    ) == ChatHistoryClearResult(
        message_ids=("message-user", "message-assistant"),
        turn_ids=("turn-1", "turn-2"),
    )

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
async def test_history_background_scope_is_held_through_surface_clear() -> None:
    calls: list[str] = []
    service, _, _, _, runtime = _service(calls)
    runtime.record_background_scope = True

    assert await service.clear_history(
        user_id="u1",
        session_id="session-1",
    )

    assert calls[0] == "background-scope-enter"
    assert calls[-1] == "background-scope-exit"
    assert calls.index("clear-chat:u1:session-1") < calls.index(
        "background-scope-exit"
    )
    assert calls.index("finalize-surface:forget-history") < calls.index(
        "background-scope-exit"
    )


@pytest.mark.asyncio
async def test_history_clear_cancels_every_canonical_outbox_identity() -> None:
    calls: list[str] = []
    service, _, _, _, _, _ = _service_with_outbox(calls)

    assert await service.clear_history(user_id="u1", session_id="session-1")

    cancellation = "cancel-outbox-messages:message-assistant,message-user"
    assert cancellation in calls
    assert calls.index(cancellation) < calls.index(
        "forget-history:u1:session-1:turn-1,turn-2:"
        "message-user,message-assistant:user_clear_chat_history"
    )


@pytest.mark.asyncio
async def test_history_clear_builds_a_linear_deduplicated_memory_snapshot() -> None:
    calls: list[str] = []
    service, read, _, memory, _ = _service(calls)
    ordinary_count = 256
    read.message_identities = [
        _MessageIdentity(
            f"message-{index}",
            "assistant",
            f"turn-{index}",
        )
        for index in range(ordinary_count)
    ] + [
        _MessageIdentity(
            f"rhythm-{index}",
            "assistant",
            "turn-rhythm",
            source_message_id="rhythm-0",
        )
        for index in range(3)
    ]
    memory.failure = RuntimeError("stop after snapshot")

    with pytest.raises(RuntimeError, match="stop after snapshot"):
        await service.clear_history(user_id="u1", session_id="session-1")

    assert len(memory.prepared_surface_message_ids) == ordinary_count + 3
    assert len(memory.prepared_history_messages) == ordinary_count + 1
    assert [
        item["message_id"] for item in memory.prepared_history_messages[-2:]
    ] == [f"message-{ordinary_count - 1}", "rhythm-0"]


@pytest.mark.asyncio
async def test_history_memory_failure_keeps_transcript_and_releases_waiting_ingress() -> None:
    calls: list[str] = []
    service, _, _, memory, _ = _service(calls)
    started = __import__("asyncio").Event()
    release = __import__("asyncio").Event()
    original = memory.execute_prepared_forget

    async def fail_after_pause(operation_id: str) -> ForgetOutcome:
        started.set()
        await release.wait()
        await original(operation_id)
        raise RuntimeError("history cleanup failed")

    memory.execute_prepared_forget = fail_after_pause  # type: ignore[method-assign]
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
async def test_recovery_activates_chat_intent_only_after_runtime_barrier() -> None:
    calls: list[str] = []
    operation = type(
        "_Operation",
        (),
        {
            "operation_id": "forget-interrupted-message",
            "selector": ForgetSelector.chat_message(
                user_id="u1",
                session_id="session-1",
                message_id="message-1",
                turn_id="turn-1",
                source="chat",
                event_type="UserMessage",
            ),
        },
    )()

    class _Memory:
        def __init__(self) -> None:
            self.active = False

        @asynccontextmanager
        async def chat_forget_operation_guard(self):  # type: ignore[no-untyped-def]
            yield

        async def list_chat_forget_intents_awaiting_runtime_barriers(self):  # type: ignore[no-untyped-def]
            return [] if self.active else [operation]

        async def activate_chat_forget_intent(self, operation_id: str):  # type: ignore[no-untyped-def]
            calls.append(f"activate:{operation_id}")
            self.active = True
            return operation

        async def execute_prepared_forget(self, operation_id: str) -> ForgetOutcome:
            calls.append(f"execute:{operation_id}")
            return ForgetOutcome(operation_id, "chat_message", 1, {})

        async def list_pending_chat_surface_finalizations(self):  # type: ignore[no-untyped-def]
            return []

    class _Runtime:
        def __init__(self) -> None:
            self.fail = True

        @asynccontextmanager
        async def forget_operation_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def prepare_message_delete(self, **scope):  # type: ignore[no-untyped-def]
            calls.append(
                f"block:{scope['session_id']}:{scope['turn_id']}:{scope['message_id']}"
            )
            if self.fail:
                raise RuntimeError("runtime barrier unavailable")
            return object()

    memory = _Memory()
    runtime = _Runtime()

    class _Outbox:
        async def cancel_assistant_memory_projections(
            self,
            *,
            canonical_message_ids=(),
            session_id=None,
        ):  # type: ignore[no-untyped-def]
            assert memory.active is True
            calls.append(
                "cancel:" + ",".join(canonical_message_ids)
            )
            return len(canonical_message_ids)

    recovery = ChatForgettingRecoveryService(
        chat_read_service=_FakeReadService(calls),
        memory=memory,
        runtime=runtime,
        assistant_memory_outbox=_Outbox(),
    )

    with pytest.raises(RuntimeError, match="runtime barrier unavailable"):
        await recovery.recover_pending()
    assert calls == ["block:session-1:turn-1:message-1"]
    assert memory.active is False

    runtime.fail = False
    assert await recovery.recover_pending() == {
        "intents_found": 1,
        "intents_activated": 1,
        "surfaces_found": 0,
        "surfaces_completed": 0,
    }
    assert calls == [
        "block:session-1:turn-1:message-1",
        "block:session-1:turn-1:message-1",
        "activate:forget-interrupted-message",
        "cancel:message-1",
        "execute:forget-interrupted-message",
    ]


@pytest.mark.asyncio
async def test_recovery_replays_pre_run_turn_from_first_persisted_intent(
    runtime_paths_with_schema,
    tmp_path,
) -> None:
    from magi.chat import ChatStore
    from magi.chat.read_service import ChatReadService
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))

    async def create_admitted_turn(turn_id: str, command_id: int) -> None:
        await store.create_user_turn_once(
            session_id="session-crash-replay",
            user_id="user-1",
            turn_id=turn_id,
            message_text=turn_id,
            created_at_ms=command_id,
            runtime_envelope={
                "source": "api",
                "user_id": "user-1",
                "session_id": "session-crash-replay",
                "turn_id": turn_id,
                "message": turn_id,
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint=f"fingerprint:{turn_id}",
        )
        assert await store.mark_user_turn_delivery_queued(
            turn_id=turn_id,
            delivery_attempt_no=0,
            command_id=command_id,
            updated_at_ms=command_id + 1,
        )
        assert await store.mark_user_turn_delivery_admitted(
            turn_id=turn_id,
            delivery_attempt_no=0,
            command_id=command_id,
            updated_at_ms=command_id + 2,
        )

    await create_admitted_turn("turn-delete", 71)
    await create_admitted_turn("turn-replay", 72)
    checkpoint_path = tmp_path / "l0-replay-recovery.db"
    original_l0 = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        restore_on_restart=True,
    )
    await original_l0.initialize()
    await original_l0.start_session(
        session_id="session-crash-replay",
        user_id="user-1",
    )
    await original_l0.push_goal(
        session_id="session-crash-replay",
        goal_id="goal-keep",
        goal_type="task",
        description="Keep unrelated working state",
    )
    await original_l0.push_goal(
        session_id="session-crash-replay",
        goal_id="chat_run:run-replay:0",
        goal_type="chat_run",
        description="turn-replay",
        metadata={"root_turn_id": "turn-replay"},
    )
    await original_l0.checkpoint_session("session-crash-replay")
    restored_l0 = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        restore_on_restart=True,
    )
    await restored_l0.initialize()
    selector = ForgetSelector.chat_message(
        user_id="user-1",
        session_id="session-crash-replay",
        message_id="message-delete",
        turn_id="turn-delete",
        source="chat",
        event_type="UserMessage",
        runtime_turn_ids=["turn-delete"],
        runtime_replay_turn_ids=["turn-replay"],
    )
    operation = type(
        "_Operation",
        (),
        {
            "operation_id": "forget-crash-replay",
            "selector": selector,
        },
    )()
    calls: list[str] = []

    class _Queue:
        @asynccontextmanager
        async def user_message_destructive_operation(self):  # type: ignore[no-untyped-def]
            yield

        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def block_user_message_scope_and_purge(
            self,
            **scope,
        ) -> int:  # type: ignore[no-untyped-def]
            calls.append(
                f"block:{scope['turn_id']}:{scope['message_id']}"
            )
            return 0

    read_service = ChatReadService()
    read_service._chat_db_path = runtime_paths_with_schema.chat_db_path

    class _AsyncRead:
        async def abump_nonterminal_user_turn_delivery_attempts(
            self,
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            *,
            bump_survivors,
        ):  # type: ignore[no-untyped-def]
            return read_service.bump_nonterminal_user_turn_delivery_attempts(
                user_id,
                session_id,
                excluded_turn_ids,
                updated_at_ms,
                bump_survivors=bump_survivors,
            )

    class _Scheduler:
        async def schedule_records(self, records):  # type: ignore[no-untyped-def]
            calls.extend(
                f"schedule:{record.turn_id}:{record.delivery_attempt_no}"
                for record in records
            )
            return []

    class _Memory:
        active = False

        @asynccontextmanager
        async def chat_forget_operation_guard(self):  # type: ignore[no-untyped-def]
            yield

        async def list_chat_forget_intents_awaiting_runtime_barriers(self):  # type: ignore[no-untyped-def]
            return [] if self.active else [operation]

        async def activate_chat_forget_intent(
            self,
            operation_id: str,
        ):  # type: ignore[no-untyped-def]
            calls.append(f"activate:{operation_id}")
            self.active = True
            return operation

        async def execute_prepared_forget(
            self,
            operation_id: str,
        ) -> ForgetOutcome:
            target = await store.get_user_turn_delivery(
                turn_id="turn-delete"
            )
            replay = await store.get_user_turn_delivery(
                turn_id="turn-replay"
            )
            assert target is not None
            assert target.delivery_state == "terminal"
            assert replay is not None
            assert replay.delivery_attempt_no == 1
            assert replay.delivery_state == "ready"
            calls.append(f"execute:{operation_id}")
            return ForgetOutcome(operation_id, "chat_message", 1, {})

        async def list_pending_chat_surface_finalizations(self):  # type: ignore[no-untyped-def]
            return []

    runtime = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=None,
        sensor_hub=None,
        chat_read_service=_AsyncRead(),
        delivery_scheduler=_Scheduler(),
        l0_store=restored_l0,
    )
    recovery = ChatForgettingRecoveryService(
        chat_read_service=_FakeReadService(calls),
        memory=_Memory(),
        runtime=runtime,
    )

    assert await recovery.recover_pending() == {
        "intents_found": 1,
        "intents_activated": 1,
        "surfaces_found": 0,
        "surfaces_completed": 0,
    }
    assert calls == [
        "block:None:message-delete",
        "block:turn-delete:None",
        "block:turn-replay:None",
        "schedule:turn-replay:1",
        "activate:forget-crash-replay",
        "execute:forget-crash-replay",
    ]
    replay_workbench = await restored_l0.get_workbench(
        "session-crash-replay"
    )
    assert [
        goal["goal_id"] for goal in replay_workbench["goal_stack"]
    ] == ["goal-keep"]
    read_service.close()


@pytest.mark.asyncio
async def test_assistant_delete_recovery_terminates_its_delivery_turn(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatMessageRecord, ChatStore
    from magi.chat.read_service import ChatReadService

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.create_user_turn_once(
        session_id="session-assistant-recovery",
        user_id="user-1",
        turn_id="turn-assistant-recovery",
        message_text="private prompt",
        created_at_ms=100,
        runtime_envelope={
            "source": "api",
            "user_id": "user-1",
            "session_id": "session-assistant-recovery",
            "turn_id": "turn-assistant-recovery",
            "message": "private prompt",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint="assistant-recovery",
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-assistant-recovery",
        delivery_attempt_no=0,
        command_id=81,
        updated_at_ms=110,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-assistant-recovery",
        delivery_attempt_no=0,
        command_id=81,
        updated_at_ms=120,
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="assistant-message-recovery",
            session_id="session-assistant-recovery",
            turn_id="turn-assistant-recovery",
            user_id="user-1",
            role="assistant",
            message_kind="assistant_final",
            content_text="private response",
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=130,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    selector = ForgetSelector.chat_message(
        user_id="user-1",
        session_id="session-assistant-recovery",
        message_id="assistant-message-recovery",
        turn_id="turn-assistant-recovery",
        source="chat",
        event_type="AIResponse",
        runtime_turn_ids=["turn-assistant-recovery"],
    )
    operation = type(
        "_Operation",
        (),
        {
            "operation_id": "forget-assistant-recovery",
            "selector": selector,
        },
    )()

    class _Memory:
        active = False

        @asynccontextmanager
        async def chat_forget_operation_guard(self):  # type: ignore[no-untyped-def]
            yield

        async def list_chat_forget_intents_awaiting_runtime_barriers(self):  # type: ignore[no-untyped-def]
            return [] if self.active else [operation]

        async def activate_chat_forget_intent(self, _operation_id: str):  # type: ignore[no-untyped-def]
            self.active = True
            return operation

        async def execute_prepared_forget(self, operation_id: str) -> ForgetOutcome:
            return ForgetOutcome(operation_id, "chat_message", 1, {})

        async def list_pending_chat_surface_finalizations(self):  # type: ignore[no-untyped-def]
            return []

    blocked_scopes: list[tuple[str | None, str | None]] = []

    class _Queue:
        @asynccontextmanager
        async def user_message_destructive_operation(self):  # type: ignore[no-untyped-def]
            yield

        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def block_user_message_scope_and_purge(self, **scope) -> int:  # type: ignore[no-untyped-def]
            blocked_scopes.append((scope["turn_id"], scope["message_id"]))
            return 0

    class _Scheduler:
        async def schedule_records(self, records):  # type: ignore[no-untyped-def]
            raise AssertionError(f"Deleted assistant turn was rescheduled: {records}")

    read_service = ChatReadService()
    read_service._chat_db_path = runtime_paths_with_schema.chat_db_path

    class _AsyncRead:
        async def abump_nonterminal_user_turn_delivery_attempts(
            self,
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            *,
            bump_survivors,
        ):  # type: ignore[no-untyped-def]
            return read_service.bump_nonterminal_user_turn_delivery_attempts(
                user_id,
                session_id,
                excluded_turn_ids,
                updated_at_ms,
                bump_survivors=bump_survivors,
            )

    runtime = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=None,
        sensor_hub=None,
        chat_read_service=_AsyncRead(),
        delivery_scheduler=_Scheduler(),
    )
    recovery = ChatForgettingRecoveryService(
        chat_read_service=read_service,
        memory=_Memory(),
        runtime=runtime,
    )

    assert await recovery.recover_pending() == {
        "intents_found": 1,
        "intents_activated": 1,
        "surfaces_found": 0,
        "surfaces_completed": 0,
    }
    delivery = await store.get_user_turn_delivery(
        turn_id="turn-assistant-recovery"
    )
    turn = await store.get_turn("turn-assistant-recovery")
    assert delivery is not None
    assert delivery.delivery_state == "terminal"
    assert turn is not None and turn.status == "cancelled"
    assert (
        read_service.list_recoverable_user_turn_deliveries(
            "user-1",
            "session-assistant-recovery",
        )
        == []
    )
    assert blocked_scopes == [
        (None, "assistant-message-recovery"),
        ("turn-assistant-recovery", None),
    ]
    assert selector.payload["event_type"] == "AIResponse"
    assert selector.payload["message_id"] == "assistant-message-recovery"
    read_service.close()


@pytest.mark.asyncio
async def test_runtime_forgetting_stops_matching_background_work() -> None:
    calls: list[tuple[str | None, frozenset[str] | None, str]] = []

    class _Queue:
        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def block_user_message_scope_and_purge(
            self,
            **scope,
        ) -> int:  # type: ignore[no-untyped-def]
            return 0

    class _Background:
        async def cancel_scope_and_wait(
            self,
            *,
            user_id=None,
            session_id=None,
            origin_turn_ids=None,
            task_ids=None,
            pending_message_ids=None,
            reason="conversation_deleted",
            timeout_seconds=30.0,
        ):  # type: ignore[no-untyped-def]
            assert user_id == "u1"
            assert timeout_seconds == 30.0
            if reason == "user_delete_chat_message":
                assert task_ids is None
                assert pending_message_ids == {"message-1"}
            calls.append(
                (
                    session_id,
                    (
                        frozenset(origin_turn_ids)
                        if origin_turn_ids is not None
                        else None
                    ),
                    reason,
                )
            )
            return 1

        @asynccontextmanager
        async def conversation_scope_boundary(
            self,
            **scope,
        ):  # type: ignore[no-untyped-def]
            await self.cancel_scope_and_wait(**scope)
            yield

    class _Read:
        async def abump_nonterminal_user_turn_delivery_attempts(
            self,
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            *,
            bump_survivors,
        ):  # type: ignore[no-untyped-def]
            return []

    class _Scheduler:
        async def schedule_records(self, records):  # type: ignore[no-untyped-def]
            return []

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=None,
        sensor_hub=None,
        chat_read_service=_Read(),
        delivery_scheduler=_Scheduler(),
        background_task_manager=_Background(),
    )

    await coordinator.prepare_session_delete(
        user_id="u1",
        session_id="session-delete",
    )
    await coordinator.quiesce_history_clear(
        user_id="u1",
        session_id="session-history",
    )
    await coordinator.prepare_message_delete(
        user_id="u1",
        session_id="session-message",
        turn_id="turn-message",
        message_id="message-1",
        include_turn_scope=True,
        run_id=None,
        run_revision=0,
        runtime_turn_ids=["turn-message"],
    )

    assert calls == [
        (
            "session-delete",
            None,
            "user_delete_chat_session",
        ),
        (
            "session-history",
            None,
            "user_clear_chat_history",
        ),
        (
            "session-message",
            frozenset({"turn-message"}),
            "user_delete_chat_message",
        ),
    ]


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
        @asynccontextmanager
        async def hold_chat_session_for_message_delete(self, **scope):  # type: ignore[no-untyped-def]
            calls.append(
                f"hold-enter:{scope['session_id']}:{scope['turn_id']}:"
                f"{scope['expected_run_id']}:{scope['expected_run_revision']}:"
                f"{scope['match_turn_scope']}"
            )
            class _Hold:
                cancelled_agent = False
                cancellation_error = None
                terminal_turn_ids: tuple[str, ...] = ()
                replay_turn_ids: tuple[str, ...] = ()

                async def prepare_after_barrier(self) -> None:
                    calls.append("cancel-after-barrier")
                    self.cancelled_agent = True

            yield _Hold()
            calls.append("hold-exit")

    class _Hub:
        async def discard_user_message_scope(self, **scope) -> int:  # type: ignore[no-untyped-def]
            calls.append(
                f"sensor-purge:{scope['session_id']}:{scope['turn_id']}:"
                f"{scope['message_id']}"
            )
            return 1

    class _Background:
        @asynccontextmanager
        async def conversation_scope_boundary(
            self,
            **scope,
        ):  # type: ignore[no-untyped-def]
            assert scope == {
                "user_id": "u1",
                "session_id": "session-1",
                "origin_turn_ids": {"turn-1"},
                "task_ids": {"task-1"},
                "pending_message_ids": {
                    "message-1",
                    "replacement-1",
                },
                "reason": "user_delete_chat_message",
            }
            calls.append("background-scope-enter")
            try:
                yield
            finally:
                calls.append("background-scope-exit")

    class _Read:
        async def abump_nonterminal_user_turn_delivery_attempts(
            self,
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            *,
            bump_survivors,
        ):  # type: ignore[no-untyped-def]
            assert updated_at_ms > 0
            calls.append(
                f"bump:{user_id}:{session_id}:{','.join(excluded_turn_ids)}:"
                f"{bump_survivors}"
            )
            return ["survivor"]

    class _Scheduler:
        async def schedule_records(self, records):  # type: ignore[no-untyped-def]
            calls.append(f"schedule:{','.join(records)}")
            return []

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=_Manager(),
        sensor_hub=_Hub(),
        chat_read_service=_Read(),
        delivery_scheduler=_Scheduler(),
        background_task_manager=_Background(),
    )

    async with coordinator.message_delete_boundary(
        user_id="u1",
        session_id="session-1",
        turn_id="turn-1",
        message_id="message-1",
        include_turn_scope=True,
        run_id="run-1",
        run_revision=0,
        related_message_ids=["message-1", "replacement-1"],
        background_task_ids=["task-1"],
    ) as result:
        calls.append("surface-hidden")
        assert not any(call.startswith("schedule:") for call in calls)

    assert calls == [
        "hold-enter:session-1:turn-1:run-1:0:True",
        "background-scope-enter",
        "queue-boundary-enter",
        "queue-block:None:message-1",
        "queue-block:None:replacement-1",
        "queue-block:turn-1:None",
        "queue-boundary-exit",
        "cancel-after-barrier",
        "bump:u1:session-1:turn-1:True",
        "sensor-purge:session-1:None:message-1",
        "sensor-purge:session-1:None:replacement-1",
        "sensor-purge:session-1:turn-1:None",
        "surface-hidden",
        "schedule:survivor",
        "background-scope-exit",
        "hold-exit",
    ]
    assert result.purged_commands == 6
    assert result.purged_sensor_events == 3
    assert result.cancelled_agent is True


@pytest.mark.asyncio
async def test_message_delete_first_intent_contains_pre_run_replay_scope() -> None:
    prepared: list[tuple[list[str], list[str]]] = []
    calls: list[str] = []
    prepare_after_called = False

    class _Queue:
        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated crash after first intent")
            yield

    class _Manager:
        @asynccontextmanager
        async def hold_chat_session_for_message_delete(
            self,
            **_scope,
        ):  # type: ignore[no-untyped-def]
            class _Hold:
                cancelled_agent = False
                cancellation_error = None
                terminal_turn_ids = ("turn-delete",)
                replay_turn_ids = ("turn-replay",)

                async def prepare_after_barrier(self) -> None:
                    nonlocal prepare_after_called
                    prepare_after_called = True

            yield _Hold()

    class _Background:
        async def cancel_scope_and_wait(self, **scope) -> int:  # type: ignore[no-untyped-def]
            calls.append("background-quiesced")
            assert scope == {
                "user_id": "user-1",
                "session_id": "session-1",
                "origin_turn_ids": {
                    "turn-delete",
                    "turn-replay",
                },
                "pending_message_ids": {"message-delete"},
                "reason": "user_delete_chat_message",
            }
            return 1

        @asynccontextmanager
        async def conversation_scope_boundary(
            self,
            **scope,
        ):  # type: ignore[no-untyped-def]
            await self.cancel_scope_and_wait(**scope)
            yield

    async def prepare_intent(
        terminal_turn_ids: list[str],
        replay_turn_ids: list[str],
    ) -> None:
        calls.append("intent-prepared")
        assert calls == [
            "background-quiesced",
            "intent-prepared",
        ]
        prepared.append(
            (list(terminal_turn_ids), list(replay_turn_ids))
        )

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=_Manager(),
        sensor_hub=None,
        chat_read_service=object(),
        delivery_scheduler=object(),
        background_task_manager=_Background(),
    )

    with pytest.raises(
        RuntimeError,
        match="simulated crash after first intent",
    ):
        async with coordinator.message_delete_boundary(
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-delete",
            message_id="message-delete",
            include_turn_scope=True,
            run_id=None,
            run_revision=0,
            runtime_turn_ids=["turn-delete"],
            prepare_intent=prepare_intent,
        ):
            raise AssertionError("The deletion body must not be entered")

    assert prepared == [
        (["turn-delete"], ["turn-replay"]),
    ]
    assert calls == [
        "background-quiesced",
        "intent-prepared",
    ]
    assert prepare_after_called is False


@pytest.mark.asyncio
async def test_assistant_message_runtime_delete_keeps_user_turn_scope() -> None:
    calls: list[str] = []

    class _Queue:
        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def block_user_message_scope_and_purge(self, **scope) -> int:  # type: ignore[no-untyped-def]
            calls.append(f"queue:{scope['turn_id']}:{scope['message_id']}")
            return 0

    class _Manager:
        @asynccontextmanager
        async def hold_chat_session_for_message_delete(self, **scope):  # type: ignore[no-untyped-def]
            calls.append(
                f"hold:{scope['turn_id']}:{scope['expected_run_id']}:"
                f"{scope['expected_run_revision']}:{scope['match_turn_scope']}"
            )

            class _Hold:
                cancelled_agent = True
                cancellation_error = None
                terminal_turn_ids: tuple[str, ...] = ()
                replay_turn_ids: tuple[str, ...] = ()

                async def prepare_after_barrier(self) -> None:
                    return None

            yield _Hold()

    class _Hub:
        async def discard_user_message_scope(self, **scope) -> int:  # type: ignore[no-untyped-def]
            calls.append(f"sensor:{scope['turn_id']}:{scope['message_id']}")
            return 0

    class _Read:
        async def abump_nonterminal_user_turn_delivery_attempts(
            self,
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            *,
            bump_survivors,
        ):  # type: ignore[no-untyped-def]
            _ = updated_at_ms
            calls.append(
                f"bump:{user_id}:{session_id}:{excluded_turn_ids}:{bump_survivors}"
            )
            return ["root"]

    class _Scheduler:
        async def schedule_records(self, records):  # type: ignore[no-untyped-def]
            calls.append(f"schedule:{records}")
            return []

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=_Manager(),
        sensor_hub=_Hub(),
        chat_read_service=_Read(),
        delivery_scheduler=_Scheduler(),
    )

    await coordinator.prepare_message_delete(
        user_id="u1",
        session_id="session-1",
        turn_id="turn-1",
        message_id="assistant-message",
        include_turn_scope=False,
        run_id="run-1",
        run_revision=0,
    )

    assert calls == [
        "hold:turn-1:run-1:0:False",
        "queue:None:assistant-message",
        "queue:turn-1:None",
        "bump:u1:session-1:['turn-1']:True",
        "sensor:None:assistant-message",
        "sensor:turn-1:None",
        "schedule:['root']",
    ]


@pytest.mark.asyncio
async def test_message_delete_invalidates_real_ledger_before_scheduling_survivors(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatStore
    from magi.chat.read_service import ChatReadService

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    read_service = ChatReadService()
    read_service._chat_db_path = runtime_paths_with_schema.chat_db_path

    async def create_turn(
        *,
        session_id: str,
        turn_id: str,
        created_at_ms: int,
        command_id: int | None,
        terminal: bool = False,
    ) -> None:
        await store.create_user_turn_once(
            session_id=session_id,
            user_id="user-1",
            turn_id=turn_id,
            message_text=turn_id,
            created_at_ms=created_at_ms,
            runtime_envelope={
                "source": "api",
                "user_id": "user-1",
                "session_id": session_id,
                "turn_id": turn_id,
                "message": turn_id,
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint=f"fingerprint:{turn_id}",
        )
        if command_id is None:
            return
        assert await store.mark_user_turn_delivery_queued(
            turn_id=turn_id,
            delivery_attempt_no=0,
            command_id=command_id,
            updated_at_ms=created_at_ms + 1,
        )
        assert await store.mark_user_turn_delivery_admitted(
            turn_id=turn_id,
            delivery_attempt_no=0,
            command_id=command_id,
            updated_at_ms=created_at_ms + 2,
        )
        if terminal:
            assert await store.mark_user_turn_delivery_terminal(
                turn_id=turn_id,
                delivery_attempt_no=0,
                command_id=command_id,
                updated_at_ms=created_at_ms + 3,
            )

    await create_turn(
        session_id="session-ledger-delete",
        turn_id="turn-target",
        created_at_ms=100,
        command_id=11,
    )
    await create_turn(
        session_id="session-ledger-delete",
        turn_id="turn-survivor",
        created_at_ms=200,
        command_id=22,
    )
    await create_turn(
        session_id="session-ledger-delete",
        turn_id="turn-complete",
        created_at_ms=300,
        command_id=33,
        terminal=True,
    )
    await create_turn(
        session_id="session-other",
        turn_id="turn-other-session",
        created_at_ms=400,
        command_id=None,
    )

    class _Queue:
        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def block_user_message_scope_and_purge(self, **_scope) -> int:  # type: ignore[no-untyped-def]
            return 1

    class _Manager:
        @asynccontextmanager
        async def hold_chat_session_for_message_delete(self, **_scope):  # type: ignore[no-untyped-def]
            class _Hold:
                cancelled_agent = True
                cancellation_error = None
                terminal_turn_ids: tuple[str, ...] = ()
                replay_turn_ids: tuple[str, ...] = ()

                async def prepare_after_barrier(self) -> None:
                    return None

            yield _Hold()

    scheduled: list[tuple[str, int, str]] = []

    class _Scheduler:
        async def schedule_records(self, records):  # type: ignore[no-untyped-def]
            scheduled.extend(
                (
                    record.turn_id,
                    record.delivery_attempt_no,
                    record.delivery_state,
                )
                for record in records
            )
            return []

    class _AsyncRead:
        async def abump_nonterminal_user_turn_delivery_attempts(
            self,
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            *,
            bump_survivors,
        ):  # type: ignore[no-untyped-def]
            return read_service.bump_nonterminal_user_turn_delivery_attempts(
                user_id,
                session_id,
                excluded_turn_ids,
                updated_at_ms,
                bump_survivors=bump_survivors,
            )

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=_Manager(),
        sensor_hub=None,
        chat_read_service=_AsyncRead(),
        delivery_scheduler=_Scheduler(),
    )

    async with coordinator.message_delete_boundary(
        user_id="user-1",
        session_id="session-ledger-delete",
        turn_id="turn-target",
        message_id="message-target",
        include_turn_scope=True,
        run_id="run-target",
        run_revision=0,
    ):
        target = await store.get_user_turn_delivery(turn_id="turn-target")
        survivor = await store.get_user_turn_delivery(turn_id="turn-survivor")
        complete = await store.get_user_turn_delivery(turn_id="turn-complete")
        other = await store.get_user_turn_delivery(turn_id="turn-other-session")

        assert target is not None and target.delivery_state == "terminal"
        assert survivor is not None
        assert survivor.delivery_attempt_no == 1
        assert survivor.delivery_state == "ready"
        assert survivor.current_command_id is None
        assert complete is not None
        assert complete.delivery_attempt_no == 0
        assert complete.delivery_state == "terminal"
        assert other is not None
        assert other.delivery_attempt_no == 0
        assert other.delivery_state == "ready"
        assert scheduled == []

    assert scheduled == [("turn-survivor", 1, "ready")]
    read_service.close()


@pytest.mark.asyncio
async def test_stopped_newer_run_is_terminal_when_cancel_cleanup_fails(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatStore
    from magi.chat.read_service import ChatReadService

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))

    async def create_admitted_turn(turn_id: str, command_id: int) -> None:
        await store.create_user_turn_once(
            session_id="session-cancel-failure",
            user_id="user-1",
            turn_id=turn_id,
            message_text=turn_id,
            created_at_ms=command_id,
            runtime_envelope={
                "source": "api",
                "user_id": "user-1",
                "session_id": "session-cancel-failure",
                "turn_id": turn_id,
                "message": turn_id,
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint=f"fingerprint:{turn_id}",
        )
        assert await store.mark_user_turn_delivery_queued(
            turn_id=turn_id,
            delivery_attempt_no=0,
            command_id=command_id,
            updated_at_ms=command_id + 1,
        )
        assert await store.mark_user_turn_delivery_admitted(
            turn_id=turn_id,
            delivery_attempt_no=0,
            command_id=command_id,
            updated_at_ms=command_id + 2,
        )

    await create_admitted_turn("turn-delete-target", 91)
    await create_admitted_turn("turn-newer-root", 92)
    await create_admitted_turn("turn-later-survivor", 93)

    blocked_scopes: list[tuple[str | None, str | None]] = []

    class _Queue:
        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def block_user_message_scope_and_purge(self, **scope) -> int:  # type: ignore[no-untyped-def]
            blocked_scopes.append((scope["turn_id"], scope["message_id"]))
            return 0

    class _Manager:
        @asynccontextmanager
        async def hold_chat_session_for_message_delete(self, **_scope):  # type: ignore[no-untyped-def]
            class _Hold:
                cancelled_agent = False
                cancellation_error = None
                terminal_turn_ids = (
                    "turn-delete-target",
                    "turn-newer-root",
                )
                replay_turn_ids = ()

                async def prepare_after_barrier(self) -> None:
                    self.cancelled_agent = True
                    self.cancellation_error = OSError(
                        "cancel cleanup unavailable"
                    )

            yield _Hold()

    scheduled_turn_ids: list[str] = []

    class _Scheduler:
        async def schedule_records(self, records):  # type: ignore[no-untyped-def]
            scheduled_turn_ids.extend(record.turn_id for record in records)
            return []

    read_service = ChatReadService()
    read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    prepared_runtime_turn_ids: list[list[str]] = []

    class _AsyncRead:
        async def abump_nonterminal_user_turn_delivery_attempts(
            self,
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            *,
            bump_survivors,
        ):  # type: ignore[no-untyped-def]
            return read_service.bump_nonterminal_user_turn_delivery_attempts(
                user_id,
                session_id,
                excluded_turn_ids,
                updated_at_ms,
                bump_survivors=bump_survivors,
            )

    async def prepare_intent(
        runtime_turn_ids: list[str],
        replay_turn_ids: list[str],
    ) -> None:
        assert replay_turn_ids == []
        prepared_runtime_turn_ids.append(list(runtime_turn_ids))

    coordinator = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=_Manager(),
        sensor_hub=None,
        chat_read_service=_AsyncRead(),
        delivery_scheduler=_Scheduler(),
    )
    with pytest.raises(
        RuntimeError,
        match="Failed to cancel chat run before message deletion",
    ):
        async with coordinator.message_delete_boundary(
            user_id="user-1",
            session_id="session-cancel-failure",
            turn_id="turn-delete-target",
            message_id="message-delete-target",
            include_turn_scope=True,
            run_id="run-deleted",
            run_revision=0,
            runtime_turn_ids=["turn-delete-target"],
            prepare_intent=prepare_intent,
        ):
            raise AssertionError("Failed cancellation must not expose deletion body")

    target = await store.get_user_turn_delivery(turn_id="turn-delete-target")
    root = await store.get_user_turn_delivery(turn_id="turn-newer-root")
    survivor = await store.get_user_turn_delivery(turn_id="turn-later-survivor")
    root_turn = await store.get_turn("turn-newer-root")
    assert target is not None and target.delivery_state == "terminal"
    assert root is not None and root.delivery_state == "terminal"
    assert root_turn is not None and root_turn.status == "cancelled"
    assert survivor is not None
    assert survivor.delivery_attempt_no == 1
    assert survivor.delivery_state == "ready"
    assert scheduled_turn_ids == []
    assert prepared_runtime_turn_ids == [
        ["turn-delete-target", "turn-newer-root"],
    ]
    assert blocked_scopes == [
        (None, "message-delete-target"),
        ("turn-delete-target", None),
        ("turn-newer-root", None),
    ]

    retry = ChatRuntimeForgettingCoordinator(
        runtime_command_queue=_Queue(),
        task_agent_manager=None,
        sensor_hub=None,
        chat_read_service=_AsyncRead(),
        delivery_scheduler=_Scheduler(),
    )
    await retry.prepare_message_delete(
        user_id="user-1",
        session_id="session-cancel-failure",
        turn_id="turn-delete-target",
        message_id="message-delete-target",
        include_turn_scope=True,
        run_id=None,
        run_revision=0,
        runtime_turn_ids=prepared_runtime_turn_ids[-1],
    )
    retried_root = await store.get_user_turn_delivery(
        turn_id="turn-newer-root"
    )
    assert retried_root is not None
    assert retried_root.delivery_state == "terminal"
    assert scheduled_turn_ids == []
    read_service.close()
