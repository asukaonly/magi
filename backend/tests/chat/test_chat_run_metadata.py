from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _turn_column_names(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA table_info(chat_turns)").fetchall()
        return {str(row[1]) for row in rows}
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_chat_turn_run_metadata_round_trips(runtime_paths_with_schema) -> None:
    from magi.chat import ChatStore

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.create_user_turn(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            message_text="hello",
            created_at_ms=100,
        )

        turn = await store.get_turn("turn-1")
        assert turn is not None

        await store.upsert_turn(
            type(turn)(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                user_id=turn.user_id,
                trace_id=turn.trace_id,
                status=turn.status,
                response_mode=turn.response_mode,
                execution_mode=turn.execution_mode,
                ux_plan_json=turn.ux_plan_json,
                created_at_ms=turn.created_at_ms,
                updated_at_ms=150,
                completed_at_ms=200,
                error_text=turn.error_text,
                run_id="run-1",
                run_revision=2,
                run_disposition="message",
                response_anchor_turn_id="turn-2",
                superseded_by_turn_id="turn-2",
                supersession_reason="merged",
            )
        )

        updated_turn = await store.get_turn("turn-1")

        assert updated_turn is not None
        assert updated_turn.run_id == "run-1"
        assert updated_turn.run_revision == 2
        assert updated_turn.run_disposition == "message"
        assert updated_turn.response_anchor_turn_id == "turn-2"
        assert updated_turn.superseded_by_turn_id == "turn-2"
        assert updated_turn.supersession_reason == "merged"
    finally:
        await store.shutdown()
