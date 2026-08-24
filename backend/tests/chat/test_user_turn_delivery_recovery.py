from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from magi.chat import ChatMessageRecord, ChatReadService, ChatStore
from magi.chat.contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    ChatUserTurnDeliveryRecord,
)
from magi.chat.memory_projection_clear import ChatMemoryProjectionClearLifecycle
from magi.chat.user_turn_delivery import (
    ChatUserTurnDeliveryRecoveryService,
    ChatUserTurnDeliveryScheduler,
    InvalidUserTurnDeliveryEnvelopeError,
    StaleUserTurnDeliveryError,
    parse_user_turn_runtime_envelope,
)
from magi.events.runtime_queue import (
    SQLiteRuntimeCommandQueue,
    UserMessageScheduleOutcome,
    UserMessageScheduleResult,
)


class _RecordingProjector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def project_user_message(self, **kwargs: Any) -> bool:
        self.calls.append(dict(kwargs))
        return True


class _L1RecordingProjector(_RecordingProjector):
    def __init__(self) -> None:
        super().__init__()
        self.message_ids: set[str] = set()

    async def project_user_message(self, **kwargs: Any) -> bool:
        await super().project_user_message(**kwargs)
        self.message_ids.add(str(kwargs["message_id"]))
        return True


class _ClearGenerationState:
    def __init__(self) -> None:
        self.value = 0

    async def read(self) -> int:
        return self.value


def _clear_lifecycle(
    state: _ClearGenerationState | None = None,
) -> ChatMemoryProjectionClearLifecycle:
    generation = state or _ClearGenerationState()
    return ChatMemoryProjectionClearLifecycle(
        read_current_clear_generation=generation.read,
    )


class _FastAdmittingQueue:
    def __init__(self, *, store: ChatStore, command_id: int) -> None:
        self._store = store
        self._command_id = command_id

    async def schedule_user_message(self, command: Any) -> UserMessageScheduleResult:
        changed = await self._store.mark_user_turn_delivery_admitted(
            turn_id=command.turn_id,
            delivery_attempt_no=command.delivery_attempt_no,
            command_id=self._command_id,
            updated_at_ms=200,
        )
        assert changed
        return UserMessageScheduleResult(
            outcome=UserMessageScheduleOutcome.SCHEDULED,
            command_id=self._command_id,
            current_attempt_no=command.delivery_attempt_no,
        )


class _StaleQueue:
    async def schedule_user_message(self, command: Any) -> UserMessageScheduleResult:
        return UserMessageScheduleResult(
            outcome=UserMessageScheduleOutcome.STALE,
            command_id=900,
            current_attempt_no=command.delivery_attempt_no + 1,
        )


class _ScopedReadService:
    def __init__(self, chat_db_path: Path) -> None:
        self._service = ChatReadService()
        self._service.close()
        self._service._chat_db_path = chat_db_path

    async def alist_recoverable_user_turn_deliveries(
        self,
        *,
        limit: int,
        after: ChatUserTurnDeliveryRecord | None,
    ) -> list[ChatUserTurnDeliveryRecord]:
        return self._service.list_recoverable_user_turn_deliveries(
            limit=limit,
            after=after,
        )

    def close(self) -> None:
        self._service.close()


class _PausingReadService(_ScopedReadService):
    def __init__(self, chat_db_path: Path) -> None:
        super().__init__(chat_db_path)
        self.read_started = asyncio.Event()
        self.release_read = asyncio.Event()
        self._paused = False

    async def alist_recoverable_user_turn_deliveries(
        self,
        *,
        limit: int,
        after: ChatUserTurnDeliveryRecord | None,
    ) -> list[ChatUserTurnDeliveryRecord]:
        page = await super().alist_recoverable_user_turn_deliveries(
            limit=limit,
            after=after,
        )
        if page and not self._paused:
            self._paused = True
            self.read_started.set()
            await self.release_read.wait()
        return page


def _runtime_envelope(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source": "api",
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "message": message,
        "attachments": [],
        "workspace_path": None,
        "interaction_kind": None,
        "metadata": dict(metadata or {}),
        "runtime_namespace": "desktop",
    }


