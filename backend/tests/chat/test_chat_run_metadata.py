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
async def test_chat_turn_run_metadata_round_trips(tmp_path: Path) -> None:
    from magi.chat import ChatStore

    db_path = tmp_path / "chat.db"
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
                orchestration_id=turn.orchestration_id,
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
                run_disposition="augment",
            )
        )

        updated_turn = await store.get_turn("turn-1")

        assert updated_turn is not None
        assert updated_turn.run_id == "run-1"
        assert updated_turn.run_revision == 2
        assert updated_turn.run_disposition == "augment"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_upgrades_existing_turn_schema_with_run_metadata(tmp_path: Path) -> None:
    from magi.chat import ChatStore

    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE chat_turns (
                turn_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                trace_id TEXT,
                orchestration_id TEXT,
                status TEXT NOT NULL,
                response_mode TEXT NOT NULL,
                execution_mode TEXT,
                ux_plan_json TEXT NOT NULL DEFAULT '{}',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                completed_at_ms INTEGER,
                error_text TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        columns = _turn_column_names(db_path)

        assert "run_id" in columns
        assert "run_revision" in columns
        assert "run_disposition" in columns
    finally:
        await store.shutdown()
