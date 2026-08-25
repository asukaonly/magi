from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from magi.chat.model_context import ModelContextItem
from magi.chat.read_service import ChatReadService
from magi.chat.store import ChatStore
from magi.utils.runtime import RuntimePaths


_MODEL_CONTEXT_TABLES = (
    "chat_model_context_boundaries",
    "chat_model_context_epochs",
    "chat_model_context_surface_nodes",
    "chat_model_context_events",
    "chat_model_context_heads",
)


async def _seed_model_context(store: ChatStore, *, session_id: str) -> str:
    message = await store.create_user_turn(
        session_id=session_id,
        user_id="user-1",
        turn_id="turn-1",
        message_text="private prompt",
        created_at_ms=1,
    )
    snapshot = await store.append_model_context(
        session_id=session_id,
        items=(
            ModelContextItem.from_prompt_message(
                {"role": "user", "content": "private prompt"},
                source="user",
            ),
        ),
        expected_revision=0,
        turn_id="turn-1",
        run_id="run-1",
        step_index=0,
    )
    await store.record_model_context_boundary(
        session_id=session_id,
        surface_revision=snapshot.revision,
        system_prompt="private system prompt",
        tools=[{"type": "function", "function": {"name": "read"}}],
        boundary_kind="tool_loop",
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
    )
    return message.message_id


def _assert_model_context_removed(db_path: str, *, session_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        for table in _MODEL_CONTEXT_TABLES:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            assert count == 0, table


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["message", "history", "session", "global"])
async def test_chat_deletion_physically_removes_model_context(
    tmp_path,
    mutation: str,
) -> None:
    db_path = str(tmp_path / "chat.db")
    store = ChatStore(db_path=db_path)
    message_id = await _seed_model_context(store, session_id="session-1")
    service = ChatReadService(runtime_paths=RuntimePaths(tmp_path / "runtime"))
    service._chat_db_path = Path(store.db_path)
    service._runtime_trace_db_path = tmp_path / "missing-runtime-trace.db"

    if mutation == "message":
        assert service.forget_message_artifacts(
            "user-1",
            "session-1",
            message_id,
        )
    elif mutation == "history":
        service.clear_conversation_history("user-1", "session-1")
    elif mutation == "session":
        service.delete_session("user-1", "session-1")
    else:
        assert service.clear_all_sessions() == 1

    _assert_model_context_removed(db_path, session_id="session-1")
