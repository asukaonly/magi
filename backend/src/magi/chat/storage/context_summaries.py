"""Persistent named boundary summaries for chat sessions."""

from __future__ import annotations

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..contracts import ChatContextSummaryRecord

SUMMARY_SELECT_COLUMNS = """
    summary_id, session_id, parent_summary_id, status, summary_kind,
    persona_scope, covered_from_message_id, covered_to_message_id,
    first_kept_message_id, covered_to_sequence_no, session_origin,
    summary_text, prompt_profile, model_provider, model_id,
    token_count_before, token_count_after, quality_status,
    created_at_ms, updated_at_ms
"""

_SUPERSEDE_ACTIVE_CONTEXT_SUMMARIES_SQL = """
UPDATE chat_context_summaries
SET status = 'superseded', updated_at_ms = ?
WHERE session_id = ?
  AND summary_kind = ?
  AND COALESCE(persona_scope, '') = ?
  AND status = 'active'
  AND summary_id != ?
"""

_UPSERT_CONTEXT_SUMMARY_SQL = """
INSERT INTO chat_context_summaries (
    summary_id,
    session_id,
    parent_summary_id,
    status,
    summary_kind,
    persona_scope,
    covered_from_message_id,
    covered_to_message_id,
    first_kept_message_id,
    covered_to_sequence_no,
    session_origin,
    summary_text,
    prompt_profile,
    model_provider,
    model_id,
    token_count_before,
    token_count_after,
    quality_status,
    created_at_ms,
    updated_at_ms
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(summary_id) DO UPDATE SET
    parent_summary_id = excluded.parent_summary_id,
    status = excluded.status,
    summary_kind = excluded.summary_kind,
    persona_scope = excluded.persona_scope,
    covered_from_message_id = excluded.covered_from_message_id,
    covered_to_message_id = excluded.covered_to_message_id,
    first_kept_message_id = excluded.first_kept_message_id,
    covered_to_sequence_no = excluded.covered_to_sequence_no,
    session_origin = excluded.session_origin,
    summary_text = excluded.summary_text,
    prompt_profile = excluded.prompt_profile,
    model_provider = excluded.model_provider,
    model_id = excluded.model_id,
    token_count_before = excluded.token_count_before,
    token_count_after = excluded.token_count_after,
    quality_status = excluded.quality_status,
    updated_at_ms = excluded.updated_at_ms
"""

_BUMP_SESSION_HISTORY_VERSION_SQL = """
UPDATE chat_sessions
SET history_version = history_version + 1
WHERE session_id = ?
"""

_CLAIM_SESSION_HISTORY_VERSION_SQL = """
UPDATE chat_sessions
SET history_version = history_version + 1
WHERE session_id = ?
  AND history_version = ?
"""


