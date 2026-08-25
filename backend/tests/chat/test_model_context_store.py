from __future__ import annotations

import sqlite3

import pytest

from magi.chat.model_context import (
    ModelContextItem,
    ModelContextItemKind,
    ModelContextRevisionConflictError,
    ModelContextScope,
)
from magi.chat.store import ChatStore
from magi.chat.contracts import ChatSessionRecord
from magi.chat.contracts import ChatMessageRecord


def _item(
    role: str,
    content: str,
    *,
    kind: ModelContextItemKind | None = None,
    source: str = "test",
) -> ModelContextItem:
    return ModelContextItem.from_prompt_message(
        {"role": role, "content": content},
        source=source,
        kind=kind,
        scope=ModelContextScope.SESSION,
    )


async def _create_session(store: ChatStore, session_id: str = "session-1") -> None:
    await store.upsert_session(
        ChatSessionRecord(
            session_id=session_id,
            user_id="user-1",
            title="Test",
            title_overridden=False,
            summary="",
            created_at_ms=1,
            updated_at_ms=1,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )


@pytest.mark.asyncio
async def test_append_and_load_model_context(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)

    snapshot = await store.append_model_context(
        session_id="session-1",
        items=(
            _item(
                "user",
                "<turn_context>snapshot</turn_context>",
                kind=ModelContextItemKind.TURN_CONTEXT,
            ),
            _item("user", "hello"),
        ),
        expected_revision=0,
        turn_id="turn-1",
        run_id="run-1",
        step_index=0,
    )

    assert snapshot.revision == 1
    assert snapshot.accepted_revision == 1
    assert [item.kind for item in snapshot.items] == [
        ModelContextItemKind.TURN_CONTEXT,
        ModelContextItemKind.USER_MESSAGE,
    ]
    assert snapshot.to_prompt_messages() == [
        {"role": "user", "content": "<turn_context>snapshot</turn_context>"},
        {"role": "user", "content": "hello"},
    ]
    assert {event.turn_id for event in snapshot.events} == {"turn-1"}
    assert {event.run_id for event in snapshot.events} == {"run-1"}


@pytest.mark.asyncio
async def test_sync_appends_suffix_and_replaces_changed_surface(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    first = await store.append_model_context(
        session_id="session-1",
        items=(_item("user", "hello"),),
        expected_revision=0,
    )

    unchanged = await store.sync_model_context_surface(
        session_id="session-1",
        items=first.items,
        expected_revision=first.revision,
        turn_id="turn-1",
        run_id="run-1",
    )
    assert unchanged.revision == 1
    assert unchanged.is_working

    appended = await store.sync_model_context_surface(
        session_id="session-1",
        items=(*first.items, _item("assistant", "hi")),
        expected_revision=first.revision,
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
    )
    assert appended.revision == 2
    assert appended.accepted_revision == 1
    assert [event.operation for event in appended.events] == ["append", "working_append"]

    replacement_item = _item(
        "user",
        "[context compacted]\nsummary",
        kind=ModelContextItemKind.COMPACTION_SUMMARY,
        source="context_compactor",
    )
    replaced = await store.sync_model_context_surface(
        session_id="session-1",
        items=(replacement_item, _item("assistant", "hi")),
        expected_revision=appended.revision,
        turn_id="turn-1",
        run_id="run-1",
        step_index=2,
    )
    assert replaced.revision == 3
    assert [item.kind for item in replaced.items] == [
        ModelContextItemKind.COMPACTION_SUMMARY,
        ModelContextItemKind.ASSISTANT_MESSAGE,
    ]
    assert [event.operation for event in replaced.events] == [
        "working_replace",
        "working_append",
    ]

    accepted = await store.load_model_context(session_id="session-1")
    assert accepted.revision == 1
    working = await store.load_model_context(session_id="session-1", run_id="run-1")
    assert working.revision == 3
    assert working.items == replaced.items

    with sqlite3.connect(store.db_path) as conn:
        event_count = conn.execute(
            "SELECT COUNT(*) FROM chat_model_context_events"
        ).fetchone()[0]
    assert event_count == 3


@pytest.mark.asyncio
async def test_boundary_reconstructs_immutable_model_call(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    initial = await store.append_model_context(
        session_id="session-1",
        items=(_item("user", "hello"),),
        expected_revision=0,
    )
    working, boundary = await store.prepare_model_context_call(
        session_id="session-1",
        items=(*initial.items, _item("assistant", "draft")),
        expected_revision=initial.revision,
        system_prompt="system-v1",
        tools=[{"type": "function", "function": {"name": "read"}}],
        boundary_kind="tool_loop",
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
        request_options={"reasoning_depth": "high"},
    )
    await store.sync_model_context_surface(
        session_id="session-1",
        items=(*working.items, _item("user", "repair")),
        expected_revision=working.revision,
        turn_id="turn-1",
        run_id="run-1",
        step_index=2,
    )

    call = await store.load_model_context_call(boundary_id=boundary.boundary_id)

    assert call.surface.revision == working.revision
    assert call.surface.to_prompt_messages() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "draft"},
    ]
    assert call.epoch.system_prompt == "system-v1"
    assert call.boundary.request_options == {"reasoning_depth": "high"}


@pytest.mark.asyncio
async def test_visible_outcome_atomically_promotes_working_context(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.create_user_turn(
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-1",
        message_text="solve this",
        created_at_ms=10,
        run_id="run-1",
        run_revision=1,
    )
    working = await store.sync_model_context_surface(
        session_id="session-1",
        items=(
            ModelContextItem.from_prompt_message(
                {"role": "user", "content": "solve this"},
                source="user",
                metadata={"origin_turn_id": "turn-1"},
            ),
            ModelContextItem.from_prompt_message(
                {"role": "assistant", "content": "unaccepted draft"},
                source="model",
                metadata={"origin_turn_id": "turn-1", "persona_id": "persona-a"},
            ),
            ModelContextItem.from_prompt_message(
                {"role": "user", "content": "[Runtime validation] retry"},
                source="runtime_control",
                kind=ModelContextItemKind.RUNTIME_CONTROL,
                scope=ModelContextScope.RUN,
                metadata={"origin_turn_id": "turn-1"},
            ),
        ),
        expected_revision=0,
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
    )
    assert working.accepted_revision == 0
    committed = await store.commit_unmanaged_assistant_outcome(
        turn_id="turn-1",
        messages=[
            ChatMessageRecord(
                message_id="assistant-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                role="assistant",
                message_kind="assistant_final",
                content_text="accepted answer",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=20,
                sequence_no=0,
                replaces_message_id=None,
                replaced_by_message_id=None,
                persona_id="persona-a",
            )
        ],
        attachment_payloads_by_message_id={},
        trace_id=None,
        execution_mode="agent",
        ux_plan=None,
        response_mode="final_only",
        started_at_ms=10,
        completed_at_ms=20,
        run_id="run-1",
        run_revision=1,
    )

    assert committed is not None
    accepted = await store.load_model_context(session_id="session-1")
    assert accepted.accepted_revision == accepted.revision
    assert [message["content"] for message in accepted.to_prompt_messages()] == [
        "solve this",
        "[Runtime validation] retry",
        "accepted answer",
    ]
    assert accepted.items[-1].metadata == {
        "origin_turn_id": "turn-1",
        "accepted_outcome": True,
        "persona_id": "persona-a",
    }


@pytest.mark.asyncio
async def test_outcome_failure_rolls_back_model_context_promotion(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.create_user_turn(
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-1",
        message_text="solve this",
        created_at_ms=10,
        run_id="run-1",
        run_revision=1,
    )
    await store.sync_model_context_surface(
        session_id="session-1",
        items=(
            ModelContextItem.from_prompt_message(
                {"role": "user", "content": "solve this"},
                source="user",
                metadata={"origin_turn_id": "turn-1"},
            ),
            ModelContextItem.from_prompt_message(
                {"role": "assistant", "content": "draft"},
                source="model",
                metadata={"origin_turn_id": "turn-1"},
            ),
        ),
        expected_revision=0,
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
    )
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER abort_turn_completion
            BEFORE UPDATE OF status ON chat_turns
            WHEN NEW.turn_id = 'turn-1' AND NEW.status = 'completed'
            BEGIN
                SELECT RAISE(ABORT, 'turn completion blocked');
            END
            """
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="turn completion blocked"):
        await store.commit_unmanaged_assistant_outcome(
            turn_id="turn-1",
            messages=[
                ChatMessageRecord(
                    message_id="assistant-1",
                    session_id="session-1",
                    turn_id="turn-1",
                    user_id="user-1",
                    role="assistant",
                    message_kind="assistant_final",
                    content_text="accepted answer",
                    payload_json="{}",
                    is_final=True,
                    is_visible=True,
                    created_at_ms=20,
                    sequence_no=0,
                    replaces_message_id=None,
                    replaced_by_message_id=None,
                )
            ],
            attachment_payloads_by_message_id={},
            trace_id=None,
            execution_mode="agent",
            ux_plan=None,
            response_mode="final_only",
            started_at_ms=10,
            completed_at_ms=20,
            run_id="run-1",
            run_revision=1,
        )

    accepted = await store.load_model_context(session_id="session-1")
    working = await store.load_model_context(session_id="session-1", run_id="run-1")
    assert accepted.revision == 0
    assert [item.message["content"] for item in working.items] == [
        "solve this",
        "draft",
    ]


@pytest.mark.asyncio
async def test_cancellation_promotes_runtime_outcome_without_draft(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.create_user_turn(
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-1",
        message_text="long task",
        created_at_ms=10,
        run_id="run-1",
        run_revision=1,
    )
    await store.sync_model_context_surface(
        session_id="session-1",
        items=(
            ModelContextItem.from_prompt_message(
                {"role": "user", "content": "long task"},
                source="user",
                metadata={"origin_turn_id": "turn-1"},
            ),
            ModelContextItem.from_prompt_message(
                {"role": "assistant", "content": "partial draft"},
                source="model",
                metadata={"origin_turn_id": "turn-1"},
            ),
        ),
        expected_revision=0,
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
    )

    cancelled = await store.cancel_user_turn_delivery_if_active(
        turn_id="turn-1",
        expected_session_id="session-1",
        expected_user_id="user-1",
        run_id="run-1",
        run_revision=1,
        reason="user_cancel",
        updated_at_ms=20,
    )

    assert cancelled
    accepted = await store.load_model_context(session_id="session-1")
    contents = [str(item.message["content"]) for item in accepted.items]
    assert contents[0] == "long task"
    assert "partial draft" not in contents
    assert contents[-1].startswith("[Runtime outcome]")


@pytest.mark.asyncio
async def test_model_context_revision_conflict_is_rejected(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.append_model_context(
        session_id="session-1",
        items=(_item("user", "hello"),),
        expected_revision=0,
    )

    with pytest.raises(ModelContextRevisionConflictError):
        await store.append_model_context(
            session_id="session-1",
            items=(_item("assistant", "stale"),),
            expected_revision=0,
        )


@pytest.mark.asyncio
async def test_reset_physically_removes_model_context(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.append_model_context(
        session_id="session-1",
        items=(_item("user", "hello"),),
    )

    await store.reset_model_context(session_id="session-1")

    snapshot = await store.load_model_context(session_id="session-1")
    assert snapshot.revision == 0
    assert snapshot.events == ()


@pytest.mark.asyncio
async def test_cleared_session_rejects_late_model_context_write(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "INSERT INTO chat_cleared_session_scopes(session_id, cleared_at_ms) VALUES (?, ?)",
            ("session-1", 10),
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        await store.append_model_context(
            session_id="session-1",
            items=(_item("user", "late"),),
        )