async def _create_delivery(
    store: ChatStore,
    *,
    turn_id: str,
    created_at_ms: int,
    projected: bool = True,
    run_disposition: str | None = None,
) -> ChatUserTurnDeliveryRecord:
    session_id = "session-recovery"
    user_id = "user-recovery"
    message = f"message for {turn_id}"
    await store.create_user_turn_once(
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        message_text=message,
        created_at_ms=created_at_ms,
        run_disposition=run_disposition,
        runtime_envelope=_runtime_envelope(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            message=message,
        ),
        request_fingerprint=f"fingerprint-{turn_id}",
    )
    if projected:
        await store.mark_user_turn_projection_completed(
            turn_id=turn_id,
            updated_at_ms=created_at_ms + 1,
        )
    record = await store.get_user_turn_delivery(turn_id=turn_id)
    assert record is not None
    return record


def _read_service(chat_db_path: Path) -> _ScopedReadService:
    return _ScopedReadService(chat_db_path)


def _recovery_service(
    *,
    store: ChatStore,
    read_service: _ScopedReadService,
    projector: _RecordingProjector,
    queue: Any,
    page_size: int = 250,
    clear_lifecycle: ChatMemoryProjectionClearLifecycle | None = None,
) -> ChatUserTurnDeliveryRecoveryService:
    return ChatUserTurnDeliveryRecoveryService(
        chat_store=store,
        chat_read_service=read_service,
        chat_projector=projector,
        delivery_scheduler=ChatUserTurnDeliveryScheduler(
            chat_store=store,
            runtime_command_queue=queue,
        ),
        clear_lifecycle=clear_lifecycle or _clear_lifecycle(),
        page_size=page_size,
    )


def _delivery_record() -> ChatUserTurnDeliveryRecord:
    return ChatUserTurnDeliveryRecord(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        message_id="message-1",
        projection_completed=True,
        delivery_attempt_no=0,
        delivery_state="ready",
        current_command_id=None,
        runtime_envelope=_runtime_envelope(
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            message="hello",
        ),
        request_fingerprint="fingerprint-1",
        created_at_ms=100,
        sequence_no=1,
    )


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    (
        ("user_id", "other-user"),
        ("session_id", "other-session"),
        ("turn_id", "other-turn"),
    ),
)
def test_runtime_envelope_rejects_mismatched_owner_identity(
    field_name: str,
    wrong_value: str,
) -> None:
    record = _delivery_record()
    record.runtime_envelope[field_name] = wrong_value

    with pytest.raises(InvalidUserTurnDeliveryEnvelopeError):
        parse_user_turn_runtime_envelope(record)


