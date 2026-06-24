"""Write and destructive maintenance operations for L1 event storage."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, cast

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...events.events import EventTypes
from ..embedding.sqlite_vec_index import SqliteVecIndex
from ..evidence import (
    EVIDENCE_RULE_VERSION,
    EvidenceClass,
    EvidenceStatus,
    L1RetrievalScope,
    classify_event_evidence,
    resolve_l2_policy,
)
from ..event_contracts import MemoryEvent, author_type_code, content_type_code
from ..hybrid_retrieval.fts_utils import tokenize_for_fts
from .chat_sessions import project_chat_event_to_session
from .event_payload_store import L1_EVENT_PAYLOAD_TABLE
from .embeddings.common import (
    EVENT_CHUNKS_TABLE,
    FACT_EVENTS_TABLE,
    L1_EVENT_EMBEDDING_STATE_TABLE,
    embedding_status_code,
)

logger = logging.getLogger(__name__)
L1_SESSION_SEQUENCES_TABLE = "l1_session_sequences"


def _merge_evidence_into_metadata(
    metadata_json: dict | None, reason_code: str | None
) -> dict | None:
    """Embed the governance reason_code under a ``_evidence`` namespace inside
    the event's metadata_json, preserving the event's own keys.

    Returns None only when there is nothing to store (no reason_code and no
    pre-existing metadata), so the column can stay NULL. The namespace keeps
    governance provenance separate from the event's own metadata, and makes a
    future migration to a dedicated column a clean double-read.
    """
    if not reason_code and not metadata_json:
        return None
    merged = dict(metadata_json or {})
    if reason_code:
        existing = merged.get("_evidence")
        evidence = dict(existing) if isinstance(existing, dict) else {}
        evidence["reason_code"] = reason_code
        merged["_evidence"] = evidence
    return merged


L1_STORE_DIAGNOSTIC_EVENT_TYPES = {
    EventTypes.USER_MESSAGE,
    EventTypes.AI_RESPONSE,
    EventTypes.ACTION_EXECUTED,
}


class L1EventWriteHostProtocol(Protocol):
    db_path: str
    _embedding_queue: Any | None
    _embedding_workers: list[asyncio.Task[None]]
    _initialized: bool
    _vector_index: SqliteVecIndex | None

    async def initialize(self) -> None: ...

    def get_search_text(self, event: MemoryEvent) -> str: ...

    def _initial_embedding_status(self, event: MemoryEvent) -> str: ...

    def _initial_embedding_profile_id(self, event: MemoryEvent) -> str | None: ...

    async def _resolve_existing_event_id(self, db: Any, event: MemoryEvent) -> str | None: ...

    async def _schedule_event_embedding(self, event: MemoryEvent) -> None: ...

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent: ...

    async def count_events(self) -> int: ...

    async def _list_chunk_ids_for_event(self, event_id: str) -> list[str]: ...

    async def _replace_source_facets_for_event(
        self,
        db: aiosqlite.Connection,
        event: MemoryEvent,
    ) -> None: ...


@dataclass(slots=True)
class L1EvidenceBackfillResult:
    """Summary returned by L1 evidence annotation backfill."""

    matched: int = 0
    processed: int = 0
    updated: int = 0
    would_update: int = 0
    errors: int = 0
    dry_run: bool = False
    by_l1_retrieval_scope: dict[str, int] = field(default_factory=dict)


class L1EventWriteMixin:
    """Persist, clear, and soft-delete normalized L1 memory events."""

    async def store(self, event: MemoryEvent) -> str:
        """Persist a normalized memory event."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        if event.source == "calendar":
            logger.info(
                "L1EventStore storing calendar event | "
                "event_id=%s event_type=%s source_item_id=%s content=%s metadata_json=%s",
                event.event_id,
                event.event_type,
                event.source_item_id,
                event.content,
                event.metadata_json,
            )
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore persisting event | event_id=%s type=%s session_id=%s user_id=%s correlation_id=%s",
                event.event_id,
                event.event_type,
                event.session_id,
                event.user_id,
                event.correlation_id,
            )
        evidence_values = self._resolve_event_evidence_values(event)
        logger.debug(
            "L1 evidence classified | event_id=%s class=%s reason=%s status=%s",
            event.event_id,
            evidence_values["evidence_class"],
            evidence_values.get("reason_code"),
            evidence_values["evidence_status"],
        )
        merged_metadata = _merge_evidence_into_metadata(
            event.metadata_json, evidence_values.get("reason_code")
        )
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            existing_event_id = await host._resolve_existing_event_id(db, event)
            if existing_event_id:
                if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
                    logger.info(
                        "L1EventStore skipped duplicate event | event_id=%s type=%s",
                        event.event_id,
                        event.event_type,
                    )
                return existing_event_id
            session_seq = await self._resolve_event_session_seq(db, event)
            event.session_seq = session_seq
            cursor = await db.execute(
                f"""
                INSERT OR IGNORE INTO {FACT_EVENTS_TABLE}(
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
                    json.dumps(merged_metadata) if merged_metadata is not None else None,
                    None,
                    evidence_values["evidence_status"],
                    evidence_values["evidence_class"],
                    evidence_values["evidence_rule_version"],
                    evidence_values["l1_retrieval_scope"],
                ),
            )
            inserted = cursor.rowcount > 0
            if not inserted:
                await db.rollback()
                existing_event_id = await host._resolve_existing_event_id(db, event)
                if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
                    logger.info(
                        "L1EventStore skipped duplicate event | event_id=%s type=%s",
                        event.event_id,
                        event.event_type,
                    )
                return existing_event_id or event.event_id
            await db.execute(
                f"""
                INSERT OR REPLACE INTO {L1_EVENT_EMBEDDING_STATE_TABLE}(
                    event_id, embedding_status, embedding_profile_id,
                    embedding_chunk_count, last_embedded_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    embedding_status_code(host._initial_embedding_status(event)),
                    host._initial_embedding_profile_id(event),
                    0,
                    None,
                    time.time(),
                ),
            )
            # P3: pin the capture-time full text in the satellite table, keyed by
            # the just-inserted event_id and co-transactional with the row above.
            # Sparse — only when a sensor provided one. The row's content column
            # stays the lean summary; L2 reads this full body at extraction.
            if event.pinned_payload:
                await db.execute(
                    f"INSERT OR REPLACE INTO {L1_EVENT_PAYLOAD_TABLE}"
                    "(event_id, content, created_at) VALUES (?, ?, ?)",
                    (event.event_id, event.pinned_payload, float(event.created_at)),
                )
            await host._replace_source_facets_for_event(db, event)
            tokenized = tokenize_for_fts(host.get_search_text(event))
            await db.execute(
                "DELETE FROM l1_events_fts WHERE event_id = ?",
                (event.event_id,),
            )
            await db.execute(
                "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                (event.event_id, tokenized),
            )
            await project_chat_event_to_session(
                db,
                user_id=event.user_id,
                session_id=event.session_id,
                event_type=event.event_type,
                content=event.content,
                timestamp=float(event.timestamp),
            )
            await db.commit()
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore persisted event | event_id=%s type=%s",
                event.event_id,
                event.event_type,
            )
        await host._schedule_event_embedding(event)
        return event.event_id

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

    def _resolve_event_evidence_values(self, event: MemoryEvent) -> dict[str, Any]:
        try:
            classification = classify_event_evidence(event)
        except Exception as exc:
            logger.warning(
                "L1 evidence classification failed | event_id=%s error=%s",
                event.event_id,
                exc,
            )
            return {
                "evidence_status": int(EvidenceStatus.CLASSIFICATION_ERROR),
                "evidence_class": int(EvidenceClass.UNKNOWN),
                "evidence_rule_version": EVIDENCE_RULE_VERSION,
                "l1_retrieval_scope": int(L1RetrievalScope.NONE),
                "reason_code": None,
            }

        try:
            policy = resolve_l2_policy(classification)
        except Exception as exc:
            logger.warning(
                "L1 evidence policy resolution failed | event_id=%s evidence_class=%s error=%s",
                event.event_id,
                classification.evidence_class,
                exc,
            )
            return {
                "evidence_status": int(EvidenceStatus.POLICY_ERROR),
                "evidence_class": int(EvidenceClass.from_value(classification.evidence_class)),
                "evidence_rule_version": EVIDENCE_RULE_VERSION,
                "l1_retrieval_scope": int(L1RetrievalScope.NONE),
                "reason_code": None,
            }

        return {
            "evidence_status": int(EvidenceStatus.CLASSIFIED),
            "evidence_class": int(EvidenceClass.from_value(classification.evidence_class)),
            "evidence_rule_version": EVIDENCE_RULE_VERSION,
            "l1_retrieval_scope": int(L1RetrievalScope.from_value(policy.l1_retrieval_scope)),
            "reason_code": classification.reason_code,
        }

    async def backfill_evidence_annotations(
        self,
        *,
        user_id: str | None = None,
        source_filters: list[str] | None = None,
        event_type: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        batch_size: int = 500,
        stale_only: bool = True,
        dry_run: bool = False,
    ) -> L1EvidenceBackfillResult:
        """Classify and persist evidence policy columns for existing L1 events."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()

        where_parts = ["deleted_at IS NULL"]
        args: list[Any] = []
        if stale_only:
            where_parts.append(
                """
                (
                    evidence_status != ?
                    OR evidence_rule_version != ?
                )
                """
            )
            args.extend([int(EvidenceStatus.CLASSIFIED), EVIDENCE_RULE_VERSION])
        if user_id:
            where_parts.append("user_id = ?")
            args.append(user_id)
        if source_filters:
            placeholders = ", ".join("?" for _ in source_filters)
            where_parts.append(f"source IN ({placeholders})")
            args.extend(source_filters)
        if event_type:
            where_parts.append("event_type = ?")
            args.append(event_type)
        if start_time is not None:
            where_parts.append("timestamp >= ?")
            args.append(float(start_time))
        if end_time is not None:
            where_parts.append("timestamp <= ?")
            args.append(float(end_time))

        where_clause = " AND ".join(where_parts)
        result = L1EvidenceBackfillResult(dry_run=bool(dry_run))
        last_seen_id = 0
        effective_batch_size = max(1, int(batch_size))

        update_sql = f"""
            UPDATE {FACT_EVENTS_TABLE}
            SET evidence_status = ?,
                evidence_class = ?,
                evidence_rule_version = ?,
                l1_retrieval_scope = ?
            WHERE event_id = ?
        """

        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT COUNT(*) FROM {FACT_EVENTS_TABLE} WHERE {where_clause}",
                tuple(args),
            ) as cursor:
                row = await cursor.fetchone()
                result.matched = int(row[0]) if row else 0

            while True:
                async with db.execute(
                    f"""
                    SELECT *
                    FROM {FACT_EVENTS_TABLE}
                    WHERE {where_clause}
                      AND id > ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (*args, last_seen_id, effective_batch_size),
                ) as cursor:
                    rows = await cursor.fetchall()
                if not rows:
                    break

                updates: list[tuple[Any, ...]] = []
                for row in rows:
                    last_seen_id = max(last_seen_id, int(row["id"]))
                    try:
                        event = host._row_to_memory_event(row)
                        values = self._resolve_event_evidence_values(event)
                    except Exception as exc:  # noqa: BLE001
                        result.errors += 1
                        logger.warning(
                            "L1 evidence backfill skipped event | event_id=%s error=%s",
                            row["event_id"],
                            exc,
                        )
                        continue

                    result.processed += 1
                    scope = L1RetrievalScope.from_value(values["l1_retrieval_scope"]).label
                    result.by_l1_retrieval_scope[scope] = (
                        result.by_l1_retrieval_scope.get(scope, 0) + 1
                    )
                    if dry_run:
                        result.would_update += 1
                        continue
                    updates.append(
                        (
                            values["evidence_status"],
                            values["evidence_class"],
                            values["evidence_rule_version"],
                            values["l1_retrieval_scope"],
                            event.event_id,
                        )
                    )

                if updates:
                    await db.executemany(update_sql, updates)
                    await db.commit()
                    result.updated += len(updates)

        return result

    async def clear(self) -> int:
        """Delete all events by dropping and recreating the DB file."""
        host = cast(L1EventWriteHostProtocol, self)
        logger.info("L1EventStore.clear: counting events before wipe")
        count = await host.count_events()
        logger.info("L1EventStore.clear: total=%d, stopping embedding workers", count)

        if host._embedding_queue is not None and host._embedding_workers:
            for _ in host._embedding_workers:
                await host._embedding_queue.put(None)
            await asyncio.gather(*host._embedding_workers, return_exceptions=True)
            host._embedding_workers = []
            logger.info("L1EventStore.clear: embedding workers stopped")

        if host._vector_index is not None:
            logger.info("L1EventStore.clear: closing vec index connection")
            await host._vector_index.close()

        db_path = Path(host.db_path)
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(db_path) + suffix)
            if path.exists():
                logger.info("L1EventStore.clear: deleting %s", path)
                path.unlink()

        host._initialized = False
        logger.info("L1EventStore.clear: reinitializing schema at %s", db_path)

        await host.initialize()
        logger.info("L1EventStore.clear: done, removed %d events", count)

        return count

    async def mark_deleted(self, event_id: str, *, deleted_at: Optional[float] = None) -> bool:
        """Soft-delete an event."""
        host = cast(L1EventWriteHostProtocol, self)
        await host.initialize()
        deleted_timestamp = float(deleted_at or time.time())
        chunk_ids = await host._list_chunk_ids_for_event(event_id)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                f"UPDATE {FACT_EVENTS_TABLE} SET deleted_at = ? WHERE event_id = ?",
                (deleted_timestamp, event_id),
            )
            if cursor.rowcount > 0:
                await db.execute(
                    "DELETE FROM l1_events_fts WHERE event_id = ?",
                    (event_id,),
                )
                await db.execute(
                    f"DELETE FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                    (event_id,),
                )
            await db.commit()
        if cursor.rowcount > 0 and host._vector_index is not None:
            for chunk_id in chunk_ids:
                await host._vector_index.delete_entity(entity_id=chunk_id)
        return cursor.rowcount > 0


__all__ = [
    "L1EvidenceBackfillResult",
    "L1EventWriteMixin",
    "L1_STORE_DIAGNOSTIC_EVENT_TYPES",
]