class ChatContextSummaryPersistenceMixin:
    """Persist and query explicitly named session-boundary summaries."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def get_active_context_summary(
        self,
        *,
        session_id: str,
        summary_kind: str,
        persona_scope: str | None = None,
    ) -> ChatContextSummaryRecord | None:
        """Return the active named summary for one session/scope."""
        await self.initialize()
        normalized_scope = str(persona_scope or "").strip()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                f"""
                SELECT {SUMMARY_SELECT_COLUMNS}
                FROM chat_context_summaries
                WHERE session_id = ?
                  AND summary_kind = ?
                  AND COALESCE(persona_scope, '') = ?
                  AND status = 'active'
                ORDER BY covered_to_sequence_no DESC, updated_at_ms DESC
                LIMIT 1
                """,
                (session_id, summary_kind, normalized_scope),
            )
            row = await cur.fetchone()
        return self._row_to_context_summary(row) if row is not None else None

    async def activate_context_summary(self, record: ChatContextSummaryRecord) -> None:
        """Store a summary and supersede the previous active summary in the same scope."""
        await self.initialize()
        normalized_scope = str(record.persona_scope or "").strip()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await self._supersede_active_context_summaries(
                db,
                record,
                normalized_scope,
            )
            await self._upsert_active_context_summary(db, record)
            await self._bump_context_summary_history_version(db, record.session_id)
            await db.commit()

    async def activate_context_summary_if_history_version(
        self,
        record: ChatContextSummaryRecord,
        *,
        expected_history_version: int,
    ) -> bool:
        """Activate a summary only if its source transcript is still current."""
        await self.initialize()
        normalized_scope = str(record.persona_scope or "").strip()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            cursor = await db.execute(
                _CLAIM_SESSION_HISTORY_VERSION_SQL,
                (record.session_id, expected_history_version),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            await self._supersede_active_context_summaries(
                db,
                record,
                normalized_scope,
            )
            await self._upsert_active_context_summary(db, record)
            await db.commit()
        return True

    async def _supersede_active_context_summaries(
        self,
        db: aiosqlite.Connection,
        record: ChatContextSummaryRecord,
        normalized_scope: str,
    ) -> None:
        await db.execute(
            _SUPERSEDE_ACTIVE_CONTEXT_SUMMARIES_SQL,
            (
                record.updated_at_ms,
                record.session_id,
                record.summary_kind,
                normalized_scope,
                record.summary_id,
            ),
        )

    async def _upsert_active_context_summary(
        self,
        db: aiosqlite.Connection,
        record: ChatContextSummaryRecord,
    ) -> None:
        await db.execute(
            _UPSERT_CONTEXT_SUMMARY_SQL,
            self._context_summary_values(record, status="active"),
        )

    async def _bump_context_summary_history_version(
        self,
        db: aiosqlite.Connection,
        session_id: str,
    ) -> None:
        await db.execute(_BUMP_SESSION_HISTORY_VERSION_SQL, (session_id,))

    @staticmethod
    def _context_summary_values(
        record: ChatContextSummaryRecord,
        *,
        status: str | None = None,
    ) -> tuple[object, ...]:
        return (
            record.summary_id,
            record.session_id,
            record.parent_summary_id,
            status or record.status,
            record.summary_kind,
            record.persona_scope,
            record.covered_from_message_id,
            record.covered_to_message_id,
            record.first_kept_message_id,
            record.covered_to_sequence_no,
            record.session_origin,
            record.summary_text,
            record.prompt_profile,
            record.model_provider,
            record.model_id,
            record.token_count_before,
            record.token_count_after,
            record.quality_status,
            record.created_at_ms,
            record.updated_at_ms,
        )

    @staticmethod
    def _row_to_context_summary(row: aiosqlite.Row) -> ChatContextSummaryRecord:
        return ChatContextSummaryRecord(
            summary_id=str(row["summary_id"]),
            session_id=str(row["session_id"]),
            parent_summary_id=(
                str(row["parent_summary_id"]) if row["parent_summary_id"] is not None else None
            ),
            status=str(row["status"]),
            summary_kind=str(row["summary_kind"]),
            persona_scope=str(row["persona_scope"]) if row["persona_scope"] is not None else None,
            covered_from_message_id=(
                str(row["covered_from_message_id"])
                if row["covered_from_message_id"] is not None
                else None
            ),
            covered_to_message_id=(
                str(row["covered_to_message_id"])
                if row["covered_to_message_id"] is not None
                else None
            ),
            first_kept_message_id=(
                str(row["first_kept_message_id"])
                if row["first_kept_message_id"] is not None
                else None
            ),
            covered_to_sequence_no=(
                int(row["covered_to_sequence_no"])
                if row["covered_to_sequence_no"] is not None
                else None
            ),
            session_origin=str(row["session_origin"] or ""),
            summary_text=str(row["summary_text"] or ""),
            prompt_profile=str(row["prompt_profile"] or "general_chat"),
            model_provider=(
                str(row["model_provider"]) if row["model_provider"] is not None else None
            ),
            model_id=str(row["model_id"]) if row["model_id"] is not None else None,
            token_count_before=(
                int(row["token_count_before"]) if row["token_count_before"] is not None else None
            ),
            token_count_after=(
                int(row["token_count_after"]) if row["token_count_after"] is not None else None
            ),
            quality_status=(
                str(row["quality_status"]) if row["quality_status"] is not None else None
            ),
            created_at_ms=int(row["created_at_ms"] or 0),
            updated_at_ms=int(row["updated_at_ms"] or 0),
        )
