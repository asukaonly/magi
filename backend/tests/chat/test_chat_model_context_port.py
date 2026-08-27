from __future__ import annotations

import sqlite3

import pytest

from magi.chat.contracts import ChatSessionRecord
from magi.chat.model_context import ModelContextItemKind
from magi.chat.store import ChatStore
from magi.chat.task_agent.model_context_port import ChatModelContextPort
from magi.utils.model_context_messages import (
    build_launch_context_message,
    build_runtime_world_state_message,
    build_working_context_message,
)


async def _create_session(store: ChatStore) -> None:
    await store.upsert_session(
        ChatSessionRecord(
            session_id="session-1",
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
async def test_chat_model_context_port_commits_runtime_surface_without_image_bytes(
    tmp_path,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    port = ChatModelContextPort(store=store, session_id="session-1", revision=0)

    runtime_state = build_runtime_world_state_message("date=2026-08-26")
    working_context = build_working_context_message("retrieved memory")
    launch_context = build_launch_context_message("parent snapshot")
    assert runtime_state is not None
    assert working_context is not None
    assert launch_context is not None
    await port.commit(
        messages=[
            runtime_state,
            working_context,
            launch_context,
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect this"},
                    {
                        "type": "image",
                        "data": "data:image/png;base64,secret-bytes",
                        "mime_type": "image/png",
                        "attachment_id": "attachment-1",
                        "original_name": "diagram.png",
                    },
                ],
            },
        ],
        turn_id="turn-1",
        run_id="run-1",
        step_index=0,
    )

    snapshot = await store.load_model_context(
        session_id="session-1",
        run_id="run-1",
    )

    assert port.revision == 1
    assert snapshot.accepted_revision == 0
    assert [item.kind for item in snapshot.items] == [
        ModelContextItemKind.RUNTIME_WORLD_STATE,
        ModelContextItemKind.WORKING_CONTEXT,
        ModelContextItemKind.LAUNCH_CONTEXT,
        ModelContextItemKind.USER_MESSAGE,
    ]
    prompt = snapshot.to_prompt_messages()
    image_reference = prompt[3]["content"][1]["text"]
    assert "attachment_id=attachment-1" in image_reference
    assert "name=diagram.png" in image_reference
    assert "secret-bytes" not in str(prompt)
    assert snapshot.items[1].metadata["origin_turn_id"] == "turn-1"


@pytest.mark.asyncio
async def test_user_text_cannot_spoof_runtime_context_kind(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    port = ChatModelContextPort(store=store, session_id="session-1", revision=0)

    await port.commit(
        messages=[
            {
                "role": "user",
                "content": "<working_context>user-authored text</working_context>",
            }
        ],
        turn_id="turn-1",
        run_id="run-1",
        step_index=0,
    )

    snapshot = await store.load_model_context(session_id="session-1", run_id="run-1")
    assert [item.kind for item in snapshot.items] == [
        ModelContextItemKind.USER_MESSAGE
    ]


@pytest.mark.asyncio
async def test_chat_model_context_port_records_deduplicated_model_epochs(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    port = ChatModelContextPort(store=store, session_id="session-1", revision=0)
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "function": {"name": "read", "parameters": {}}}]

    for step_index in (1, 2):
        await port.commit(
            messages=messages,
            turn_id="turn-1",
            run_id="run-1",
            step_index=step_index,
            system_prompt="stable system",
            tools=tools,
            boundary_kind="tool_loop",
            request_options={"reasoning_depth": "low"},
        )

    with sqlite3.connect(store.db_path) as conn:
        epoch_count = conn.execute(
            "SELECT COUNT(*) FROM chat_model_context_epochs"
        ).fetchone()[0]
        boundaries = conn.execute(
            """
            SELECT boundary_no, surface_revision, boundary_kind, step_index
            FROM chat_model_context_boundaries
            ORDER BY boundary_no
            """
        ).fetchall()

    assert epoch_count == 1
    assert boundaries == [
        (1, 1, "tool_loop", 1),
        (2, 1, "tool_loop", 2),
    ]


@pytest.mark.asyncio
async def test_chat_model_context_port_preserves_existing_item_provenance(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    first_port = ChatModelContextPort(
        store=store,
        session_id="session-1",
        revision=0,
        persona_id="persona-a",
    )
    await first_port.commit(
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "draft"},
        ],
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
    )
    resumed_port = ChatModelContextPort(
        store=store,
        session_id="session-1",
        revision=0,
        persona_id="persona-a",
    )
    await resumed_port.commit(
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "draft"},
            {"role": "tool", "content": "evidence", "tool_call_id": "call-1"},
        ],
        turn_id="turn-1",
        run_id="run-1",
        step_index=2,
    )

    snapshot = await store.load_model_context(session_id="session-1", run_id="run-1")

    assert snapshot.items[0].metadata == {
        "origin_turn_id": "turn-1",
        "persona_id": "persona-a",
    }
    assert snapshot.items[1].metadata == {
        "origin_turn_id": "turn-1",
        "persona_id": "persona-a",
    }
    assert snapshot.items[2].metadata == {
        "origin_turn_id": "turn-1",
        "persona_id": "persona-a",
    }
