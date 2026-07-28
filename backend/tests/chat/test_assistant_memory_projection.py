from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import sqlite3
import time
from types import SimpleNamespace

import pytest

from magi.chat import (
    ChatReadService,
    ChatMessageRecord,
    ChatSessionRecord,
    ChatStore,
    ChatTurnRecord,
)
from magi.chat.assistant_memory_projection import (
    ChatAssistantMemoryProjectionService,
)
from magi.chat.storage import assistant_memory_outbox


class _FakeL1:
    def __init__(self) -> None:
        self.message_ids: set[str] = set()

    async def find_event_id_by_idempotency(
        self,
        *,
        source: str,
        event_type: str,
        idempotency_key: str,
    ) -> str | None:
        assert source == "chat"
        assert event_type == "AIResponse"
        return (
            f"event:{idempotency_key}"
            if idempotency_key in self.message_ids
            else None
        )


class _FakeMemory:
    def __init__(self, l1: _FakeL1 | None) -> None:
        self.l1 = l1
        self.guard_entries = 0

    @asynccontextmanager
    async def memory_operation_guard(self):
        self.guard_entries += 1
        yield


class _FakeProjector:
    def __init__(
        self,
        *,
        l1: _FakeL1 | None,
        confirm: bool = True,
        failure: Exception | None = None,
    ) -> None:
        self._l1 = l1
        self._confirm = confirm
        self._failure = failure
        self.calls: list[dict[str, object]] = []

    async def project_assistant_message(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        if self._failure is not None:
            raise self._failure
        if self._confirm and self._l1 is not None:
            self._l1.message_ids.add(str(kwargs["message_id"]))
        return True


async def _create_unmanaged_projection(
    store: ChatStore,
    *,
    message_id: str = "assistant-1",
    session_id: str = "session-1",
    turn_id: str = "turn-1",
    content: str = "A durable answer",
    created_at_ms: int = 100,
) -> ChatMessageRecord:
    await store.upsert_session(
        ChatSessionRecord(
            session_id=session_id,
            user_id="user-1",
            title="",
            title_overridden=False,
            summary="",
            created_at_ms=created_at_ms,
            updated_at_ms=created_at_ms,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )
    await store.upsert_turn(
        ChatTurnRecord(
            turn_id=turn_id,
            session_id=session_id,
            user_id="user-1",
            trace_id=None,
            orchestration_id=None,
            status="running",
            response_mode="final_only",
            execution_mode=None,
            ux_plan_json="{}",
            created_at_ms=created_at_ms,
            updated_at_ms=created_at_ms,
            completed_at_ms=None,
            error_text=None,
        )
    )
    message = ChatMessageRecord(
        message_id=message_id,
        session_id=session_id,
        turn_id=turn_id,
        user_id="user-1",
        role="assistant",
        message_kind="assistant_final",
        content_text=content,
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=created_at_ms,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    committed = await store.commit_unmanaged_assistant_outcome(
        turn_id=turn_id,
        messages=[message],
        attachment_payloads_by_message_id={},
        trace_id=None,
        orchestration_id=None,
        execution_mode=None,
        ux_plan={},
        response_mode="final_only",
        started_at_ms=created_at_ms,
        completed_at_ms=created_at_ms + 1,
        run_id=None,
        run_revision=0,
        run_disposition=None,
    )
    assert committed is not None
    return committed[0]


@pytest.mark.asyncio
async def test_managed_outcome_atomically_commits_transcript_and_outbox(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    created = await store.create_user_turn_once(
        session_id="session-managed",
        user_id="user-1",
        turn_id="turn-managed",
        message_text="hello",
        created_at_ms=100,
        runtime_envelope={"message": "hello"},
        request_fingerprint="fingerprint",
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-managed",
        delivery_attempt_no=created.delivery_attempt_no,
        command_id=41,
        updated_at_ms=110,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-managed",
        delivery_attempt_no=created.delivery_attempt_no,
        command_id=41,
        updated_at_ms=120,
    )
    message = ChatMessageRecord(
        message_id="assistant-managed",
        session_id="session-managed",
        turn_id="turn-managed",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_final",
        content_text="answer",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=130,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    committed = await store.commit_user_turn_assistant_outcome(
        turn_id="turn-managed",
        delivery_attempt_no=created.delivery_attempt_no,
        command_id=41,
        messages=[message],
        attachment_payloads_by_message_id={},
        trace_id="trace-1",
        orchestration_id=None,
        execution_mode="direct_llm",
        ux_plan={},
        response_mode="final_only",
        started_at_ms=100,
        completed_at_ms=130,
        run_id=None,
        run_revision=0,
        run_disposition=None,
    )

    assert committed is not None
    assert [item.message_id for item in committed] == ["assistant-managed"]
    projection = await store.get_assistant_memory_projection(
        "assistant-managed"
    )
    assert projection is not None
    assert projection.content == "answer"
    delivery = await store.get_user_turn_delivery(turn_id="turn-managed")
    assert delivery is not None
    assert delivery.delivery_state == "terminal"


@pytest.mark.asyncio
async def test_segmented_outcome_derives_one_canonical_projection_from_transcript(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.upsert_session(
        ChatSessionRecord(
            session_id="session-rhythm",
            user_id="user-1",
            title="",
            title_overridden=False,
            summary="",
            created_at_ms=100,
            updated_at_ms=100,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )
    await store.upsert_turn(
        ChatTurnRecord(
            turn_id="turn-rhythm",
            session_id="session-rhythm",
            user_id="user-1",
            trace_id=None,
            orchestration_id=None,
            status="running",
            response_mode="final_only",
            execution_mode=None,
            ux_plan_json="{}",
            created_at_ms=100,
            updated_at_ms=100,
            completed_at_ms=None,
            error_text=None,
        )
    )
    first = ChatMessageRecord(
        message_id="assistant-rhythm-1",
        session_id="session-rhythm",
        turn_id="turn-rhythm",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_rhythm_segment",
        content_text="first part",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=120,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    second = ChatMessageRecord(
        message_id="assistant-rhythm-2",
        session_id="session-rhythm",
        turn_id="turn-rhythm",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_rhythm_segment",
        content_text="second part",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=121,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    committed = await store.commit_unmanaged_assistant_outcome(
        turn_id="turn-rhythm",
        messages=[first, second],
        attachment_payloads_by_message_id={},
        trace_id=None,
        orchestration_id=None,
        execution_mode=None,
        ux_plan={},
        response_mode="multi_message",
        started_at_ms=100,
        completed_at_ms=121,
        run_id=None,
        run_revision=0,
        run_disposition=None,
    )

    assert committed is not None
    projection = await store.get_assistant_memory_projection(
        "assistant-rhythm-1"
    )
    assert projection is not None
    assert projection.content == "first part\nsecond part"
    assert await store.get_assistant_memory_projection("assistant-rhythm-2") is None
    turn = await store.get_turn("turn-rhythm")
    assert turn is not None
    assert turn.status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_message",
    (
        {"is_final": False},
        {"is_visible": False},
    ),
)
async def test_assistant_outcome_rejects_nonfinal_or_hidden_projection_rows(
    runtime_paths_with_schema,
    invalid_message: dict[str, bool],
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.upsert_session(
        ChatSessionRecord(
            session_id="session-invalid-outcome",
            user_id="user-1",
            title="",
            title_overridden=False,
            summary="",
            created_at_ms=100,
            updated_at_ms=100,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )
    await store.upsert_turn(
        ChatTurnRecord(
            turn_id="turn-invalid-outcome",
            session_id="session-invalid-outcome",
            user_id="user-1",
            trace_id=None,
            orchestration_id=None,
            status="running",
            response_mode="final_only",
            execution_mode=None,
            ux_plan_json="{}",
            created_at_ms=100,
            updated_at_ms=100,
            completed_at_ms=None,
            error_text=None,
        )
    )
    valid_message = ChatMessageRecord(
        message_id="assistant-invalid-outcome",
        session_id="session-invalid-outcome",
        turn_id="turn-invalid-outcome",
        user_id="user-1",
        role="assistant",
        message_kind="assistant_final",
        content_text="must not project",
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=110,
        sequence_no=0,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )

    with pytest.raises(
        ValueError,
        match="must be visible final rows",
    ):
        await store.commit_unmanaged_assistant_outcome(
            turn_id="turn-invalid-outcome",
            messages=[replace(valid_message, **invalid_message)],
            attachment_payloads_by_message_id={},
            trace_id=None,
            orchestration_id=None,
            execution_mode=None,
            ux_plan={},
            response_mode="final_only",
            started_at_ms=100,
            completed_at_ms=120,
            run_id=None,
            run_revision=0,
            run_disposition=None,
        )

    turn = await store.get_turn("turn-invalid-outcome")
    assert turn is not None and turn.status == "running"
    assert await store.get_assistant_memory_projection(
        "assistant-invalid-outcome"
    ) is None


@pytest.mark.asyncio
async def test_assistant_outcome_allows_explicit_no_message_completion(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.upsert_session(
        ChatSessionRecord(
            session_id="session-no-message",
            user_id="user-1",
            title="",
            title_overridden=False,
            summary="",
            created_at_ms=100,
            updated_at_ms=100,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )
    await store.upsert_turn(
        ChatTurnRecord(
            turn_id="turn-no-message",
            session_id="session-no-message",
            user_id="user-1",
            trace_id=None,
            orchestration_id=None,
            status="running",
            response_mode="final_only",
            execution_mode=None,
            ux_plan_json="{}",
            created_at_ms=100,
            updated_at_ms=100,
            completed_at_ms=None,
            error_text=None,
        )
    )

    committed = await store.commit_unmanaged_assistant_outcome(
        turn_id="turn-no-message",
        messages=[],
        attachment_payloads_by_message_id={},
        trace_id=None,
        orchestration_id=None,
        execution_mode=None,
        ux_plan={},
        response_mode="final_only",
        started_at_ms=100,
        completed_at_ms=120,
        run_id=None,
        run_revision=0,
        run_disposition=None,
    )

    assert committed == []
    turn = await store.get_turn("turn-no-message")
    assert turn is not None and turn.status == "completed"


@pytest.mark.asyncio
async def test_outbox_lease_expiry_and_completion_are_owner_scoped(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)

    first = await store.claim_assistant_memory_projections(
        limit=10,
        lease_seconds=1.0,
        now_ms=1_000,
    )
    assert len(first) == 1
    assert first[0].attempt_count == 1
    assert await store.claim_assistant_memory_projections(
        limit=10,
        lease_seconds=1.0,
        now_ms=1_999,
    ) == []

    recovered = await store.claim_assistant_memory_projections(
        limit=10,
        lease_seconds=1.0,
        now_ms=2_001,
    )
    assert len(recovered) == 1
    assert recovered[0].attempt_count == 2
    assert recovered[0].lease_token != first[0].lease_token
    assert not await store.complete_assistant_memory_projection(
        canonical_message_id="assistant-1",
        lease_token=first[0].lease_token,
    )
    assert await store.complete_assistant_memory_projection(
        canonical_message_id="assistant-1",
        lease_token=recovered[0].lease_token,
    )
    assert await store.count_assistant_memory_projections() == 0


@pytest.mark.asyncio
async def test_session_surface_delete_removes_pending_projection_content(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)
    read_service = ChatReadService(runtime_paths=runtime_paths_with_schema)
    try:
        read_service.delete_session("user-1", "session-1")
        assert await store.count_assistant_memory_projections() == 0
    finally:
        read_service.close()


@pytest.mark.asyncio
async def test_full_chat_clear_removes_pending_and_claimed_projection_content(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(
        store,
        message_id="assistant-pending",
        session_id="session-pending",
        turn_id="turn-pending",
        created_at_ms=100,
    )
    await _create_unmanaged_projection(
        store,
        message_id="assistant-claimed",
        session_id="session-claimed",
        turn_id="turn-claimed",
        created_at_ms=200,
    )
    claimed = await store.claim_assistant_memory_projections(
        limit=1,
        lease_seconds=30,
        now_ms=1_000,
    )
    assert len(claimed) == 1

    read_service = ChatReadService(runtime_paths=runtime_paths_with_schema)
    try:
        assert read_service.clear_all_sessions() == 2
        assert await store.count_assistant_memory_projections() == 0
    finally:
        read_service.close()


@pytest.mark.asyncio
async def test_projection_worker_confirms_l1_before_removing_content(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)
    l1 = _FakeL1()
    projector = _FakeProjector(l1=l1)
    memory = _FakeMemory(l1)
    service = ChatAssistantMemoryProjectionService(
        outbox=store,
        projector=projector,  # type: ignore[arg-type]
        unified_memory=memory,
        confirmation_timeout_seconds=0.05,
    )

    stats = await service.process_ready_once()

    assert stats == {
        "claimed": 1,
        "confirmed": 1,
        "disabled": 0,
        "retried": 0,
        "cancelled": 0,
    }
    assert l1.message_ids == {"assistant-1"}
    assert len(projector.calls) == 1
    assert await store.count_assistant_memory_projections() == 0
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT content_text FROM chat_assistant_memory_outbox"
        ).fetchall() == []


@pytest.mark.asyncio
async def test_startup_recovery_drains_pending_projection(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)
    l1 = _FakeL1()
    service = ChatAssistantMemoryProjectionService(
        outbox=store,
        projector=_FakeProjector(l1=l1),  # type: ignore[arg-type]
        unified_memory=_FakeMemory(l1),
        retry_interval_seconds=0.05,
        confirmation_timeout_seconds=0.05,
    )
    store.set_assistant_memory_outbox_waker(service.wake)
    await service.start()
    try:
        deadline = time.monotonic() + 1.0
        while await store.count_assistant_memory_projections():
            if time.monotonic() >= deadline:
                raise AssertionError("startup recovery did not drain the outbox")
            await asyncio.sleep(0.01)
    finally:
        store.set_assistant_memory_outbox_waker(None)
        await service.stop()

    assert l1.message_ids == {"assistant-1"}


@pytest.mark.asyncio
async def test_crash_after_publish_replays_by_confirmation_without_republish(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)
    claimed = await store.claim_assistant_memory_projections(
        limit=1,
        lease_seconds=1.0,
        now_ms=0,
    )
    assert len(claimed) == 1
    l1 = _FakeL1()
    l1.message_ids.add("assistant-1")
    projector = _FakeProjector(l1=l1)
    service = ChatAssistantMemoryProjectionService(
        outbox=store,
        projector=projector,  # type: ignore[arg-type]
        unified_memory=_FakeMemory(l1),
    )

    stats = await service.process_ready_once()

    assert stats["confirmed"] == 1
    assert projector.calls == []
    assert await store.count_assistant_memory_projections() == 0


@pytest.mark.asyncio
async def test_projection_timeout_keeps_content_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)
    monkeypatch.setattr(
        assistant_memory_outbox,
        "time",
        SimpleNamespace(time=lambda: 1.0),
    )
    l1 = _FakeL1()
    service = ChatAssistantMemoryProjectionService(
        outbox=store,
        projector=_FakeProjector(l1=l1, confirm=False),  # type: ignore[arg-type]
        unified_memory=_FakeMemory(l1),
        confirmation_timeout_seconds=0.01,
        confirmation_poll_seconds=0.002,
        retry_base_seconds=0.1,
        retry_max_seconds=1.0,
    )

    first = await service.process_ready_once()
    immediate = await service.process_ready_once()

    assert first["retried"] == 1
    assert immediate["claimed"] == 0
    assert await store.count_assistant_memory_projections() == 1
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            """
            SELECT state, attempt_count, next_attempt_at_ms, last_error,
                   content_text, lease_token, lease_expires_at_ms
            FROM chat_assistant_memory_outbox
            WHERE canonical_message_id = 'assistant-1'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] == 1
    assert row[2] == 1_100
    assert "TimeoutError" in str(row[3])
    assert row[4] == "A durable answer"
    assert row[5] is None
    assert row[6] is None


@pytest.mark.asyncio
async def test_l1_disabled_completes_outbox_without_publishing(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)
    projector = _FakeProjector(l1=None)
    service = ChatAssistantMemoryProjectionService(
        outbox=store,
        projector=projector,  # type: ignore[arg-type]
        unified_memory=_FakeMemory(None),
    )

    stats = await service.process_ready_once()

    assert stats["disabled"] == 1
    assert projector.calls == []
    assert await store.count_assistant_memory_projections() == 0


@pytest.mark.asyncio
async def test_unmanaged_outcome_does_not_publish_before_outbox_worker(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await _create_unmanaged_projection(store)
    l1 = _FakeL1()
    projector = _FakeProjector(l1=l1)

    assert projector.calls == []
    assert l1.message_ids == set()
    assert await store.count_assistant_memory_projections() == 1

    service = ChatAssistantMemoryProjectionService(
        outbox=store,
        projector=projector,  # type: ignore[arg-type]
        unified_memory=_FakeMemory(l1),
    )
    await service.process_ready_once()
    assert len(projector.calls) == 1
