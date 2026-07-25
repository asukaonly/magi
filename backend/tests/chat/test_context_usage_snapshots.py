from __future__ import annotations

import sqlite3

import pytest

from magi.chat import (
    ChatMessageRecord,
    ChatReadService,
    ChatSessionRecord,
    ChatStore,
    ChatTurnRecord,
)


async def _commit_answer(
    store: ChatStore,
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    completed_at_ms: int,
    used_tokens: int,
) -> None:
    await store.upsert_turn(
        ChatTurnRecord(
            turn_id=turn_id,
            session_id=session_id,
            user_id="user-1",
            trace_id=None,
            orchestration_id=None,
            status="running",
            response_mode="final_only",
            execution_mode="direct_llm",
            ux_plan_json="{}",
            created_at_ms=completed_at_ms - 10,
            updated_at_ms=completed_at_ms - 10,
            completed_at_ms=None,
            error_text=None,
        )
    )
    committed = await store.commit_unmanaged_assistant_outcome(
        turn_id=turn_id,
        messages=[
            ChatMessageRecord(
                message_id=message_id,
                session_id=session_id,
                turn_id=turn_id,
                user_id="user-1",
                role="assistant",
                message_kind="assistant_final",
                content_text=f"answer {turn_id}",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=completed_at_ms,
                sequence_no=0,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        ],
        attachment_payloads_by_message_id={},
        trace_id=None,
        orchestration_id=None,
        execution_mode="direct_llm",
        ux_plan={},
        response_mode="final_only",
        started_at_ms=completed_at_ms - 10,
        completed_at_ms=completed_at_ms,
        context_usage={
            "used_tokens": used_tokens,
            "context_window": 1_000_000,
            "input_capacity": 983_616,
            "compaction_threshold": 491_808,
            "measurement": "actual",
            "model_provider": "provider-1",
            "model_id": "model-1",
        },
    )
    assert committed is not None


@pytest.mark.asyncio
async def test_latest_context_usage_survives_restart_and_follows_visible_answer(
    runtime_paths_with_schema,
) -> None:
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.upsert_session(
        ChatSessionRecord(
            session_id="session-1",
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
    await _commit_answer(
        store,
        session_id="session-1",
        turn_id="turn-1",
        message_id="message-1",
        completed_at_ms=200,
        used_tokens=2_633,
    )
    await _commit_answer(
        store,
        session_id="session-1",
        turn_id="turn-2",
        message_id="message-2",
        completed_at_ms=300,
        used_tokens=6_064,
    )

    reader = ChatReadService(runtime_paths=runtime_paths_with_schema)
    latest = await reader.aget_latest_context_usage("user-1", "session-1")
    assert latest is not None
    assert latest.turn_id == "turn-2"
    assert latest.used_tokens == 6_064
    assert latest.context_window == 1_000_000
    assert latest.measurement == "actual"

    with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as conn:
        conn.execute(
            "UPDATE chat_messages SET is_visible = 0 WHERE message_id = ?",
            ("message-2",),
        )
        conn.commit()
    reader.close()

    restarted_reader = ChatReadService(runtime_paths=runtime_paths_with_schema)
    fallback = await restarted_reader.aget_latest_context_usage(
        "user-1",
        "session-1",
    )
    assert fallback is not None
    assert fallback.turn_id == "turn-1"
    assert fallback.used_tokens == 2_633
    restarted_reader.close()