@pytest.mark.asyncio
async def test_scheduler_attaches_ready_attempt_to_real_runtime_queue(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    record = await _create_delivery(
        store,
        turn_id="turn-ready",
        created_at_ms=100,
    )
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    await queue.start()
    try:
        result = await ChatUserTurnDeliveryScheduler(
            chat_store=store,
            runtime_command_queue=queue,
        ).schedule_record(record)

        persisted = await store.get_user_turn_delivery(turn_id=record.turn_id)
        assert result.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert result.command_id is not None
        assert persisted is not None
        assert persisted.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert persisted.current_command_id == result.command_id
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_scheduler_accepts_consumer_admission_before_queue_mark(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    record = await _create_delivery(
        store,
        turn_id="turn-fast-admission",
        created_at_ms=100,
    )
    result = await ChatUserTurnDeliveryScheduler(
        chat_store=store,
        runtime_command_queue=_FastAdmittingQueue(store=store, command_id=701),
    ).schedule_record(record)

    persisted = await store.get_user_turn_delivery(turn_id=record.turn_id)
    assert result.delivery_state == CHAT_DELIVERY_STATE_ADMITTED
    assert result.command_id == 701
    assert persisted is not None
    assert persisted.delivery_state == CHAT_DELIVERY_STATE_ADMITTED
    assert persisted.current_command_id == 701


@pytest.mark.asyncio
async def test_scheduler_rejects_attempt_older_than_runtime_queue(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    record = await _create_delivery(
        store,
        turn_id="turn-stale",
        created_at_ms=100,
    )
    scheduler = ChatUserTurnDeliveryScheduler(
        chat_store=store,
        runtime_command_queue=_StaleQueue(),
    )

    with pytest.raises(StaleUserTurnDeliveryError):
        await scheduler.schedule_record(record)

    persisted = await store.get_user_turn_delivery(turn_id=record.turn_id)
    assert persisted is not None
    assert persisted.delivery_state == "ready"
    assert persisted.current_command_id is None


@pytest.mark.asyncio
async def test_startup_requires_visible_result_except_for_no_reply_turns(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    final_record = await _create_delivery(
        store,
        turn_id="turn-with-final",
        created_at_ms=100,
    )
    no_reply_record = await _create_delivery(
        store,
        turn_id="turn-completed-no-reply",
        created_at_ms=200,
    )
    missing_final_record = await _create_delivery(
        store,
        turn_id="turn-completed-missing-final",
        created_at_ms=250,
    )
    deferred_record = await _create_delivery(
        store,
        turn_id="turn-completed-defer",
        created_at_ms=300,
        run_disposition="message",
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="assistant-final-1",
            session_id=final_record.session_id,
            turn_id=final_record.turn_id,
            user_id=final_record.user_id,
            role="assistant",
            message_kind="assistant_final",
            content_text="finished already",
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=150,
            sequence_no=100,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    for record, disposition in (
        (no_reply_record, None),
        (missing_final_record, None),
        (deferred_record, "defer"),
    ):
        turn = await store.get_turn(record.turn_id)
        assert turn is not None
        turn.status = "completed"
        turn.run_disposition = disposition
        if record.turn_id == no_reply_record.turn_id:
            turn.response_mode = "none"
        turn.updated_at_ms += 10
        turn.completed_at_ms = turn.updated_at_ms
        await store.upsert_turn(turn)

    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    read_service = _read_service(runtime_paths_with_schema.chat_db_path)
    projector = _RecordingProjector()
    await queue.start()
    try:
        stats = await _recovery_service(
            store=store,
            read_service=read_service,
            projector=projector,
            queue=queue,
            page_size=2,
        ).recover_startup()

        final_current = await store.get_user_turn_delivery(
            turn_id=final_record.turn_id
        )
        no_reply_current = await store.get_user_turn_delivery(
            turn_id=no_reply_record.turn_id
        )
        missing_final_current = await store.get_user_turn_delivery(
            turn_id=missing_final_record.turn_id
        )
        deferred_current = await store.get_user_turn_delivery(
            turn_id=deferred_record.turn_id
        )
        assert stats.found == 4
        assert stats.terminal == 2
        assert stats.scheduled == 2
        assert final_current is not None
        assert final_current.delivery_state == "terminal"
        repaired_final_turn = await store.get_turn(final_record.turn_id)
        assert repaired_final_turn is not None
        assert repaired_final_turn.status == "completed"
        assert repaired_final_turn.completed_at_ms == 150
        assert no_reply_current is not None
        assert no_reply_current.delivery_state == "terminal"
        assert missing_final_current is not None
        assert missing_final_current.delivery_attempt_no == 1
        assert missing_final_current.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert deferred_current is not None
        assert deferred_current.delivery_attempt_no == 1
        assert deferred_current.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert projector.calls == []
    finally:
        read_service.close()
        await queue.stop()


@pytest.mark.asyncio
async def test_startup_distinguishes_complete_visible_output_from_partial_or_hidden_output(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    complete_record = await _create_delivery(
        store,
        turn_id="turn-complete-rhythm",
        created_at_ms=100,
    )
    partial_record = await _create_delivery(
        store,
        turn_id="turn-partial-rhythm",
        created_at_ms=200,
    )
    hidden_record = await _create_delivery(
        store,
        turn_id="turn-hidden-final",
        created_at_ms=300,
    )
    for index in range(2):
        await store.append_message(
            ChatMessageRecord(
                message_id=f"complete-segment-{index}",
                session_id=complete_record.session_id,
                turn_id=complete_record.turn_id,
                user_id=complete_record.user_id,
                role="assistant",
                message_kind="assistant_rhythm_segment",
                content_text=f"complete {index}",
                payload_json=(
                    '{"rhythm":{"segment_count":2,"segment_index":'
                    f"{index}}}}}"
                ),
                is_final=True,
                is_visible=True,
                created_at_ms=150 + index,
                sequence_no=100 + index,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )
    await store.append_message(
        ChatMessageRecord(
            message_id="partial-segment-0",
            session_id=partial_record.session_id,
            turn_id=partial_record.turn_id,
            user_id=partial_record.user_id,
            role="assistant",
            message_kind="assistant_rhythm_segment",
            content_text="partial",
            payload_json='{"rhythm":{"segment_count":2,"segment_index":0}}',
            is_final=True,
            is_visible=True,
            created_at_ms=250,
            sequence_no=200,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="hidden-final",
            session_id=hidden_record.session_id,
            turn_id=hidden_record.turn_id,
            user_id=hidden_record.user_id,
            role="assistant",
            message_kind="assistant_final",
            content_text="not visible",
            payload_json="{}",
            is_final=True,
            is_visible=False,
            created_at_ms=350,
            sequence_no=300,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )

    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    read_service = _read_service(runtime_paths_with_schema.chat_db_path)
    await queue.start()
    try:
        stats = await _recovery_service(
            store=store,
            read_service=read_service,
            projector=_RecordingProjector(),
            queue=queue,
        ).recover_startup()

        assert stats.found == 3
        assert stats.terminal == 1
        assert stats.scheduled == 2
        complete_delivery = await store.get_user_turn_delivery(
            turn_id=complete_record.turn_id
        )
        partial_delivery = await store.get_user_turn_delivery(
            turn_id=partial_record.turn_id
        )
        hidden_delivery = await store.get_user_turn_delivery(
            turn_id=hidden_record.turn_id
        )
        assert complete_delivery is not None
        assert complete_delivery.delivery_state == "terminal"
        complete_turn = await store.get_turn(complete_record.turn_id)
        assert complete_turn is not None
        assert complete_turn.status == "completed"
        assert complete_turn.completed_at_ms == 151
        assert partial_delivery is not None
        assert partial_delivery.delivery_attempt_no == 1
        assert partial_delivery.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert hidden_delivery is not None
        assert hidden_delivery.delivery_attempt_no == 1
        assert hidden_delivery.delivery_state == CHAT_DELIVERY_STATE_QUEUED
    finally:
        read_service.close()
        await queue.stop()


@pytest.mark.asyncio
async def test_startup_invalidates_queued_and_admitted_attempts_before_replay(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    queued_record = await _create_delivery(
        store,
        turn_id="turn-was-queued",
        created_at_ms=100,
    )
    admitted_record = await _create_delivery(
        store,
        turn_id="turn-was-admitted",
        created_at_ms=200,
    )
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    scheduler = ChatUserTurnDeliveryScheduler(
        chat_store=store,
        runtime_command_queue=queue,
    )
    read_service = _read_service(runtime_paths_with_schema.chat_db_path)
    projector = _RecordingProjector()
    await queue.start()
    try:
        queued_initial = await scheduler.schedule_record(queued_record)
        admitted_initial = await scheduler.schedule_record(admitted_record)
        assert admitted_initial.command_id is not None
        assert await store.mark_user_turn_delivery_admitted(
            turn_id=admitted_record.turn_id,
            delivery_attempt_no=0,
            command_id=admitted_initial.command_id,
            updated_at_ms=250,
        )

        stats = await _recovery_service(
            store=store,
            read_service=read_service,
            projector=projector,
            queue=queue,
        ).recover_startup()

        queued_current = await store.get_user_turn_delivery(
            turn_id=queued_record.turn_id
        )
        admitted_current = await store.get_user_turn_delivery(
            turn_id=admitted_record.turn_id
        )
        assert stats.prepared == 2
        assert stats.scheduled == 2
        assert queued_current is not None
        assert queued_current.delivery_attempt_no == 1
        assert queued_current.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert queued_current.current_command_id != queued_initial.command_id
        assert admitted_current is not None
        assert admitted_current.delivery_attempt_no == 1
        assert admitted_current.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert admitted_current.current_command_id != admitted_initial.command_id

        with sqlite3.connect(runtime_paths_with_schema.message_queue_db_path) as conn:
            rows = conn.execute(
                """
                SELECT correlation_id, delivery_attempt_no, status
                FROM runtime_commands
                WHERE correlation_id IN (?, ?)
                ORDER BY correlation_id, delivery_attempt_no
                """,
                (
                    f"user_message:{queued_record.message_id}",
                    f"user_message:{admitted_record.message_id}",
                ),
            ).fetchall()
        assert len(rows) == 4
        assert [(int(row[1]), str(row[2])) for row in rows] == [
            (0, "completed"),
            (1, "pending"),
            (0, "completed"),
            (1, "pending"),
        ]
    finally:
        read_service.close()
        await queue.stop()


@pytest.mark.asyncio
async def test_startup_recovers_projection_before_scheduling(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    record = await _create_delivery(
        store,
        turn_id="turn-needs-projection",
        created_at_ms=100,
        projected=False,
    )
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    read_service = _read_service(runtime_paths_with_schema.chat_db_path)
    projector = _RecordingProjector()
    await queue.start()
    try:
        stats = await _recovery_service(
            store=store,
            read_service=read_service,
            projector=projector,
            queue=queue,
        ).recover_startup()

        current = await store.get_user_turn_delivery(turn_id=record.turn_id)
        assert stats.projected == 1
        assert stats.scheduled == 1
        assert current is not None
        assert current.projection_completed is True
        assert current.delivery_attempt_no == 1
        assert current.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert len(projector.calls) == 1
        assert projector.calls[0]["message_id"] == record.message_id
        assert projector.calls[0]["turn_id"] == record.turn_id
    finally:
        read_service.close()
        await queue.stop()


@pytest.mark.asyncio
async def test_read_recovery_cannot_repopulate_l1_after_full_clear(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_delivery(
        store,
        turn_id="turn-before-clear",
        created_at_ms=100,
        projected=False,
    )
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    read_service = _PausingReadService(runtime_paths_with_schema.chat_db_path)
    chat_clear = ChatReadService(runtime_paths=runtime_paths_with_schema)
    projector = _L1RecordingProjector()
    generation = _ClearGenerationState()
    clear_lifecycle = _clear_lifecycle(generation)
    recovery = _recovery_service(
        store=store,
        read_service=read_service,
        projector=projector,
        queue=queue,
        clear_lifecycle=clear_lifecycle,
    )

    async def clear_all() -> None:
        async with clear_lifecycle.user_content_clear_boundary():
            async with queue.user_message_global_clear_boundary():
                generation.value, _ = await queue.advance_user_message_generation_and_purge()
                await chat_clear.aclear_all_sessions()
                assert await chat_clear.acomplete_global_clear()
                projector.message_ids.clear()

    await queue.start()
    processing: asyncio.Task | None = None
    clearing: asyncio.Task | None = None
    try:
        processing = asyncio.create_task(recovery.retry_ready())
        await asyncio.wait_for(read_service.read_started.wait(), timeout=1.0)
        clearing = asyncio.create_task(clear_all())
        while not clear_lifecycle.clear_in_progress():
            await asyncio.sleep(0)
        assert clearing.done() is False

        read_service.release_read.set()
        stale_stats = await asyncio.wait_for(processing, timeout=1.0)
        await asyncio.wait_for(clearing, timeout=1.0)

        assert stale_stats.projected == 0
        assert stale_stats.scheduled == 0
        assert projector.calls == []
        assert projector.message_ids == set()

        fresh_record = await _create_delivery(
            store,
            turn_id="turn-after-clear",
            created_at_ms=200,
            projected=False,
        )
        fresh_stats = await recovery.retry_ready()

        assert fresh_stats.projected == 1
        assert fresh_stats.scheduled == 1
        assert projector.message_ids == {fresh_record.message_id}
    finally:
        read_service.release_read.set()
        for task in (processing, clearing):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (processing, clearing) if task is not None),
            return_exceptions=True,
        )
        read_service.close()
        chat_clear.close()
        await queue.stop()


@pytest.mark.asyncio
async def test_startup_recovers_every_page_in_stable_order(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    records = [
        await _create_delivery(
            store,
            turn_id=f"turn-page-{index}",
            created_at_ms=100 + index,
        )
        for index in range(5)
    ]
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    read_service = _read_service(runtime_paths_with_schema.chat_db_path)
    projector = _RecordingProjector()
    await queue.start()
    try:
        stats = await _recovery_service(
            store=store,
            read_service=read_service,
            projector=projector,
            queue=queue,
            page_size=2,
        ).recover_startup()

        current = [
            await store.get_user_turn_delivery(turn_id=record.turn_id)
            for record in records
        ]
        assert stats.found == 5
        assert stats.prepared == 5
        assert stats.scheduled == 5
        assert all(record is not None for record in current)
        assert [record.delivery_attempt_no for record in current if record] == [
            1,
            1,
            1,
            1,
            1,
        ]
        assert [
            record.delivery_state for record in current if record
        ] == [CHAT_DELIVERY_STATE_QUEUED] * 5
    finally:
        read_service.close()
        await queue.stop()


@pytest.mark.asyncio
async def test_corrupt_delivery_isolated_without_blocking_later_turns(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    corrupt = await _create_delivery(
        store,
        turn_id="turn-corrupt-envelope",
        created_at_ms=100,
    )
    valid = await _create_delivery(
        store,
        turn_id="turn-after-corrupt-envelope",
        created_at_ms=200,
    )
    with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as conn:
        conn.execute(
            """
            UPDATE chat_user_turn_delivery
            SET runtime_envelope_json = '{invalid'
            WHERE turn_id = ?
            """,
            (corrupt.turn_id,),
        )
        conn.commit()

    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    read_service = _read_service(runtime_paths_with_schema.chat_db_path)
    await queue.start()
    try:
        stats = await _recovery_service(
            store=store,
            read_service=read_service,
            projector=_RecordingProjector(),
            queue=queue,
            page_size=1,
        ).recover_startup()

        corrupt_delivery = await store.get_user_turn_delivery(
            turn_id=corrupt.turn_id
        )
        valid_delivery = await store.get_user_turn_delivery(turn_id=valid.turn_id)
        corrupt_turn = await store.get_turn(corrupt.turn_id)
        corrupt_final = await store.get_latest_message_for_turn(
            corrupt.turn_id,
            message_kind="assistant_final",
        )
        assert stats.found == 2
        assert stats.quarantined == 1
        assert stats.scheduled == 1
        assert corrupt_delivery is not None
        assert corrupt_delivery.delivery_state == "terminal"
        assert corrupt_turn is not None
        assert corrupt_turn.status == "failed"
        assert corrupt_final is not None
        assert corrupt_final.is_visible is True
        assert "重新发送" in str(corrupt_final.content_text)
        assert valid_delivery is not None
        assert valid_delivery.delivery_attempt_no == 1
        assert valid_delivery.delivery_state == CHAT_DELIVERY_STATE_QUEUED
    finally:
        read_service.close()
        await queue.stop()


@pytest.mark.asyncio
async def test_periodic_retry_only_schedules_ready_attempts(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    ready_record = await _create_delivery(
        store,
        turn_id="turn-periodic-ready",
        created_at_ms=100,
    )
    queued_record = await _create_delivery(
        store,
        turn_id="turn-periodic-queued",
        created_at_ms=200,
    )
    admitted_record = await _create_delivery(
        store,
        turn_id="turn-periodic-admitted",
        created_at_ms=300,
    )
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    scheduler = ChatUserTurnDeliveryScheduler(
        chat_store=store,
        runtime_command_queue=queue,
    )
    read_service = _read_service(runtime_paths_with_schema.chat_db_path)
    projector = _RecordingProjector()
    await queue.start()
    try:
        queued_before = await scheduler.schedule_record(queued_record)
        admitted_before = await scheduler.schedule_record(admitted_record)
        assert admitted_before.command_id is not None
        assert await store.mark_user_turn_delivery_admitted(
            turn_id=admitted_record.turn_id,
            delivery_attempt_no=0,
            command_id=admitted_before.command_id,
            updated_at_ms=350,
        )

        stats = await _recovery_service(
            store=store,
            read_service=read_service,
            projector=projector,
            queue=queue,
            page_size=1,
        ).retry_ready()

        ready_current = await store.get_user_turn_delivery(
            turn_id=ready_record.turn_id
        )
        queued_current = await store.get_user_turn_delivery(
            turn_id=queued_record.turn_id
        )
        admitted_current = await store.get_user_turn_delivery(
            turn_id=admitted_record.turn_id
        )
        assert stats.found == 1
        assert stats.scheduled == 1
        assert ready_current is not None
        assert ready_current.delivery_attempt_no == 0
        assert ready_current.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert queued_current is not None
        assert queued_current.delivery_attempt_no == 0
        assert queued_current.delivery_state == CHAT_DELIVERY_STATE_QUEUED
        assert queued_current.current_command_id == queued_before.command_id
        assert admitted_current is not None
        assert admitted_current.delivery_attempt_no == 0
        assert admitted_current.delivery_state == CHAT_DELIVERY_STATE_ADMITTED
        assert admitted_current.current_command_id == admitted_before.command_id
    finally:
        read_service.close()
        await queue.stop()
