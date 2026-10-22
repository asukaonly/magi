"""SQLite owner of atomic L1 event insertion and idempotency."""

from __future__ import annotations

import json
import time

import aiosqlite

from ....core.persistence_errors import PersistenceConflictError
from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryEvent, author_type_code, content_type_code
from ...hybrid_retrieval.fts_utils import tokenize_for_fts
from ..chat_sessions import project_chat_event_to_session
from ..event_payload_store import L1_EVENT_PAYLOAD_TABLE
from ..embeddings.common import FACT_EVENTS_TABLE, L1_EVENT_EMBEDDING_STATE_TABLE, embedding_status_code
from ...evidence import L1RetrievalScope
from ..ports import EventAppend, EventAppendResult, EventVisibility, MemoryEventRecord
from .source_facets import L1_SOURCE_FACETS_TABLE, SqliteSourceFacets, source_facet_values
from .event_mapping import event_record_from_mapping
from .event_queries import SqliteEventQueries
from .event_maintenance import SqliteEventMaintenanceQueries
from .event_deletion import SqliteEventDeletion

L1_SESSION_SEQUENCES_TABLE = "l1_session_sequences"


class SqliteMemoryEventRepository(SqliteEventQueries, SqliteEventMaintenanceQueries, SqliteSourceFacets, SqliteEventDeletion):
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def get(
        self, event_id: str, *, visibility: EventVisibility = "raw",
    ) -> MemoryEventRecord | None:
        if visibility not in {"raw", "active", "user_visible"}:
            raise ValueError("Unknown memory event visibility")
        clauses = ["fact_events.event_id = ?"]
        values: list[object] = [event_id]
        if visibility != "raw":
            clauses.append("fact_events.deleted_at IS NULL")
        if visibility == "user_visible":
            clauses.append("fact_events.l1_retrieval_scope != ?")
            values.append(int(L1RetrievalScope.AUDIT_ONLY))
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT fact_events.*, s.embedding_status, s.embedding_profile_id, "
                "s.embedding_chunk_count, s.last_embedded_at FROM fact_events "
                "LEFT JOIN l1_event_embedding_state s USING(event_id) WHERE "
                + " AND ".join(clauses),
                tuple(values),
            ) as cursor:
                row = await cursor.fetchone()
        return event_record_from_mapping(dict(row)) if row is not None else None

    async def append(self, command: EventAppend) -> EventAppendResult:
        event = command.event
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            existing = await self._existing_event(db, event)
            if existing is not None:
                return existing
            session_seq = await self._resolve_event_session_seq(db, event)
            try:
                await self._insert_fact_event_row(db, command=command, session_seq=session_seq)
            except aiosqlite.IntegrityError as exc:
                raise PersistenceConflictError("Memory event violates a persistence constraint") from exc
            await self._write_event_side_tables(db, command)
            await db.commit()
        return EventAppendResult(event.event_id, inserted=True, session_seq=session_seq)

    async def find_by_idempotency(
        self, *, source: str, event_type: str, idempotency_key: str,
    ) -> str | None:
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                "SELECT event_id FROM fact_events WHERE source = ? AND event_type = ? AND idempotency_key = ? LIMIT 1",
                (source, event_type, idempotency_key),
            ) as cursor:
                row = await cursor.fetchone()
        return str(row[0]) if row is not None else None

    @staticmethod
    async def _existing_event(db: aiosqlite.Connection, event: MemoryEvent) -> EventAppendResult | None:
        if event.idempotency_key:
            async with db.execute(
                "SELECT event_id, session_seq FROM fact_events WHERE source = ? AND event_type = ? AND idempotency_key = ? LIMIT 1",
                (event.source, event.event_type, event.idempotency_key),
            ) as cursor:
                row = await cursor.fetchone()
            if row is not None:
                return EventAppendResult(str(row[0]), False, int(row[1]) if row[1] is not None else None)
        async with db.execute(
            "SELECT event_id, session_seq FROM fact_events WHERE event_id = ?", (event.event_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return EventAppendResult(str(row[0]), False, int(row[1]) if row[1] is not None else None)

    async def _insert_fact_event_row(
        self,
        db: aiosqlite.Connection,
        *,
        command: EventAppend,
        session_seq: int | None,
    ) -> None:
        event = command.event
        await db.execute(
            f"""
            INSERT INTO {FACT_EVENTS_TABLE}(
                event_id, timestamp, created_at,
                event_type, source, source_item_id, idempotency_key, memory_domain,
                cognition_eligible, retention_class, session_id, turn_id, session_seq, user_id,
                content, author_type, content_type, importance_score,
                media_path, metadata_json, deleted_at,
                evidence_status, evidence_class, evidence_rule_version,
                l1_retrieval_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                float(event.timestamp),
                float(event.created_at),
                event.event_type,
                event.source,
                event.source_item_id,
                event.idempotency_key,
                int(event.memory_domain),
                1 if event.cognition_eligible else 0,
                int(event.retention_class),
                event.session_id,
                event.turn_id,
                session_seq,
                event.user_id,
                event.content,
                author_type_code(event.author_type),
                content_type_code(event.content_type),
                float(event.importance_score),
                event.media_path,
                json.dumps(command.metadata) if command.metadata is not None else None,
                None,
                int(command.evidence.status),
                int(command.evidence.classification),
                command.evidence.rule_version,
                int(command.evidence.retrieval_scope),
            ),
        )

    async def _write_event_side_tables(
        self,
        db: aiosqlite.Connection,
        command: EventAppend,
    ) -> None:
        event = command.event
        await self._insert_embedding_state(db, command)
        await self._insert_pinned_payload_if_present(db, command)
        await self._replace_source_facets(db, command)
        await self._sync_event_fts(db, command)
        await project_chat_event_to_session(
            db,
            user_id=event.user_id,
            session_id=event.session_id,
            event_type=event.event_type,
            content=event.content,
            timestamp=float(event.timestamp),
        )

    @staticmethod
    async def _insert_embedding_state(
        db: aiosqlite.Connection,
        command: EventAppend,
    ) -> None:
        event = command.event
        await db.execute(
            f"""
            INSERT OR REPLACE INTO {L1_EVENT_EMBEDDING_STATE_TABLE}(
                event_id, embedding_status, embedding_profile_id,
                embedding_chunk_count, last_embedded_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                embedding_status_code(command.embedding_status),
                command.embedding_profile_id,
                0,
                None,
                time.time(),
            ),
        )

    @staticmethod
    async def _insert_pinned_payload_if_present(
        db: aiosqlite.Connection,
        command: EventAppend,
    ) -> None:
        event = command.event
        if not event.pinned_payload:
            return
        await db.execute(
            f"INSERT OR REPLACE INTO {L1_EVENT_PAYLOAD_TABLE}"
            "(event_id, content, created_at) VALUES (?, ?, ?)",
            (event.event_id, event.pinned_payload, float(event.created_at)),
        )

    @staticmethod
    async def _sync_event_fts(
        db: aiosqlite.Connection,
        command: EventAppend,
    ) -> None:
        event = command.event
        tokenized = tokenize_for_fts(command.search_text)
        await db.execute(
            "DELETE FROM l1_events_fts WHERE event_id = ?",
            (event.event_id,),
        )
        await db.execute(
            "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
            (event.event_id, tokenized),
        )

    @staticmethod
    async def _replace_source_facets(db: aiosqlite.Connection, command: EventAppend) -> None:
        if command.source_facets:
            await db.executemany(
                f"INSERT INTO {L1_SOURCE_FACETS_TABLE}(event_id, source, facet_name, text_value, normalized_text_value, numeric_value, timestamp_value, json_value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [source_facet_values(facet) for facet in command.source_facets],
            )

    async def _resolve_event_session_seq(
        self,
        db: aiosqlite.Connection,
        event: MemoryEvent,
    ) -> int | None:
        session_id = str(event.session_id or "").strip()
        if not session_id:
            return event.session_seq
        if event.session_seq is not None:
            explicit_seq = max(int(event.session_seq), 0)
            await self._advance_session_sequence(
                db,
                session_id=session_id,
                next_seq=explicit_seq + 1,
            )
            return explicit_seq
        return await self._allocate_session_seq(db, session_id=session_id)

    @staticmethod
    async def _allocate_session_seq(
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> int:
        async with db.execute(
            f"""
            INSERT INTO {L1_SESSION_SEQUENCES_TABLE}(session_id, next_seq, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                next_seq = next_seq + 1,
                updated_at = excluded.updated_at
            RETURNING next_seq - 1
            """,
            (session_id, time.time()),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Failed to allocate L1 session sequence")
        return int(row[0])

    @staticmethod
    async def _advance_session_sequence(
        db: aiosqlite.Connection,
        *,
        session_id: str,
        next_seq: int,
    ) -> None:
        await db.execute(
            f"""
            INSERT INTO {L1_SESSION_SEQUENCES_TABLE}(session_id, next_seq, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                next_seq = MAX(next_seq, excluded.next_seq),
                updated_at = excluded.updated_at
            """,
            (session_id, max(int(next_seq), 0), time.time()),
        )

