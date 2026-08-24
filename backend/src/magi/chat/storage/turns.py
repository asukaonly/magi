"""Turn row persistence for the chat store."""

from __future__ import annotations

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..contracts import ChatTurnRecord


TURN_SELECT_COLUMNS = """
    turn_id, session_id, user_id, trace_id, status,
    response_mode, execution_mode, ux_plan_json, created_at_ms,
    updated_at_ms, completed_at_ms, error_text, run_id,
    run_revision, run_disposition, response_anchor_turn_id,
    superseded_by_turn_id, supersession_reason
"""


class ChatTurnPersistenceMixin:
    """Persist chat turn records and supersession lookups."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[object, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    async def upsert_turn(self, record: ChatTurnRecord) -> None:
        """Insert or update one chat turn row."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute(
                """
                INSERT INTO chat_turns (
                    turn_id,
                    session_id,
                    user_id,
                    trace_id,
                    status,
                    response_mode,
                    execution_mode,
                    ux_plan_json,
                    created_at_ms,
                    updated_at_ms,
                    completed_at_ms,
                    error_text,
                    run_id,
                    run_revision,
                    run_disposition,
                    response_anchor_turn_id,
                    superseded_by_turn_id,
                    supersession_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(turn_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    user_id = excluded.user_id,
                    trace_id = excluded.trace_id,
                    status = excluded.status,
                    response_mode = excluded.response_mode,
                    execution_mode = excluded.execution_mode,
                    ux_plan_json = excluded.ux_plan_json,
                    updated_at_ms = excluded.updated_at_ms,
                    completed_at_ms = excluded.completed_at_ms,
                    error_text = excluded.error_text,
                    run_id = excluded.run_id,
                    run_revision = excluded.run_revision,
                    run_disposition = excluded.run_disposition,
                    response_anchor_turn_id = excluded.response_anchor_turn_id,
                    superseded_by_turn_id = excluded.superseded_by_turn_id,
                    supersession_reason = excluded.supersession_reason
                """,
                (
                    record.turn_id,
                    record.session_id,
                    record.user_id,
                    record.trace_id,
                    record.status,
                    record.response_mode,
                    record.execution_mode,
                    record.ux_plan_json,
                    record.created_at_ms,
                    record.updated_at_ms,
                    record.completed_at_ms,
                    record.error_text,
                    record.run_id,
                    record.run_revision,
                    record.run_disposition,
                    record.response_anchor_turn_id,
                    record.superseded_by_turn_id,
                    record.supersession_reason,
                ),
            )
            await db.commit()

    async def get_turn(self, turn_id: str) -> ChatTurnRecord | None:
        """Return one chat turn by ID."""
        row = await self._fetchone(
            f"""
            SELECT {TURN_SELECT_COLUMNS}
            FROM chat_turns
            WHERE turn_id = ?
            """,
            (turn_id,),
        )
        if row is None:
            return None
        return self._row_to_turn(row)

    async def get_latest_superseded_turn(self, *, anchor_turn_id: str) -> ChatTurnRecord | None:
        """Return the most recent turn superseded by one anchor turn."""
        row = await self._fetchone(
            f"""
            SELECT {TURN_SELECT_COLUMNS}
            FROM chat_turns
            WHERE superseded_by_turn_id = ?
            ORDER BY updated_at_ms DESC, created_at_ms DESC
            LIMIT 1
            """,
            (anchor_turn_id,),
        )
        if row is None:
            return None
        return self._row_to_turn(row)

    @staticmethod
    def _row_to_turn(row: aiosqlite.Row) -> ChatTurnRecord:
        return ChatTurnRecord(
            turn_id=str(row["turn_id"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            trace_id=row["trace_id"],
            status=str(row["status"]),
            response_mode=str(row["response_mode"]),
            execution_mode=row["execution_mode"],
            ux_plan_json=str(row["ux_plan_json"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
            completed_at_ms=int(row["completed_at_ms"]) if row["completed_at_ms"] is not None else None,
            error_text=row["error_text"],
            run_id=row["run_id"],
            run_revision=int(row["run_revision"] or 0),
            run_disposition=row["run_disposition"],
            response_anchor_turn_id=row["response_anchor_turn_id"],
            superseded_by_turn_id=row["superseded_by_turn_id"],
            supersession_reason=row["supersession_reason"],
        )
